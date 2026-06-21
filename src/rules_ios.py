"""
rules_ios.py  ——  iOS 版规则集(与 rules.py 的 Android 版一一对应)
====================================================================
引擎(采集 / AI / 评论)和 Android 完全共用;只有「什么算风险」这张清单不同。
对照表:
    AndroidManifest.xml 权限   ->  Info.plist 的 NS...UsageDescription(隐私用途说明)
    build.gradle 依赖          ->  Podfile / Package.swift(CocoaPods / SPM)
    !! 强解包                   ->  try! / as! / 隐式解包 / DispatchQueue.main.sync
    明文 http                  ->  http:// + ATS 的 NSAllowsArbitraryLoads
    versionCode 等发版信号      ->  CFBundleVersion / .entitlements / 关联域名

每条风险仍用 rules.py 里的 Finding 结构表达,这样 AI / 评论环节无需改动。
"""

from __future__ import annotations
import re

from collect_pr import PRContext, ChangedFile
from rules import Finding, sort_by_severity


# ============ 规则 1:Info.plist 新增隐私用途说明(= 用了敏感能力) ============
# iOS 用某项隐私能力,必须在 Info.plist 写一句「用途说明」,否则上架被拒/运行崩溃。
# 因此「新增了某个 NSxxxUsageDescription」≈「这次开始用某项敏感能力」。
SENSITIVE_USAGE_KEYS = {
    "NSCameraUsageDescription": "相机",
    "NSMicrophoneUsageDescription": "麦克风",
    "NSPhotoLibraryUsageDescription": "相册(读取)",
    "NSPhotoLibraryAddUsageDescription": "相册(写入)",
    "NSLocationWhenInUseUsageDescription": "使用期间定位",
    "NSLocationAlwaysAndWhenInUseUsageDescription": "始终定位(含后台)",
    "NSContactsUsageDescription": "通讯录",
    "NSUserTrackingUsageDescription": "广告追踪(ATT,App 上架高度敏感)",
    "NSBluetoothAlwaysUsageDescription": "蓝牙",
    "NSFaceIDUsageDescription": "Face ID",
}


def rule_ios_permissions(f: ChangedFile) -> list[Finding]:
    if not f.filename.endswith("Info.plist"):
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        for key, cn in SENSITIVE_USAGE_KEYS.items():
            if key in line:
                out.append(Finding(
                    rule="permissions", file=f.filename, line=i, severity="HIGH",
                    message=f"新增隐私用途说明 {key}({cn}),意味着开始使用该敏感能力。",
                    suggestion="确认隐私政策、App 隐私营养标签(App Privacy)、运行时授权弹窗三处同步更新。",
                ))
    # ATS 开后门:整体允许明文网络,安全风险高
    for i, line in f.added_lines_with_lineno():
        if "NSAllowsArbitraryLoads" in line:
            out.append(Finding(
                rule="permissions", file=f.filename, line=i, severity="HIGH",
                message="Info.plist 出现 NSAllowsArbitraryLoads(关闭 ATS,放行所有明文 http)。",
                suggestion="不要全局关闭 ATS;只对必要域名用 NSExceptionDomains 精确放行。",
            ))
    return out


# ============ 规则 2:Podfile / Package.swift 依赖变化 ============
RISKY_SDK_KEYWORDS = {
    "applovin": "广告", "google-mobile-ads": "广告", "admob": "广告", "pangle": "广告",
    "firebaseanalytics": "统计", "firebase/analytics": "统计", "appsflyer": "归因统计",
    "jpush": "推送", "getui": "推送", "firebasemessaging": "推送",
    "amap": "定位", "bmklocation": "定位",
    "stripe": "支付", "alipay": "支付", "wechat": "支付",
}


def rule_ios_dependencies(f: ChangedFile) -> list[Finding]:
    name = f.filename
    if not (name.endswith("Podfile") or name.endswith("Package.swift")
            or name.endswith("Podfile.lock")):
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        low = line.lower().replace(" ", "")
        for kw, cat in RISKY_SDK_KEYWORDS.items():
            if kw in low:
                out.append(Finding(
                    rule="gradle_dependencies", file=name, line=i, severity="MEDIUM",
                    message=f"新增 {cat}类 SDK(匹配关键字 '{kw}')。",
                    suggestion="确认合规(隐私清单 PrivacyInfo / SDK 名单)、包体积影响、是否与现有 SDK 冲突。",
                ))
        # CocoaPods 没锁版本(只写 pod 'X',没跟版本号)-> 构建不可复现
        if re.match(r"\s*pod\s+['\"][^'\"]+['\"]\s*$", line):
            out.append(Finding(
                rule="gradle_dependencies", file=name, line=i, severity="LOW",
                message="pod 未指定版本号,构建结果不可复现。",
                suggestion="用 ~> 锁定一个明确版本范围,例如 pod 'X', '~> 5.2'。",
            ))
    return out


