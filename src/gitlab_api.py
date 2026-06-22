"""
gitlab_api.py  ——  GitLab 适配(与 GitHub 那套对称)
====================================================
核心引擎(规则 / Semgrep / AI / 配置)完全平台无关;只有两头是平台专属:
  1) 采集:从 GitLab MR 拿改动 -> 统一的 PRContext;
  2) 回写:把结果写成 GitLab 的「note(汇总)」+「discussion(行内)」。

GitHub vs GitLab 的对照:
  PR              ->  MR(Merge Request)
  api.github.com  ->  $CI_API_V4_URL(如 https://gitlab.com/api/v4)
  PR 评论/Review  ->  notes(整条)/ discussions(带行号位置)
  GITHUB_TOKEN    ->  GITLAB_TOKEN(需有 api 权限的 PAT / Project Access Token)

GitLab CI 预定义变量我们用到:CI_API_V4_URL / CI_PROJECT_ID / CI_MERGE_REQUEST_IID。
"""

from __future__ import annotations
import json
import os
import urllib.request

from collect_pr import ChangedFile, PRContext

MARKER = "<!-- mobile-pr-guard-review -->"
INLINE_MARKER = "<!-- mpg-inline -->"
_SEV_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}


def _api(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("PRIVATE-TOKEN", token)            # GitLab 用这个头认证
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def _env():
    """返回 (api_base, project_id, mr_iid, token);缺任一则返回 None 表示非 GitLab/本地。"""
    api = os.environ.get("CI_API_V4_URL")
    project = os.environ.get("CI_PROJECT_ID")
    iid = os.environ.get("CI_MERGE_REQUEST_IID")
    token = os.environ.get("GITLAB_TOKEN")
    if not (api and project and iid and token):
        return None
    return api, project, iid, token


# ---------- 采集 ----------
def collect_from_gitlab() -> PRContext:
    api = os.environ["CI_API_V4_URL"]
    project = os.environ["CI_PROJECT_ID"]
    iid = os.environ["CI_MERGE_REQUEST_IID"]
    token = os.environ["GITLAB_TOKEN"]
    base = f"{api}/projects/{project}/merge_requests/{iid}"

    mr = _api("GET", base, token)                     # MR 元信息 + diff_refs
    refs = (mr.get("diff_refs") or {}) if isinstance(mr, dict) else {}
    changes = _api("GET", f"{base}/changes", token)   # 改了哪些文件 + 每个文件的 diff

    changed: list[ChangedFile] = []
    for ch in (changes.get("changes", []) if isinstance(changes, dict) else []):
        if ch.get("deleted_file"):
            continue
        changed.append(ChangedFile(
            filename=ch.get("new_path") or ch.get("old_path") or "",
            status="added" if ch.get("new_file") else "modified",
            patch=ch.get("diff", "") or "",           # 统一 diff 文本,复用同一套解析
        ))

    return PRContext(
        pr_number=int(iid),
        title=mr.get("title", "") if isinstance(mr, dict) else "",
        base_sha=refs.get("base_sha", ""),
        head_sha=refs.get("head_sha", ""),
        start_sha=refs.get("start_sha", ""),
        repo=str(project),
        changed_files=changed,
    )


# ---------- 回写:汇总 note(幂等更新) ----------
def post_or_update_gitlab(ctx, body_markdown: str) -> str:
    env = _env()
    if not env or ctx.pr_number is None:
        return "[local] 未发评论(非 GitLab MR 环境)。"
    api, project, iid, token = env
    base = f"{api}/projects/{project}/merge_requests/{iid}"

    sha_short = (ctx.head_sha or "")[:8]
    full_body = (
        f"{MARKER}\n# 🛡️ Mobile PR Guard Review\n_commit `{sha_short}`_\n\n"
        f"{body_markdown}\n\n"
        f"<sub>由 Mobile PR Guard 自动生成,仅供参考,最终判断以人工 review 为准。</sub>"
    )

    notes = _api("GET", f"{base}/notes?per_page=100", token)
    existing = None
    if isinstance(notes, list):
        existing = next((n for n in notes if MARKER in (n.get("body") or "")), None)
    if existing:
        _api("PUT", f"{base}/notes/{existing['id']}", token, {"body": full_body})
    else:
        _api("POST", f"{base}/notes", token, {"body": full_body})
    return f"{base}"


# ---------- 回写:行内评论(discussion + position) ----------
def _delete_old_inline_gitlab(base: str, token: str) -> None:
    discussions = _api("GET", f"{base}/discussions?per_page=100", token)
    if not isinstance(discussions, list):
        return
    for d in discussions:
        for n in d.get("notes", []) or []:
            if INLINE_MARKER in (n.get("body") or ""):
                try:
                    _api("DELETE", f"{base}/discussions/{d['id']}/notes/{n['id']}", token)
                except Exception:
                    pass


def post_inline_gitlab(ctx, findings) -> int:
    env = _env()
    if not env or ctx.pr_number is None:
        return 0
    api, project, iid, token = env
    base = f"{api}/projects/{project}/merge_requests/{iid}"

    _delete_old_inline_gitlab(base, token)

    count = 0
    for f in findings:
        if not f.line or f.line <= 0 or not f.file or f.file.startswith("("):
            continue
        emoji = _SEV_EMOJI.get(f.severity, "")
        body = (f"{INLINE_MARKER}\n{emoji} **[{f.severity}] {f.rule}**\n\n"
                f"{f.message}\n\n💡 {f.suggestion}")
        position = {
            "position_type": "text",
            "base_sha": ctx.base_sha, "start_sha": ctx.start_sha, "head_sha": ctx.head_sha,
            "new_path": f.file, "old_path": f.file, "new_line": f.line,
        }
        try:
            _api("POST", f"{base}/discussions", token, {"body": body, "position": position})
            count += 1
        except Exception as e:
            # 该行不在 diff 内时 GitLab 会拒 -> 跳过,留给汇总 note
            print(f"[gitlab-inline] 跳过 {f.file}:{f.line}({e})")
    return count
