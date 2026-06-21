"""
ai_review.py  ——  对应路线图「第 3 周:接入 AI」
===================================================
把 prompt 发给大模型,拿回一段 Markdown review。

【多模型适配 / 适配器模式】
比喻:出国带的「万能电源转接头」。我们的 prompt(吹风机)一点不用改,
只要换个插头头子,就能插进不同厂商的接口:
  - anthropic : 官方 Claude,用 anthropic SDK。
  - deepseek  : DeepSeek,便宜量大。它【兼容 OpenAI 接口】,所以用 openai SDK
                改个 base_url 就能调。
  - openai    : OpenAI 官方(顺手支持,接口同上)。
客户只要在 mobile-pr-guard.yml 里写一行 `provider: deepseek` 就切换了。

其它要点:
- 失败要「优雅降级」:AI 挂了不能把整个 CI 带崩,
  此时退回到「只展示规则扫描结果」(_fallback_review)。
"""

from __future__ import annotations
import os

from prompts import SYSTEM_PROMPT, build_user_prompt


# 一张「插头规格表」:每家厂商需要哪把钥匙(环境变量)、连到哪个地址、
# 默认型号是什么、用哪种调用风格(anthropic 风格 or openai 风格)。
PROVIDERS = {
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "base_url": None,
        "default_model": "claude-sonnet-4-6",
        "style": "anthropic",
    },
    "deepseek": {
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",  # DeepSeek 兼容 OpenAI 接口
        "default_model": "deepseek-chat",
        "style": "openai",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "base_url": None,                        # None = 用 openai SDK 默认地址
        "default_model": "gpt-4o-mini",
        "style": "openai",
    },
}


def _read_team_docs(repo_root: str, doc_paths: list[str]) -> str:
    """读取存在的团队规范文档,拼成一段文本喂给 AI。"""
    chunks = []
    for rel in doc_paths:
        full = os.path.join(repo_root, rel)
        if os.path.exists(full):
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()[:4000]  # 每份文档限长,防止撑爆 prompt
                chunks.append(f"--- {rel} ---\n{txt}")
            except OSError:
                pass
    return "\n\n".join(chunks)


def generate_review(ctx, findings, cfg, repo_root: str = ".") -> str:
    """返回一段 Markdown review。无 API key 或调用失败时优雅降级。"""
    provider = (cfg.review.get("provider") or "anthropic").lower()
    team_docs_text = _read_team_docs(repo_root, cfg.team_docs)
    user_prompt = build_user_prompt(ctx, findings, team_docs_text)

    spec = PROVIDERS.get(provider)
    if spec is None:
        return _fallback_review(
            findings,
            reason=f"未知的 provider「{provider}」,可选 {list(PROVIDERS)}。仅展示规则扫描结果。",
        )

    api_key = os.environ.get(spec["env"])
    if not api_key:
        return _fallback_review(
            findings, reason=f"未配置 {spec['env']}(provider={provider}),仅展示规则扫描结果。"
        )

    # 留空就用该 provider 的默认型号
    model = cfg.review.get("model") or spec["default_model"]

    try:
        if spec["style"] == "anthropic":
            text = _call_anthropic(api_key, model, user_prompt)
        else:  # openai 风格(openai 官方 + deepseek 都走这里)
            text = _call_openai_compatible(api_key, spec["base_url"], model, user_prompt)
        return text.strip() or _fallback_review(findings, reason="AI 返回为空。")
    except Exception as e:  # 网络/额度/SDK 任何错误都不该拖垮 CI
        return _fallback_review(findings, reason=f"AI 调用失败({provider}/{model}):{e}")


def _call_anthropic(api_key: str, model: str, user_prompt: str) -> str:
    """Claude 插头:用 anthropic SDK。system 是独立参数,返回是 block 列表。"""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    )


def _call_openai_compatible(api_key: str, base_url, model: str, user_prompt: str) -> str:
    """DeepSeek / OpenAI 插头:用 openai SDK。
    区别只在 base_url:DeepSeek 指向自家地址,OpenAI 传 None 用官方默认。
    它的 system 是放进 messages 列表里的一条 role=system 消息。"""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)  # base_url=None -> 官方 OpenAI
    resp = client.chat.completions.create(
        model=model,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.choices[0].message.content or ""


def _fallback_review(findings, reason: str) -> str:
    """AI 不可用时的兜底:把规则结果整理成同样的 Markdown 结构。"""
    def by(sev):
        return [f for f in findings if f.severity == sev]

    def block(items):
        if not items:
            return "无"
        return "\n".join(f"- [ ] {f.file}:{f.line} — {f.message} 建议:{f.suggestion}"
                         for f in items)

    return f"""## Mobile PR Guard Review

> 注意:{reason}

### Summary
本次未能调用 AI,以下为确定性规则扫描结果。

### High Risk
{block(by("HIGH"))}

### Medium Risk
{block(by("MEDIUM"))}

### Test Suggestions
{block(by("LOW")) if by("LOW") else "无"}

### Release Checklist
- 人工复核上述高风险项
"""
