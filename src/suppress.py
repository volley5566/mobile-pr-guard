"""
suppress.py  ——  误报抑制(让某条 finding 闭嘴)
================================================
review 工具被卸载的头号原因,就是「报错了却没法让它闭嘴」。这里提供两种方式:

1) 行内注释:在出问题那一行的【行末】或【上一行】写 `mpg-ignore`,静音那一行。
   例:  val token = intent.getStringExtra("t")!!   // mpg-ignore

2) 配置 suppress:按 规则前缀 + 路径(glob)整片静音,适合已知的遗留目录。
   suppress:
     - { rule: crash_patterns, path: "legacy/**" }

在所有扫描器跑完、findings 合并之后,统一过滤一遍。
"""

from __future__ import annotations
import fnmatch

IGNORE_MARK = "mpg-ignore"


def _ignored_lines(ctx) -> set:
    """收集被行内 mpg-ignore 标记的 (文件, 行号)。
    约定:标记写在问题行末尾(静音本行),或单独写在问题行上一行(静音下一行)。"""
    marked = set()
    for cf in ctx.changed_files:
        for lineno, text in cf.added_lines_with_lineno():
            if IGNORE_MARK in text:
                marked.add((cf.filename, lineno))        # 行末标记 -> 静音本行
                marked.add((cf.filename, lineno + 1))     # 单独成行 -> 静音下一行
    return marked


def _rule_matches(finding_rule: str, pat: str) -> bool:
    if not pat:
        return True
    # 前缀匹配:'semgrep' 命中 'semgrep:xxx';'crash_patterns' 命中自身
    return finding_rule == pat or finding_rule.startswith(pat)


def apply_suppressions(findings, ctx, cfg):
    """返回 (保留的 findings, 被抑制的条数)。"""
    entries = getattr(cfg, "suppress", None) or []
    ignored = _ignored_lines(ctx)

    kept, suppressed = [], 0
    for f in findings:
        # 1) 行内注释抑制
        if f.line and (f.file, f.line) in ignored:
            suppressed += 1
            continue
        # 2) 配置 suppress 抑制(规则前缀 + 路径 glob)
        hit = False
        for e in entries:
            if not isinstance(e, dict):
                continue
            path_pat = e.get("path") or ""
            if _rule_matches(f.rule, e.get("rule") or "") and \
               (not path_pat or fnmatch.fnmatch(f.file, path_pat)):
                hit = True
                break
        if hit:
            suppressed += 1
            continue
        kept.append(f)
    return kept, suppressed
