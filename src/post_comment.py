"""
post_comment.py  ——  对应路线图「第 4 周:回写 PR 评论」
=======================================================
把 review 写回 PR。关键技巧:用一个隐藏标记(HTML 注释)认出
「上一次是我发的那条评论」,然后更新它,而不是每次都新发一条把 PR 刷屏。

这叫「幂等更新」:同一个 PR 不管跑多少次,永远只有一条 Guard 评论。
"""

from __future__ import annotations
import json
import os
import urllib.request

MARKER = "<!-- mobile-pr-guard-review -->"


def _api(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def _find_existing_comment(repo: str, pr_number: int, token: str) -> int | None:
    """翻 PR 已有评论,找带 MARKER 的那条,返回它的 id。"""
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}"
        comments = _api("GET", url, token)
        if not comments:
            return None
        for c in comments:
            if MARKER in (c.get("body") or ""):
                return c["id"]
        if len(comments) < 100:
            return None
        page += 1


def post_or_update(ctx, body_markdown: str) -> str:
    """返回评论的 html_url(本地模式下返回提示字符串)。"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token or ctx.pr_number is None:
        # 本地模式:不发评论,直接返回 review 文本,方便你肉眼看
        return "[local] 未发评论(没有 GITHUB_TOKEN 或没有 PR 号),review 内容见上方。"

    sha_short = (ctx.head_sha or "")[:7]
    full_body = (
        f"{MARKER}\n"
        f"# 🛡️ Mobile PR Guard Review\n"
        f"_commit `{sha_short}`_\n\n"
        f"{body_markdown}\n\n"
        f"<sub>由 Mobile PR Guard 自动生成,仅供参考,最终判断以人工 review 为准。</sub>"
    )

    existing = _find_existing_comment(ctx.repo, ctx.pr_number, token)
    if existing:
        url = f"https://api.github.com/repos/{ctx.repo}/issues/comments/{existing}"
        res = _api("PATCH", url, token, {"body": full_body})
    else:
        url = f"https://api.github.com/repos/{ctx.repo}/issues/{ctx.pr_number}/comments"
        res = _api("POST", url, token, {"body": full_body})
    return res.get("html_url", "(已提交评论)")
