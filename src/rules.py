"""
rules.py  ——  对应路线图「第 2 周:规则扫描」
==============================================
不调用 AI,纯靠确定性规则,就能发现一部分「一定有问题」的风险。

为什么先做规则、后做 AI?
- 规则:便宜、稳定、可解释。"新增了 CAMERA 权限" 这种事实不需要 AI 判断。
- AI:贵、灵活、能读懂上下文。留给「这段逻辑有没有隐患」这类模糊判断。
两者配合:规则负责抓铁证,AI 负责出判断。

每条风险用统一结构 Finding 表达:文件、行号、等级、解释、建议。
"""

from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Literal

from collect_pr import PRContext, ChangedFile

Severity = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass
class Finding:
    rule: str
    file: str
    line: int          # 0 表示「整文件/未定位到具体行」
    severity: Severity
    message: str       # 风险是什么
    suggestion: str    # 怎么处理

    def dict(self) -> dict:
        return asdict(self)


# ============ 规则 1:Manifest 敏感权限新增 ============
SENSITIVE_PERMISSIONS = {
    "CAMERA": "相机",
    "RECORD_AUDIO": "录音",
    "READ_MEDIA_IMAGES": "读取相册图片",
    "READ_MEDIA_VIDEO": "读取相册视频",
    "ACCESS_FINE_LOCATION": "精确定位",
    "ACCESS_BACKGROUND_LOCATION": "后台定位",
    "QUERY_ALL_PACKAGES": "查询全部已安装应用(应用市场高度敏感)",
    "POST_NOTIFICATIONS": "发送通知",
    "READ_CONTACTS": "读取通讯录",
    "READ_PHONE_STATE": "读取手机状态",
}


def rule_permissions(f: ChangedFile) -> list[Finding]:
    if not f.filename.endswith("AndroidManifest.xml"):
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        m = re.search(r'android\.permission\.([A-Z_]+)', line)
        if m and m.group(1) in SENSITIVE_PERMISSIONS:
            perm = m.group(1)
            out.append(Finding(
                rule="permissions", file=f.filename, line=i, severity="HIGH",
                message=f"新增敏感权限 {perm}({SENSITIVE_PERMISSIONS[perm]})",
                suggestion="确认隐私政策、运行时权限弹窗、应用市场权限声明三处是否同步更新。",
            ))
    return out


# ============ 规则 2:Gradle 依赖变化 ============
RISKY_SDK_KEYWORDS = {
    "admob": "广告", "applovin": "广告", "pangle": "广告", "unityads": "广告",
    "firebase-analytics": "统计", "appsflyer": "归因统计", "umeng": "统计",
    "jpush": "推送", "getui": "推送", "fcm": "推送",
    "amap": "定位", "baidu-location": "定位",
    "alipay": "支付", "wechat-pay": "支付", "stripe": "支付",
}


def rule_gradle(f: ChangedFile) -> list[Finding]:
    if not (f.filename.endswith(".gradle") or f.filename.endswith(".gradle.kts")
            or f.filename.endswith(".toml")):
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        low = line.lower()
        # 2a:动态版本号 + / latest,会导致构建不可复现
        if re.search(r'["\'][\w.\-]+:[\w.\-]+:[\w.\-]*\+', line) or "latest.release" in low:
            out.append(Finding(
                rule="gradle_dependencies", file=f.filename, line=i, severity="MEDIUM",
                message="依赖使用了动态版本号(+ / latest),构建结果不可复现。",
                suggestion="锁定到具体版本号,避免今天能编译、明天突然挂。",
            ))
        # 2b:新增了敏感类目的 SDK
        for kw, cat in RISKY_SDK_KEYWORDS.items():
            if kw in low:
                out.append(Finding(
                    rule="gradle_dependencies", file=f.filename, line=i, severity="MEDIUM",
                    message=f"新增 {cat}类 SDK(匹配关键字 '{kw}')。",
                    suggestion="确认合规(隐私/SDK 名单)、包体积影响、是否与现有 SDK 冲突。",
                ))
    return out


