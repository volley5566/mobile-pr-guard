"""
external_scanners.py  ——  可配置地接入 detekt / Android Lint / SwiftLint 等外部工具
====================================================================================
为什么不写死 `./gradlew detekt`?
  不同项目命令不同(./gradlew detekt、./gradlew app:lintDebug、swiftlint ...)、
  报告路径不同、格式不同,甚至有的团队已经在自己 CI 里跑过了。
所以这里只做两件事:
  1) 编排:按你在 mobile-pr-guard.yml 里写的命令去跑(也可以留空,只读已有报告)。
  2) 摄取:读它吐出的报告,转成统一的 Finding。

【关键设计:SARIF】
  detekt / Android Lint / SwiftLint 输出格式各不相同,但它们【都能输出 SARIF】——
  一种「静态分析结果的普通话」(微软牵头的行业标准)。
  我们只要会读 SARIF,一个解析器就通吃三家。另外也支持老牌的 checkstyle XML。

每个扫描器配置(见 config.DEFAULTS 注释):
  name / run / report / format(sarif|checkstyle|auto) / enabled
全程优雅降级:命令跑挂、报告找不到、格式不认识,都只是跳过,不拖垮主流程。
"""

from __future__ import annotations
import glob
import os
import subprocess
import xml.etree.ElementTree as ET
import json

from rules import Finding

# SARIF 的 level / checkstyle 的 severity -> 我们的三档
_SARIF_SEV = {"error": "HIGH", "warning": "MEDIUM", "note": "LOW", "none": "LOW"}
_CHECKSTYLE_SEV = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW", "ignore": "LOW"}


def run_external_scanners(ctx, cfg, repo_root: str = ".") -> list[Finding]:
    scanners = getattr(cfg, "external_scanners", None) or []
    out: list[Finding] = []
    for sc in scanners:
        if not isinstance(sc, dict) or not sc.get("enabled", True):
            continue
        name = sc.get("name", "scanner")
        run_cmd = (sc.get("run") or "").strip()

        # 1) 编排:有 run 就执行(best-effort)。
        # 注意:linter 发现问题时本就会返回非 0,这【不算失败】,照常去读报告。
        if run_cmd:
            try:
                subprocess.run(run_cmd, shell=True, cwd=repo_root,
                               capture_output=True, text=True, timeout=600)
            except Exception as e:
                print(f"[{name}] 命令执行异常,仍尝试读已有报告:{e}")

        # 2) 摄取:按 report 通配找报告文件并解析
        report_glob = (sc.get("report") or "").strip()
        if not report_glob:
            print(f"[{name}] 未配置 report 路径,跳过。")
            continue
        pattern = report_glob if os.path.isabs(report_glob) \
            else os.path.join(repo_root, report_glob)
        files = glob.glob(pattern, recursive=True)
        if not files:
            print(f"[{name}] 没找到报告文件({report_glob}),跳过。")
            continue

        fmt = (sc.get("format") or "auto").lower()
        for fp in files:
            out += _parse_report(fp, fmt, name, repo_root)
    return out


def _parse_report(path: str, fmt: str, name: str, repo_root: str) -> list[Finding]:
    if fmt == "auto":
        low = path.lower()
        fmt = "checkstyle" if low.endswith(".xml") else "sarif"
    try:
        if fmt == "sarif":
            return _parse_sarif(path, name, repo_root)
        if fmt == "checkstyle":
            return _parse_checkstyle(path, name, repo_root)
        print(f"[{name}] 不认识的格式 '{fmt}',跳过 {path}。")
        return []
    except Exception as e:
        print(f"[{name}] 解析报告失败,跳过({path}):{e}")
        return []


def _rel(path: str, repo_root: str) -> str:
    """报告里的路径常常已经是「相对项目根」的,这种直接用。
    只有当它是绝对路径时,才换算成相对 repo_root。"""
    if not path:
        return path
    if path.startswith("file://"):          # SARIF 有时给 file:// URI
        path = path[len("file://"):]
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, repo_root)
        except ValueError:
            return path
    return path


def _parse_sarif(path: str, name: str, repo_root: str) -> list[Finding]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)
    out: list[Finding] = []
    for run in data.get("runs", []):
        for res in run.get("results", []):
            level = (res.get("level") or "warning").lower()
            sev = _SARIF_SEV.get(level, "MEDIUM")
            msg = (res.get("message", {}) or {}).get("text", "").strip()
            rule_id = res.get("ruleId", name)
            file_uri, line = "", 0
            locs = res.get("locations") or []
            if locs:
                phys = (locs[0].get("physicalLocation") or {})
                file_uri = (phys.get("artifactLocation") or {}).get("uri", "")
                line = (phys.get("region") or {}).get("startLine", 0)
            out.append(Finding(
                rule=f"{name}:{rule_id}", file=_rel(file_uri, repo_root) if file_uri else "(项目)",
                line=line, severity=sev, message=msg or f"{name} 报告了一个问题。",
                suggestion=f"按 {name} 规则 {rule_id} 的说明处理。",
            ))
    return out


def _parse_checkstyle(path: str, name: str, repo_root: str) -> list[Finding]:
    """detekt / Android Lint 默认常输出 checkstyle 风格 XML:
       <checkstyle><file name="..."><error line=".." severity=".." message=".." source=".."/>"""
    tree = ET.parse(path)
    root = tree.getroot()
    out: list[Finding] = []
    for file_el in root.iter("file"):
        fname = file_el.get("name", "")
        for err in file_el.findall("error"):
            sev_raw = (err.get("severity") or "warning").lower()
            sev = _CHECKSTYLE_SEV.get(sev_raw, "MEDIUM")
            src = err.get("source") or name
            out.append(Finding(
                rule=f"{name}:{src}", file=_rel(fname, repo_root) if fname else "(项目)",
                line=int(err.get("line") or 0), severity=sev,
                message=(err.get("message") or "").strip() or f"{name} 报告了一个问题。",
                suggestion=f"按 {name} 规则 {src} 的说明处理。",
            ))
    return out
