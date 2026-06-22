# 🛡️ Mobile PR Guard

给 **Android / iOS** 团队用的 **AI PR Review** 工具。
开发者提交 PR → 自动分析改动 → 规则扫描 + AI 判断 → 自动在 PR 里评论风险、建议、发版注意事项。

> 第一版形态:**GitHub Action + 移动端规则库 + 大模型 + PR 自动评论**。
> 不需要服务器、不需要网站。

- **多平台 / 多语言**:Android 与 iOS 各一套规则,`platform: auto` 能在 monorepo 里**同时识别多个**;
  后端/前端(Python/Node/TS…)由 Semgrep + 可配置外部工具覆盖——polyglot 项目也能用。
- **多模型**:可选 Claude / DeepSeek / OpenAI,配置里一行 `provider:` 切换(DeepSeek 便宜量大,适合成本敏感团队)。

---

## 它能发现什么

| 规则 | 等级 | 例子 |
|------|------|------|
| Manifest 敏感权限新增 | HIGH | 新增 `READ_MEDIA_IMAGES` / `ACCESS_FINE_LOCATION` |
| 硬编码密钥 / 明文 http | HIGH | 代码里写死 API key/token、出现 `http://` |
| Gradle 依赖风险 | MEDIUM | 动态版本号 `+`、新增广告/统计/支付 SDK |
| Kotlin/Java 崩溃模式 | MEDIUM | `!!`、`GlobalScope`、`runBlocking`、`observeForever` |
| 改业务却没测试 | LOW | 改了 `src/main/` 但没动 `src/test/` |
| 发版高关注信号 | MEDIUM | 改了 `versionCode` / ProGuard / deeplink |

iOS 有一套对称的规则:`Info.plist` 隐私用途说明 / 关闭 ATS(HIGH)、`try!` / `as!` /
`DispatchQueue.main.sync` 死锁、Podfile 敏感 SDK、缺 XCTest、`CFBundleVersion` 发版信号等。

**外加 Semgrep 工业级静态分析**(按代码结构匹配,比正则强):命令执行、WebView JS 注入、
世界可读存储、不安全随机数等。规则见 [`semgrep-rules/mobile.yml`](semgrep-rules/mobile.yml),
本机没装 semgrep 会自动跳过,不影响其它检查。

确定性规则 + Semgrep 负责抓铁证,AI 负责结合上下文给可落地建议;结果合并成一条 PR 评论。

---

## 5 分钟本地试跑(不连 GitHub)

```bash
cd mobile-pr-guard
pip install -r requirements.txt

# 不带 API key:只跑规则扫描(走兜底)
python src/main.py --local demo-android    # Android 演示工程
python src/main.py --local demo-ios        # iOS 演示工程(自动识别平台)

# 带 API key:跑完整 AI review(任选一家)
export ANTHROPIC_API_KEY=sk-ant-xxxx       # provider=anthropic(默认)
# export DEEPSEEK_API_KEY=sk-xxxx          # provider=deepseek
python src/main.py --local demo-android
```

结果会打印在终端,并落盘到 `<工程>/reports/mobile-pr-guard/`(文件名带 PR 号便于追溯,
本地模式用 `local-`):
- `pr-12-context.json` —— 采集到的 PR 上下文
- `pr-12-findings.json` —— 规则 + Semgrep 扫描结果
- `pr-12-review.md` —— 最终 review

---

## 接入到真实仓库(GitHub Actions)

### 1. 配 Secret(保险柜)
在目标仓库 **Settings → Secrets and variables → Actions** 里添加(按你选的 provider 三选一):
- `ANTHROPIC_API_KEY` —— provider=anthropic 时
- `DEEPSEEK_API_KEY` —— provider=deepseek 时
- `OPENAI_API_KEY` —— provider=openai 时

(`GITHUB_TOKEN` 由 GitHub 自动提供,无需手动加。)

### 2. 加 workflow
把 `.github/workflows/example-usage.yml` 复制到目标仓库,
里面引用 `uses: volley5566/mobile-pr-guard@v1`。

### 3. 开个 PR 试试
开/更新 PR 后,几十秒内 PR 底部会出现一条 🛡️ Mobile PR Guard 评论,
重复触发只会**更新同一条**评论,不会刷屏。

---

## 自定义规则

在目标仓库根目录放一个 `mobile-pr-guard.yml`(参考 `mobile-pr-guard.yml.example`):

