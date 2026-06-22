"""
collect_pr.py  ——  对应路线图「第 1 周:PR 数据采集」
=====================================================
目标:不管在 GitHub 云端跑,还是在你本地电脑跑,都能拿到一份统一的
「PR 上下文」(改了哪些文件、每个文件改了什么)。

两种模式:
1) GitHub Actions 模式:从环境变量 + GitHub API 拿真实 PR 数据。
2) 本地模式(--local 目录):把目录里的文件当成「全部新增」,
   方便你不连 GitHub 也能测规则。

产出统一的数据结构 ChangedFile,后面规则扫描 / AI 都基于它。
"""

from __future__ import annotations
import json
import os
import re
import urllib.request
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ChangedFile:
    filename: str            # 文件路径,如 app/src/main/AndroidManifest.xml
    status: str              # added / modified / removed
    patch: str               # 这个文件的 diff(可能为空,比如二进制文件)
    additions: int = 0
    deletions: int = 0

    def added_lines_with_lineno(self) -> list[tuple[int, str]]:
        """返回 [(新文件中的真实行号, 该行内容), ...],只含新增行。
        通过解析 diff 的 hunk 头 `@@ -a,b +c,d @@` 推算真实行号:
        - 看到 hunk 头,就把行号重置到该 hunk 的新文件起始行(+ 后面的数字);
        - 新增行(+)记录并 +1;删除行(-)不占新文件行号;上下文行 +1。
        本地模式没有 hunk 头,则从第 1 行起按顺序计数,等价于文件行号。"""
        if not self.patch:
            return []
        out: list[tuple[int, str]] = []
        new_line = 1
        for ln in self.patch.splitlines():
            if ln.startswith("+++") or ln.startswith("---"):
                continue  # 文件名头,跳过,不计行
            if ln.startswith("@@"):
                m = re.search(r"\+(\d+)", ln)
                if m:
                    new_line = int(m.group(1))
                continue
            if ln.startswith("+"):
                out.append((new_line, ln[1:]))  # 去掉开头的 +
                new_line += 1
            elif ln.startswith("-"):
                pass  # 删除行只在旧文件里,不占新文件行号
            else:
                new_line += 1  # 上下文行,新文件里也有
        return out

    def added_lines(self) -> list[str]:
        """只要新增行的内容(不要行号),供 release_risk 等按文本匹配用。"""
        return [text for _, text in self.added_lines_with_lineno()]

    @property
    def ext(self) -> str:
        return os.path.splitext(self.filename)[1].lower()


@dataclass
class PRContext:
    pr_number: Optional[int]        # GitHub: PR 号;GitLab: MR iid
    title: str
    base_sha: str
    head_sha: str
    repo: str                       # GitHub: owner/name;GitLab: project id
    changed_files: list[ChangedFile]
    start_sha: str = ""             # GitLab 行内评论需要 base/start/head 三个 sha

    def to_json(self) -> dict:
        d = asdict(self)
        return d


# ---------- GitHub API 小工具(不引第三方库,标准库够用) ----------
def _gh_get(url: str, token: str) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def collect_from_github() -> PRContext:
    """在 GitHub Actions 里跑时用这个。
    GitHub 会把这次事件的全部信息写进一个 JSON 文件,
    路径放在环境变量 GITHUB_EVENT_PATH 里。"""
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]            # 例:nathan/demo-app
    event_path = os.environ["GITHUB_EVENT_PATH"]

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    pr = event["pull_request"]
    pr_number = pr["number"]
    title = pr.get("title", "")
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]

    # 调 GitHub API 拿这个 PR 改了哪些文件,以及每个文件的 diff(patch)
    # 接口会分页,每页最多 100 个文件,这里翻页直到取完
    changed: list[ChangedFile] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}"
        data = json.loads(_gh_get(url, token))
        if not data:
            break
        for item in data:
            changed.append(ChangedFile(
                filename=item["filename"],
                status=item.get("status", "modified"),
                patch=item.get("patch", "") or "",
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
            ))
        if len(data) < 100:
            break
        page += 1

    return PRContext(
        pr_number=pr_number, title=title, base_sha=base_sha,
        head_sha=head_sha, repo=repo, changed_files=changed,
    )


def collect_from_local(root: str) -> PRContext:
    """本地测试模式:把一个目录里的所有文本文件当成「整文件新增」。
    这样你不连 GitHub 也能验证规则扫描逻辑。"""
    # Android / iOS + 常见后端/前端语言(供 Semgrep 跨语言扫描)
    interesting_ext = (".kt", ".java", ".gradle", ".kts", ".xml", ".pro",
                       ".swift", ".plist", ".entitlements",
                       ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rb")
    interesting_names = ("podfile", "podfile.lock", "package.swift")
    changed: list[ChangedFile] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            low = full.lower()
            if not (low.endswith(interesting_ext)
                    or os.path.basename(low) in interesting_names):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            # 把整文件内容伪装成 diff:每行前面加 +,模拟「全部是新增」
            patch = "\n".join("+" + ln for ln in content.splitlines())
            changed.append(ChangedFile(
                filename=rel, status="added", patch=patch,
                additions=content.count("\n"), deletions=0,
            ))

    return PRContext(
        pr_number=None, title="[local test] " + os.path.basename(os.path.abspath(root)),
        base_sha="LOCAL", head_sha="LOCAL", repo="local/demo",
        changed_files=changed,
    )
