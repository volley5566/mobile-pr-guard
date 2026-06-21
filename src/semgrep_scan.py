"""
semgrep_scan.py  ——  接入真正的静态分析工具 Semgrep(对应路线图二阶段③)
========================================================================
我们手写的正则规则(rules.py)是「迷你版扫描器」:便宜、可控,但靠字符串匹配,
容易被各种写法绕过、也容易误报。Semgrep 是工业级工具,按【代码结构(语法树)】
匹配,跨语言(Kotlin / Java / Swift 都行),规则用 YAML 写,可读可维护。

设计:
- 只扫这次 PR 改动到、且磁盘上确实存在的文件(CI 里 checkout 后就有)。
- 默认用仓库自带的 semgrep-rules/mobile.yml;可在配置里再追加规则源。
- 优雅降级:semgrep 没装 / 跑挂了,都只是跳过,绝不拖垮整个流程。
- 输出统一成 rules.py 的 Finding,后面 AI / 评论环节无需改动。
"""

from __future__ import annotations
import json
import os
import shutil
import subprocess

from rules import Finding

# Semgrep 的严重度 -> 我们的三档
_SEV_MAP = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}


def _bundled_rules_path() -> str:
    """内置规则【目录】:本文件在 src/,规则在 ../semgrep-rules/。
    指向目录而非单文件,这样以后往目录里加规则文件(如 polyglot.yml)会自动生效。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "semgrep-rules"))


def run_semgrep(ctx, cfg, repo_root: str = ".") -> list[Finding]:
    if not cfg.rule_enabled("semgrep"):
        return []

    if shutil.which("semgrep") is None:
        print("[semgrep] 未安装 semgrep,跳过(pip install semgrep 后即可启用)。")
        return []

    # 只扫本次改动、且磁盘上存在的文件
    paths = []
    for cf in ctx.changed_files:
        full = os.path.join(repo_root, cf.filename)
        if os.path.exists(full):
            paths.append(full)
    if not paths:
        return []

    configs = ["--config", _bundled_rules_path()]
    extra = (cfg.semgrep.get("extra_config") or "").strip()
    if extra:  # 例如 "auto" 或 "p/kotlin",会额外拉官方规则集
        configs += ["--config", extra]

    cmd = ["semgrep", "scan", "--json", "--quiet", "--no-git-ignore", *configs, *paths]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        data = json.loads(proc.stdout or "{}")
    except Exception as e:  # 超时 / 解析失败 / 任何异常都跳过,不影响主流程
        print(f"[semgrep] 运行失败,跳过:{e}")
        return []

    out: list[Finding] = []
    for r in data.get("results", []):
        extra_info = r.get("extra", {}) or {}
        meta = extra_info.get("metadata", {}) or {}
        sev = _SEV_MAP.get(extra_info.get("severity", "WARNING"), "MEDIUM")
        check = (r.get("check_id") or "semgrep").split(".")[-1]
        try:
            rel = os.path.relpath(r.get("path", ""), repo_root)
        except ValueError:
            rel = r.get("path", "")
        out.append(Finding(
            rule=f"semgrep:{check}",
            file=rel,
            line=r.get("start", {}).get("line", 0),
            severity=sev,  # type: ignore
            message=(extra_info.get("message") or "").strip(),
            suggestion=meta.get("fix") or "参考该 Semgrep 规则的说明处理。",
        ))
    return out
