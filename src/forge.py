"""
forge.py  ——  代码托管平台适配层(GitHub / GitLab / 本地)
=========================================================
和 ai_review 里的「多模型 PROVIDERS」是同一个套路:把「平台差异」收敛到这一处,
上层(main.py)只管调 collect / post_summary / post_inline,不关心是 GitHub 还是 GitLab。

forge(锻造厂)是社区对「代码托管平台」的通称(GitHub/GitLab/Gitea…)。
新增一个平台 = 在这里加一个分支 + 写它的采集/回写,核心引擎一行都不用改。
"""

from __future__ import annotations
import os

import collect_pr
from post_comment import post_or_update, post_inline_comments
import gitlab_api


def detect(local_dir) -> str:
    """判断当前在什么环境跑:local / gitlab / github。"""
    if local_dir:
        return "local"
    if os.environ.get("GITLAB_CI") or os.environ.get("CI_MERGE_REQUEST_IID"):
        return "gitlab"
    return "github"   # 默认 GitHub(保持原有行为)


def collect(forge: str, local_dir):
    if forge == "local":
        return collect_pr.collect_from_local(local_dir)
    if forge == "gitlab":
        return gitlab_api.collect_from_gitlab()
    return collect_pr.collect_from_github()


def post_summary(forge: str, ctx, review_md: str) -> str:
    if forge == "gitlab":
        return gitlab_api.post_or_update_gitlab(ctx, review_md)
    return post_or_update(ctx, review_md)          # github / local 都走这条(local 自动跳过)


def post_inline(forge: str, ctx, findings) -> int:
    if forge == "gitlab":
        return gitlab_api.post_inline_gitlab(ctx, findings)
    return post_inline_comments(ctx, findings)
