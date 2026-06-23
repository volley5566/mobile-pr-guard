"""
main.py  ——  总编排(把第 1~4 周的模块串成一条流水线)
======================================================
完整闭环:
    采集 PR -> 规则扫描 -> AI review -> 回写 PR 评论 -> (可选)按高风险卡 CI

用法:
    # GitHub Actions 里(自动从环境变量读 PR):
    python src/main.py

    # 本地测试(扫一个目录,不连 GitHub):
    python src/main.py --local demo-android
"""

from __future__ import annotations
import json
import os
import sys

from config import load_config
import forge
from rules import run_rules, sort_by_severity
from semgrep_scan import run_semgrep
from external_scanners import run_external_scanners
from suppress import apply_suppressions
from ai_review import generate_review


def main() -> int:
    args = sys.argv[1:]
    local_dir = None
    if "--local" in args:
        idx = args.index("--local")
        local_dir = args[idx + 1] if idx + 1 < len(args) else "."

    # 仓库根:本地 / GitHub(GITHUB_WORKSPACE)/ GitLab(CI_PROJECT_DIR)
    repo_root = (local_dir or os.environ.get("GITHUB_WORKSPACE")
                 or os.environ.get("CI_PROJECT_DIR") or ".")
    cfg = load_config(repo_root)

    # 1) 采集(按平台分发:local / github / gitlab)
    fk = forge.detect(local_dir)
    ctx = forge.collect(fk, local_dir)
    print(f"[平台] {fk}")

    # 报告文件名带上 PR 号,方便历史追溯(对应路线图 pr-12-review.md)
    # 本地模式没有 PR 号,用 "local"
    prefix = f"pr-{ctx.pr_number}" if ctx.pr_number else "local"

    print(f"[1/4] 采集完成:{len(ctx.changed_files)} 个文件改动")
    _dump(repo_root, f"{prefix}-context.json", ctx.to_json())

    # 2) 规则扫描(手写规则 + Semgrep + 外部工具 detekt/Lint/SwiftLint)
    findings = run_rules(ctx, cfg)
    sg_findings = run_semgrep(ctx, cfg, repo_root)
    ext_findings = run_external_scanners(ctx, cfg, repo_root)
    findings = sort_by_severity(findings + sg_findings + ext_findings)
    # 误报抑制(行内 mpg-ignore + 配置 suppress)
    findings, n_suppressed = apply_suppressions(findings, ctx, cfg)
    print(f"[2/4] 规则扫描完成:{len(findings)} 条 finding"
          f"(Semgrep {len(sg_findings)} 条,外部工具 {len(ext_findings)} 条"
          f"{f',已抑制 {n_suppressed} 条' if n_suppressed else ''})")
    _dump(repo_root, f"{prefix}-findings.json", [f.dict() for f in findings])

    # 3) AI review
    review_md = generate_review(ctx, findings, cfg, repo_root=repo_root)
    print("[3/4] AI review 生成完成")
    _dump_text(repo_root, f"{prefix}-review.md", review_md)
    print("\n" + "=" * 60 + "\n" + review_md + "\n" + "=" * 60 + "\n")

    # 4) 回写评论(本地模式会自动跳过):底部汇总 + 行内评论
    if cfg.review.get("comment_on_pr", True):
        url = forge.post_summary(fk, ctx, review_md)
        print(f"[4/4] 汇总评论已处理:{url}")
        if cfg.review.get("inline_comments", True):
            n = forge.post_inline(fk, ctx, findings)
            print(f"      行内评论:已贴 {n} 条")
    else:
        print("[4/4] 配置关闭了 PR 评论,跳过。")

    # 是否按高风险卡 CI
    has_high = any(f.severity == "HIGH" for f in findings)
    if cfg.review.get("fail_on_high_risk", False) and has_high:
        print("发现高风险且配置要求卡 CI -> 退出码 1")
        return 1
    return 0


def _dump(root: str, name: str, obj) -> None:
    out_dir = os.path.join(root, "reports", "mobile-pr-guard")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _dump_text(root: str, name: str, text: str) -> None:
    out_dir = os.path.join(root, "reports", "mobile-pr-guard")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    raise SystemExit(main())