# ============ 规则 3:Kotlin/Java 崩溃/隐患模式 ============
# 每条规则:正则 + 等级 + 解释 + 建议
CRASH_PATTERNS = [
    (r'(?<![!=])!!(?![=])', "MEDIUM", "使用了 !! 强解包,可能触发 NPE 崩溃。", "改用 ?. / ?: / requireNotNull 并给出明确错误。"),
    (r'\bGlobalScope\b', "MEDIUM", "使用 GlobalScope,协程脱离生命周期,易泄漏。", "改用与生命周期绑定的 scope(viewModelScope / lifecycleScope)。"),
    (r'\brunBlocking\b', "MEDIUM", "主线程 runBlocking 可能卡 UI 甚至 ANR。", "改为挂起函数 + 合适的 dispatcher。"),
    (r'Thread\.sleep\s*\(', "MEDIUM", "Thread.sleep 阻塞线程,主线程上会卡顿/ANR。", "改用 delay() 或事件驱动。"),
    (r'\.observeForever\s*\(', "MEDIUM", "observeForever 容易忘记 removeObserver 造成泄漏。", "优先 observe(lifecycleOwner) 自动解绑。"),
    (r'getSerializableExtra\s*\(', "LOW", "getSerializableExtra 在 Android 13+ 有兼容写法变化。", "用带 Class 参数的新重载并做版本判断。"),
    (r'http://[^\s"\')]+', "HIGH", "出现明文 http:// 链接,存在中间人风险且可能被系统拦。", "改用 https://,或在网络安全配置中显式声明。"),
    (r'(?i)(api[_-]?key|secret|token|password)\s*=\s*["\'][A-Za-z0-9_\-]{12,}["\']',
     "HIGH", "疑似硬编码密钥/Token。", "移到服务端或安全存储,切勿写进代码库。"),
]
_CRASH_COMPILED = [(re.compile(p), sev, msg, sug) for p, sev, msg, sug in CRASH_PATTERNS]


def rule_crash_patterns(f: ChangedFile) -> list[Finding]:
    if f.ext not in (".kt", ".java"):
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        stripped = line.strip()
        # 跳过注释 / import / package / 注解行,减少误报
        # (例如 `import ...GlobalScope` 只是引入,并非真的在用)
        if stripped.startswith(("//", "*", "import ", "package ", "@")):
            continue
        for rgx, sev, msg, sug in _CRASH_COMPILED:
            if rgx.search(line):
                out.append(Finding(
                    rule="crash_patterns", file=f.filename, line=i, severity=sev,  # type: ignore
                    message=msg, suggestion=sug,
                ))
    return out


# ============ 规则 4:改了业务代码却没测试 ============
def rule_missing_tests(ctx: PRContext) -> list[Finding]:
    touched_main = any("src/main/" in cf.filename and cf.ext in (".kt", ".java")
                       for cf in ctx.changed_files)
    touched_test = any(("src/test/" in cf.filename or "src/androidTest/" in cf.filename)
                       for cf in ctx.changed_files)
    if touched_main and not touched_test:
        return [Finding(
            rule="missing_tests", file="(整个 PR)", line=0, severity="LOW",
            message="本次修改涉及 src/main 业务逻辑,但未看到任何测试改动。",
            suggestion="补充关键路径的单元/UI 测试(失败、弱网、边界场景)。",
        )]
    return []


# ============ 规则 5:发版高关注信号 ============
RELEASE_SIGNALS = [
    ("versionCode", "改了 versionCode"),
    ("versionName", "改了 versionName"),
    ("proguard-rules.pro", "改了 ProGuard 规则(可能影响混淆后崩溃)"),
    ("AndroidManifest.xml", "改了 Manifest"),
    ("deeplink", "涉及 deeplink"),
    ("scheme", "涉及 URL scheme"),
]