# ============ 规则 3:Swift 崩溃 / 隐患模式 ============
CRASH_PATTERNS = [
    (r'\btry!\s', "MEDIUM", "使用 try! 强制 try,出错会直接崩溃。", "改用 do/catch 或 try?,妥善处理错误。"),
    (r'\bas!\s', "MEDIUM", "使用 as! 强制类型转换,转换失败会崩溃。", "改用 as? + 安全解包(if let / guard let)。"),
    (r'\.unsafelyUnwrapped\b', "MEDIUM", "使用 unsafelyUnwrapped,绕过安全检查易崩溃。", "改用安全解包 if let / guard let。"),
    (r'\bfatalError\s*\(', "MEDIUM", "fatalError 会主动让进程崩溃。", "确认仅用于真正不可达分支;否则改为可恢复的错误处理。"),
    (r'DispatchQueue\.main\.sync\b', "HIGH", "在主线程上 DispatchQueue.main.sync 会死锁。", "改用 async,或确保不在主线程调用。"),
    (r':\s*[A-Z]\w*!\s*(=|$)', "LOW", "隐式解包可选(Type!),为 nil 时访问即崩溃。", "尽量改为普通可选 Type? 并安全解包。"),
    (r'http://[^\s"\')]+', "HIGH", "出现明文 http:// 链接,iOS 默认 ATS 会拦截且有中间人风险。", "改用 https://,或对该域名做精确 ATS 例外。"),
    (r'(?i)(api[_-]?key|secret|token|password)\s*=\s*"[A-Za-z0-9_\-]{12,}"',
     "HIGH", "疑似硬编码密钥/Token。", "移到服务端或 Keychain,切勿写进代码库。"),
]
_CRASH_COMPILED = [(re.compile(p), sev, msg, sug) for p, sev, msg, sug in CRASH_PATTERNS]


def rule_ios_crash_patterns(f: ChangedFile) -> list[Finding]:
    if f.ext != ".swift":
        return []
    out = []
    for i, line in f.added_lines_with_lineno():
        stripped = line.strip()
        if stripped.startswith(("//", "*", "import ", "@")):
            continue  # 跳过注释 / import / 注解,减少误报
        for rgx, sev, msg, sug in _CRASH_COMPILED:
            if rgx.search(line):
                out.append(Finding(
                    rule="crash_patterns", file=f.filename, line=i, severity=sev,  # type: ignore
                    message=msg, suggestion=sug,
                ))
    return out


# ============ 规则 4:改了业务代码却没测试 ============
def rule_ios_missing_tests(ctx: PRContext) -> list[Finding]:
    def is_test(name: str) -> bool:
        return ("Tests/" in name or name.endswith("Tests.swift")
                or name.endswith("UITests.swift"))

    touched_src = any(cf.ext == ".swift" and not is_test(cf.filename)
                      for cf in ctx.changed_files)
    touched_test = any(is_test(cf.filename) for cf in ctx.changed_files)
    if touched_src and not touched_test:
        return [Finding(
            rule="missing_tests", file="(整个 PR)", line=0, severity="LOW",
            message="本次修改涉及 Swift 业务代码,但未看到任何测试改动。",
            suggestion="补充关键路径的 XCTest 单元/UI 测试(失败、弱网、边界场景)。",
        )]
    return []


# ============ 规则 5:发版高关注信号 ============
RELEASE_SIGNALS = [
    ("CFBundleShortVersionString", "改了对外版本号 CFBundleShortVersionString"),
    ("CFBundleVersion", "改了构建号 CFBundleVersion"),
    (".entitlements", "改了 entitlements(能力/签名相关)"),
    ("aps-environment", "涉及推送环境(APNs)"),
    ("associated-domains", "涉及关联域名(Universal Links / deeplink)"),
    ("CFBundleURLSchemes", "涉及 URL Scheme(deeplink)"),
]


def rule_ios_release_risk(ctx: PRContext) -> list[Finding]:
    out = []
    for cf in ctx.changed_files:
        hay = cf.filename + "\n" + "\n".join(cf.added_lines())
        for needle, why in RELEASE_SIGNALS:
            if needle.lower() in hay.lower():
                out.append(Finding(
                    rule="release_risk", file=cf.filename, line=0, severity="MEDIUM",
                    message=f"发版高关注信号:{why}。",
                    suggestion="走 TestFlight 灰度;发版前过一遍 release checklist。",
                ))
                break  # 一个文件命中一次即可
    return out


# ============ iOS 总入口(与 Android 的 _run_android_rules 对称) ============
def run_ios_rules(ctx: PRContext, cfg) -> list[Finding]:
    findings: list[Finding] = []
    for cf in ctx.changed_files:
        if cfg.rule_enabled("permissions"):
            findings += rule_ios_permissions(cf)
        if cfg.rule_enabled("gradle_dependencies"):   # 复用同一个开关:依赖检查
            findings += rule_ios_dependencies(cf)
        if cfg.rule_enabled("crash_patterns"):
            findings += rule_ios_crash_patterns(cf)
    if cfg.rule_enabled("missing_tests"):
        findings += rule_ios_missing_tests(ctx)
    if cfg.rule_enabled("release_risk"):
        findings += rule_ios_release_risk(ctx)
    return sort_by_severity(findings)
