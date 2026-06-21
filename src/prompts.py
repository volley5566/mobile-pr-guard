"""
prompts.py  ——  对应路线图「第 3 周:AI Review」的 prompt 部分
=============================================================
prompt(提示词)就是你交给 AI 的「工作说明书」。
好的 review 工具,一半功夫在这份说明书上:你要把「移动端老司机的审查习惯」
写成明确规则,逼着 AI 只基于事实说话、不说废话。
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是一位资深 Android / 移动端 code review 工程师。
你的任务是审查一个 Pull Request,产出专业、可落地的 review。

铁律(必须遵守):
1. 只基于给你的 diff 和扫描结果说话,不要脑补不存在的代码。
2. 不确定的地方,明确写「需要人工确认」,不要假装确定。
3. 每条建议必须能落地(给出具体做法),禁止「建议优化代码质量」这类空话。
4. 不要因为低风险问题去阻塞 PR;只有高风险才需要重点强调并解释原因。
5. 输出严格使用下面的 Markdown 结构,不要加额外寒暄。

输出结构:
## Mobile PR Guard Review

### Summary
(2-3 句话说清这个 PR 干了什么)

### High Risk
(没有就写「无」。每条用 - [ ] 开头,说清风险 + 为什么 + 怎么办)

### Medium Risk
(同上)

### Test Suggestions
(针对这次改动,建议补哪些测试场景)

### Release Checklist
(这次发版需要人工确认的事项清单)
"""


def build_user_prompt(ctx, findings, team_docs_text: str) -> str:
    """把所有上下文拼成一条用户消息。
    顺序:标题 -> 改了哪些文件 -> 规则扫描结果 -> 团队规范 -> diff 节选。"""
    files_block = "\n".join(
        f"- {cf.filename} ({cf.status}, +{cf.additions}/-{cf.deletions})"
        for cf in ctx.changed_files
    ) or "(无)"

    if findings:
        rule_block = "\n".join(
            f"- [{fd.severity}] {fd.file}:{fd.line} | {fd.message} 建议:{fd.suggestion}"
            for fd in findings
        )
    else:
        rule_block = "(确定性规则未发现问题)"

    # diff 可能很大,做个粗暴截断,避免一次塞太多 token
    diff_parts = []
    budget = 12000  # 字符预算,够 MVP 用;真实项目可按 token 精算
    for cf in ctx.changed_files:
        if not cf.patch:
            continue
        chunk = f"\n### FILE: {cf.filename}\n{cf.patch}\n"
        if budget - len(chunk) < 0:
            diff_parts.append("\n(diff 过长,已截断……)")
            break
        diff_parts.append(chunk)
        budget -= len(chunk)
    diff_block = "".join(diff_parts) or "(无 diff)"

    team_block = team_docs_text.strip() or "(该仓库未提供团队规范文档)"

    return f"""# PR 标题
{ctx.title}

# 改动文件
{files_block}

# 确定性规则扫描结果(请重点核对这些事实)
{rule_block}

# 团队规范(如有,请遵守)
{team_block}

# 代码 diff
{diff_block}
"""