```yaml
project:
  platform: auto             # auto = 自动识别;也可写死 android / ios
review:
  fail_on_high_risk: false   # true = 有高风险就让 CI 失败
  provider: anthropic        # anthropic / deepseek / openai
  model: ""                  # 留空 = 用该 provider 的默认型号
rules:
  permissions: true
  crash_patterns: true
  semgrep: true              # Semgrep 静态分析(需装 semgrep)
semgrep:
  extra_config: ""           # 留空只用内置规则;可填 auto / p/kotlin 追加官方规则
```

什么都不写也能跑,全部有默认值。

### 接入 detekt / Android Lint / SwiftLint(可配置)

这些工具每个项目命令/报告路径都不同,所以**不写死**——你自己声明命令和报告位置,
推荐让工具输出 **SARIF**(一种解析器通吃三家;Lint 默认 XML 用 `format: checkstyle`):

```yaml
external_scanners:
  - name: detekt
    enabled: true
    run: "./gradlew detekt"                          # 你项目的命令
    report: "**/build/reports/detekt/detekt.sarif"   # 报告位置(支持 ** 通配)
    format: sarif
  - name: swiftlint
    enabled: true
    run: "swiftlint lint --reporter sarif > swiftlint.sarif"
    report: "swiftlint.sarif"
    format: sarif
```

- `run` 留空 = 不执行,只读你 CI 里**别的步骤已经生成**的报告。
- linter 发现问题会返回非 0,这不算失败,工具照样会读取报告。
- 工具没装 / 报告找不到 / 格式不认识 → 自动跳过,不影响其它检查。

---

## 提交前本地拦截(pre-commit hook,可选)

除了 PR 时在 CI 里跑,还能在你 `git commit` 的那一刻、在本地先拦一道——
发现 HIGH 风险就**中止这次提交**(用的是和 CI 同一套规则 + Semgrep)。

安装(每个开发者 clone 后跑一次):

```bash
bash scripts/install-hooks.sh        # 本质:git config core.hooksPath hooks
```

之后:
- `git commit` 时自动扫描**已暂存**的改动;有 HIGH 风险则拦下并列出问题。
- 临时跳过一次:`git commit --no-verify`
- 卸载:`git config --unset core.hooksPath`
- 没装 python 时自动放行,不打断你的工作流。

> CI(PR 时)是**团队级强制门禁**;pre-commit 是**个人级提前预警**。两者用同一套逻辑,
> 本地拦到的和 PR 上报的一致。

---

## 强制门禁:让高风险 PR 合不了

默认本工具只**评论**、不卡 merge(降低接入门槛)。想升级成「高风险就合不了」,需要**两层配合**:

| 层 | 谁来做 |
|----|--------|
| 有 HIGH 风险时让检查失败 | 工具:`mobile-pr-guard.yml` 设 `review.fail_on_high_risk: true` |
| 检查失败 / 缺 review 就锁 merge | GitHub:仓库 **分支保护(Branch Protection)** |

在 GitHub 用 **Rulesets** 设置(新版已用它取代旧的 "Branch protection rules";
路径:Settings → Rules → **Rulesets** → New ruleset → **New branch ruleset**):

1. **Ruleset Name**:随便起,如 `main-protection`
2. **Enforcement status**:改成 **Active**(最容易漏!不改成 Active 整条规则不生效)
3. **Target branches**:Add target → **Include default branch**(即 main)
4. ☑ **Require status checks to pass** → 点 **Add checks** → 输入并选中 **`mobile-pr-guard`**
   (该检查跑过一次后才会出现在补全里)
5. (可选)☑ **Require a pull request before merging**
   - ⚠️ 个人仓库把 **Required approvals 设为 0**:GitHub 不允许你 approve 自己的 PR,
     设 1 会因为"没人能批"把自己锁死;等真团队协作时再设 1
6. **Bypass list**:留空 = 连你自己也强制;把 `Repository admin` 加进去 = 给自己留后门
7. 点 **Create**

设完后:高风险 PR 的检查变红 ❌、Merge 按钮被锁 🔒。
> 工具只是「贴罚单的协警」,**放不放行由交警(分支保护)说了算**;
> `fail_on_high_risk` 负责把罚单升级成「红灯」,分支保护规定「红灯不准过」。

---

## 评论的身份(为什么署名是 github-actions[bot]?)

评论默认由内置的 `GITHUB_TOKEN` 发出,所以作者显示成 **`github-actions[bot]`**——
这是 GitHub 借给 Action 的「临时工牌」上印的名字。想显示成公司自己的名字(如 "XXX Reviewer"):

- **GitHub App(推荐)**:App 的名字 + 头像就是机器人的署名 —— 路线图第 4 阶段。
- **临时方案**:建一个专用机器人账号 + PAT,用它发评论。

