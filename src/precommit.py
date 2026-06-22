"""
precommit.py  ——  本地「提交前拦截」(被 pre-commit hook 调用)
=============================================================
和 CI 不同,这个在你 `git commit` 的那一刻、在你自己电脑上跑:
- 用 `git diff --cached` 拿到这次【已暂存(staged)】的改动(精确到行);
- 复用同一套规则 + Semgrep 扫描(不跑 detekt 等重型工具,提交要快);
- 发现 HIGH 风险就拦下这次提交(退出码 1),否则放行。

想临时跳过一次:  git commit --no-verify
复用 CI 的同一套逻辑,所以「本地拦到的」和「PR 上报的」一致。
"""

from __future__ import annotations
import os
import subprocess
import sys

from config import load_config
from collect_pr import ChangedFile, PRContext
from rules import run_rules, sort_by_severity
from semgrep_scan import run_semgrep


def _staged_diff() -> str:
    """这次提交将要包含的 diff(已暂存内容)。"""
    return subprocess.run(
        ["git", "diff", "--cached", "--no-color"],
        capture_output=True, text=True,
    ).stdout


def _split_per_file(diff_text: str) -> list[ChangedFile]:
    """把整段 `git diff --cached` 按文件切成一个个 ChangedFile。
    每个文件的 patch 仍带 @@ hunk 头,交给 added_lines_with_lineno 算真实行号。"""
    files: list[ChangedFile] = []
    cur_path = None
    cur_lines: list[str] = []

    def flush():
        nonlocal cur_path, cur_lines
        if cur_path and cur_lines:
            files.append(ChangedFile(filename=cur_path, status="modified",
                                     patch="\n".join(cur_lines)))
        cur_lines = []

    for ln in diff_text.splitlines():
        if ln.startswith("diff --git "):
            flush()
            cur_path = None
        elif ln.startswith("+++ b/"):
            cur_path = ln[len("+++ b/"):].strip()
        elif ln.startswith("+++ "):
            cur_path = None          # +++ /dev/null(删除文件),跳过
        else:
            cur_lines.append(ln)
    flush()
    return [f for f in files if f.filename]


def main() -> int:
    repo_root = os.getcwd()
    cfg = load_config(repo_root)

    diff = _staged_diff()
    if not diff.strip():
        return 0
    changed = _split_per_file(diff)
    if not changed:
        return 0

    ctx = PRContext(
        pr_number=None, title="[pre-commit]", base_sha="STAGED",
        head_sha="STAGED", repo="local/precommit", changed_files=changed,
    )
    findings = sort_by_severity(run_rules(ctx, cfg) + run_semgrep(ctx, cfg, repo_root))

    highs = [f for f in findings if f.severity == "HIGH"]
    mediums = sum(1 for f in findings if f.severity == "MEDIUM")
    lows = sum(1 for f in findings if f.severity == "LOW")

    if not highs:
        print(f"🛡️ Mobile PR Guard:暂存改动无 HIGH 风险"
              f"({mediums} MEDIUM / {lows} LOW),放行。")
        return 0

    print("🛡️ Mobile PR Guard:发现 HIGH 风险,已拦下本次提交\n")
    for f in highs:
        loc = f"{f.file}:{f.line}" if f.line else f.file
        print(f"  🔴 {loc}\n     {f.message}\n     💡 {f.suggestion}\n")
    print(f"(另有 {mediums} MEDIUM / {lows} LOW,不阻塞)")
    print("\n修掉上面的 HIGH 后再提交;确需跳过本次检查:git commit --no-verify")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