def rule_release_risk(ctx: PRContext) -> list[Finding]:
    out = []
    for cf in ctx.changed_files:
        hay = cf.filename + "\n" + "\n".join(cf.added_lines())
        for needle, why in RELEASE_SIGNALS:
            if needle.lower() in hay.lower():
                out.append(Finding(
                    rule="release_risk", file=cf.filename, line=0, severity="MEDIUM",
                    message=f"发版高关注信号:{why}。",
                    suggestion="走灰度发布;发版前过一遍 release checklist。",
                ))
                break  # 一个文件命中一次即可,避免刷屏
    return out


# ============ 公共:按等级排序(HIGH 在最前) ============
def sort_by_severity(findings: list[Finding]) -> list[Finding]:
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda x: order.get(x.severity, 9))
    return findings


# ============ 公共:识别工程涉及哪些移动平台(可能同时有多个!) ============
SUPPORTED_PLATFORMS = ("android", "ios")


def detect_platforms(ctx: PRContext) -> list[str]:
    """看改动里出现了哪些平台的特征文件。
    monorepo 可能【同时】有 Android 和 iOS,所以返回的是一个【列表】。
    一个都没识别出来(纯后端/纯前端 PR)就返回空 -> 交给 Semgrep/外部工具去管。"""
    has_ios = has_android = False
    for cf in ctx.changed_files:
        name = cf.filename
        if name.endswith(".swift") or name.endswith("Info.plist") \
                or name.endswith("Podfile") or "Package.swift" in name \
                or ".xcodeproj" in name or ".entitlements" in name:
            has_ios = True
        if name.endswith((".kt", ".java", ".gradle", ".kts")) \
                or name.endswith("AndroidManifest.xml") or name.endswith(".pro"):
            has_android = True
    out = []
    if has_android:
        out.append("android")
    if has_ios:
        out.append("ios")
    return out


def _resolve_platforms(cfg, ctx: PRContext) -> list[str]:
    """把配置里的 platform 归一化成一个平台列表。
    支持:auto / all / 单个字符串 android|ios / 列表 [android, ios]。"""
    raw = cfg.project.get("platform", "auto")
    if isinstance(raw, list):
        return [str(p).lower() for p in raw if str(p).lower() in SUPPORTED_PLATFORMS]
    val = str(raw).lower()
    if val == "auto":
        return detect_platforms(ctx)
    if val == "all":
        return list(SUPPORTED_PLATFORMS)
    return [val] if val in SUPPORTED_PLATFORMS else []


# ============ 总入口:按平台(可多个)分发到对应规则集 ============
def run_rules(ctx: PRContext, cfg) -> list[Finding]:
    platforms = _resolve_platforms(cfg, ctx)
    findings: list[Finding] = []
    if "android" in platforms:
        findings += _run_android_rules(ctx, cfg)
    if "ios" in platforms:
        from rules_ios import run_ios_rules   # 延迟导入,避免循环依赖
        findings += run_ios_rules(ctx, cfg)
    # 没有任何移动平台命中也没关系:Semgrep + 外部工具仍会在 main 里跑。
    return sort_by_severity(findings)


def _run_android_rules(ctx: PRContext, cfg) -> list[Finding]:
    findings: list[Finding] = []
    for cf in ctx.changed_files:
        if cfg.rule_enabled("permissions"):
            findings += rule_permissions(cf)
        if cfg.rule_enabled("gradle_dependencies"):
            findings += rule_gradle(cf)
        if cfg.rule_enabled("crash_patterns"):
            findings += rule_crash_patterns(cf)
    if cfg.rule_enabled("missing_tests"):
        findings += rule_missing_tests(ctx)
    if cfg.rule_enabled("release_risk"):
        findings += rule_release_risk(ctx)
    return sort_by_severity(findings)
