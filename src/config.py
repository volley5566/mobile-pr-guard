"""
config.py
=========
读取仓库根目录下的 mobile-pr-guard.yml 配置文件。
如果文件不存在,就用一套合理的默认值,保证「零配置也能跑」。

设计原则:配置永远有默认值。客户什么都不写,工具也能工作;
客户想关掉某条规则,只要在 yml 里写一行就行。
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover
    yaml = None


# ---- 默认配置:这就是「客户什么都不填」时的行为 ----
DEFAULTS = {
    "project": {
        # auto = 看文件自动判断 Android 还是 iOS;也可写死 android / ios
        "platform": "auto",
        "min_sdk": 21,
        "target_sdk": 35,
    },
    "review": {
        "fail_on_high_risk": False,   # 默认不卡 CI,只评论,降低接入心理门槛
        "comment_on_pr": True,
        "inline_comments": True,      # 把带行号的风险贴成「行内评论」(代码行下面)
        # 用哪家大模型:anthropic(Claude) / deepseek / openai
        "provider": "anthropic",
        # 具体型号;留空 "" = 用该 provider 的默认型号(见 ai_review.PROVIDERS)
        "model": "",
    },
    "rules": {
        "permissions": True,
        "gradle_dependencies": True,
        "crash_patterns": True,
        "missing_tests": True,
        "release_risk": True,
        "semgrep": True,              # 用 Semgrep 做工业级静态分析(需装 semgrep)
    },
    "semgrep": {
        # 额外规则源:留空 = 只用内置 semgrep-rules/mobile.yml;
        # 可填 "auto"(官方社区规则,需联网)或 "p/kotlin" 等规则包名。
        "extra_config": "",
    },
    # 外部静态分析工具(detekt / Android Lint / SwiftLint ...)。
    # 默认空 = 不跑任何外部工具;每个项目按自己的命令/报告路径自行配置。
    # 每项字段:
    #   name    : 显示名
    #   run     : 在仓库根执行的命令(留空 = 不执行,只读已有报告)
    #   report  : 跑完去哪读报告(支持 ** 通配)
    #   format  : sarif / checkstyle / auto(按扩展名猜)
    #   enabled : 是否启用
    "external_scanners": [],
    # AI 需要读的团队规范文档(存在才读,不存在自动跳过)
    "team_docs": [
        "MOBILE_REVIEW.md",
        "CLAUDE.md",
        "docs/release-checklist.md",
    ],
}


@dataclass
class Config:
    project: dict = field(default_factory=lambda: dict(DEFAULTS["project"]))
    review: dict = field(default_factory=lambda: dict(DEFAULTS["review"]))
    rules: dict = field(default_factory=lambda: dict(DEFAULTS["rules"]))
    semgrep: dict = field(default_factory=lambda: dict(DEFAULTS["semgrep"]))
    external_scanners: list = field(default_factory=list)
    team_docs: list = field(default_factory=lambda: list(DEFAULTS["team_docs"]))

    def rule_enabled(self, name: str) -> bool:
        return bool(self.rules.get(name, False))


def _deep_merge(base: dict, override: dict) -> dict:
    """把用户配置叠加到默认配置上(只覆盖用户写了的字段)。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(repo_root: str = ".") -> Config:
    path = os.path.join(repo_root, "mobile-pr-guard.yml")
    user_cfg = {}
    if os.path.exists(path) and yaml is not None:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}

    merged = _deep_merge(DEFAULTS, user_cfg)
    return Config(
        project=merged["project"],
        review=merged["review"],
        rules=merged["rules"],
        semgrep=merged.get("semgrep", DEFAULTS["semgrep"]),
        external_scanners=merged.get("external_scanners", []),
        team_docs=merged.get("team_docs", DEFAULTS["team_docs"]),
    )