注意评论**内容**其实已经品牌化(标题就是 `🛡️ Mobile PR Guard Review`),只是「发帖人」是 bot;
`github-actions[bot]` 本身不能改名。

---

## 团队规范注入

工具会自动读取目标仓库里存在的这些文件,作为 AI 的判断依据:
`MOBILE_REVIEW.md`、`CLAUDE.md`、`docs/release-checklist.md`。
把你团队的规范写进去,AI 评语就会贴合你们的标准。

---

## 数据与费用

- **数据**:diff 和规则结果会发给你所选 provider 的 API 用于生成 review。
  不接 AI(不配任何 key)时,数据完全不出仓库,只跑本地规则。
- **费用**:按所选模型的 token 计费。`claude-sonnet-4-6` 性价比高;
  追求更低成本可换 `provider: deepseek`。单个普通 PR 通常只消耗很少 token。

---

## 目录结构

```
mobile-pr-guard/
├── action.yml                 # GitHub Action 定义(一行接入)
├── requirements.txt
├── mobile-pr-guard.yml.example
├── src/
│   ├── main.py                # 总编排:采集→规则→AI→评论
│   ├── config.py              # 读配置(零配置也能跑)
│   ├── collect_pr.py          # 第1周:PR 数据采集(Android + iOS 文件)
│   ├── rules.py               # 第2周:Android 规则 + 平台分发/自动识别
│   ├── rules_ios.py           # iOS 规则集(与 Android 对称)
│   ├── semgrep_scan.py        # Semgrep 静态分析接入(优雅降级)
│   ├── external_scanners.py   # 可配置接入 detekt/Lint/SwiftLint(读 SARIF)
│   ├── prompts.py             # 第3周:AI 提示词
│   ├── ai_review.py           # 第3周:多模型适配(Claude/DeepSeek/OpenAI)
│   ├── post_comment.py        # 第4周:回写评论(底部汇总 + 行内评论)
│   └── precommit.py           # 本地提交前拦截(被 pre-commit hook 调用)
├── hooks/pre-commit           # git 钩子脚本
├── scripts/install-hooks.sh   # 一键安装钩子
├── semgrep-rules/             # 内置 Semgrep 规则目录(加 .yml 自动生效)
│   ├── mobile.yml             #   Kotlin / Swift 移动端规则
│   └── polyglot.yml           #   Python / JS / TS 跨语言规则
├── .github/workflows/example-usage.yml
├── demo-android/              # 故意埋了风险的 Android 演示工程
├── demo-ios/                  # 故意埋了风险的 iOS 演示工程
└── docs/LEARNING.md           # 👈 边学边做:所有概念的大白话讲解
```

---

## 想边看代码边学习?从这里开始

整个项目就是一条流水线,`src/main.py` 是总指挥,其它 `src/*.py` 是流水线上的工位。
**推荐阅读顺序**(跟着数据流走):

1. `src/main.py` — 全局地图(不到 100 行),先读它,看清整条流水线
2. `src/collect_pr.py` — 数据从哪来(`ChangedFile` / `PRContext`)
3. `src/rules.py` → `src/rules_ios.py` — 怎么找毛病(同一套路,换清单)
4. `src/semgrep_scan.py` / `src/external_scanners.py` — 借外部工具,翻译成统一 `Finding`
5. `src/prompts.py` → `src/ai_review.py` — 给 AI 提要求 + 调模型(看 `PROVIDERS` 换插头表)
6. `src/post_comment.py` — 回写评论(看 `MARKER` 怎么实现「更新而不刷屏」)

> 📖 **完整代码导读 + 每个文件职责 + 三个贯穿全局的约定**,见
> [docs/LEARNING.md](docs/LEARNING.md) 开头的「📂 代码导读」小节。
> 那里还讲了「边看边动手」的最快学法:改一行 demo 代码,跑一次,看 finding 怎么变。

---

## 路线图(你现在在第一阶段)

1. **MVP(已搭好)**:Action + 规则 + AI + PR 评论 + 多平台 + 多模型。
2. **可交付(进行中)**:配置文件 ✅、团队规范 ✅、Semgrep ✅、报告持久化 ✅、
   可配置外部工具(detekt/Lint/SwiftLint via SARIF)✅;待办:在真实仓库跑通。
3. **客户试用**:找 5–10 个小团队免费审 PR,做案例报告,开始按服务收费。
4. **产品化**:有人付费后再做轻量后台(GitHub App + 控制台)。

核心原则:**先让它能审一个真实 PR,再让它变漂亮。**
