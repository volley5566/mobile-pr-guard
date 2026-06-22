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


# ============ 行内评论(贴在对应代码行下面) ============
# GitHub 的 PR 评论分两种:上面 post_or_update 发的是「会话评论」(底部一整条);
# 这里发的是「行内评论」(Review comment),贴在 diff 里某一行旁边——
# 就是你在公司 review 时看到的那种「代码下面跟一条评论」。
# 约束:只能评论 diff 里出现过的行,且行号必须精确(所以前面要先把行号修准)。

INLINE_MARKER = "<!-- mpg-inline -->"
_SEV_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}


def _list_review_comments(repo: str, pr_number: int, token: str) -> list:
    out, page = [], 1
    while True:
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments?per_page=100&page={page}"
        comments = _api("GET", url, token)
        if not comments:
            break
        out.extend(comments)
        if len(comments) < 100:
            break
        page += 1
    return out


def _delete_old_inline(repo: str, pr_number: int, token: str) -> None:
    """删掉上一轮自己贴的行内评论(认带 INLINE_MARKER 的),实现幂等、不刷屏。"""
    for c in _list_review_comments(repo, pr_number, token):
        if INLINE_MARKER in (c.get("body") or ""):
            try:
                _api("DELETE", f"https://api.github.com/repos/{repo}/pulls/comments/{c['id']}", token)
            except Exception:
                pass  # 已被删/无权限都无所谓,继续


def post_inline_comments(ctx, findings) -> int:
    """把「定位到具体行」的 finding 贴成行内评论。返回成功贴出的条数。
    line<=0 或非真实文件(如『(整个 PR)』)的 finding 不在这里贴,留给底部汇总。"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token or ctx.pr_number is None:
        return 0

    _delete_old_inline(ctx.repo, ctx.pr_number, token)

    count = 0
    for f in findings:
        if not f.line or f.line <= 0 or not f.file or f.file.startswith("("):
            continue
        emoji = _SEV_EMOJI.get(f.severity, "")
        body = (
            f"{INLINE_MARKER}\n"
            f"{emoji} **[{f.severity}] {f.rule}**\n\n"
            f"{f.message}\n\n"
            f"💡 {f.suggestion}"
        )
        payload = {
            "body": body, "commit_id": ctx.head_sha,
            "path": f.file, "line": f.line, "side": "RIGHT",
        }
        url = f"https://api.github.com/repos/{ctx.repo}/pulls/{ctx.pr_number}/comments"
        try:
            _api("POST", url, token, payload)
            count += 1
        except Exception as e:
            # 该行不在 diff 内时 GitHub 会拒(422)-> 跳过,该项仍会出现在底部汇总
            print(f"[inline] 跳过 {f.file}:{f.line}({e})")
    return count
