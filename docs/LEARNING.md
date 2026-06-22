# 边学边做:Mobile PR Guard 涉及的所有概念(大白话版)

这份文档按「你会在工程里遇到的顺序」讲。每个概念都配一个生活化的比喻,
读完你不只会用这个工具,还会理解它为什么这么搭。

---

## 0. 先有个全局画面:这个工具到底在干嘛?

想象你们团队是一家**餐厅**。

- 厨师 = 开发者
- 一道新菜 = 一次代码改动(PR)
- 出餐前的「质检员」= 我们要做的 Mobile PR Guard

以前每道菜出锅,得叫一位**老师傅**(资深工程师)过来尝一口、挑毛病。
老师傅很贵、很忙,而且会累。

我们要做的,是给厨房装一个**自动质检台**:
菜一做好,自动检查「咸淡(明显错误)」,再请一位 **AI 老师傅**尝一口给评语,
最后把意见贴在菜旁边的小纸条上。老师傅只需要在拿不准时才亲自来。

这就是整条流水线:

```
开发者提交 PR → 自动拉取改动 → 规则扫描(查铁证)→ AI 判断(给评语)→ 贴回 PR
```

---

## 📂 代码导读:每个文件干什么 + 推荐阅读顺序

**先记住一句话**:整个项目就是一条流水线,`src/main.py` 是「总指挥」,
其它每个 `src/*.py` 是流水线上的一个工位。看代码就顺着流水线走,最不容易晕。

### 目录长什么样

```
mobile-pr-guard/
├── action.yml                 # 【封面】让本项目变成可被 `uses:` 引用的 GitHub Action
├── requirements.txt           # 依赖清单(anthropic / openai / semgrep / pyyaml)
├── mobile-pr-guard.yml.example # 给客户抄的配置模板(改名成 mobile-pr-guard.yml 生效)
│
├── src/                       # 👈 全部逻辑都在这
│   ├── main.py                # 【总指挥】串起整条流水线,从这里开始读
│   ├── collect_pr.py          #  工位1:采集 PR(GitHub 模式 / 本地模式)
│   ├── config.py              #  读配置(零配置也能跑,全有默认值)
│   ├── rules.py               #  工位2a:Android 手写规则 + 平台分发/识别
│   ├── rules_ios.py           #  工位2b:iOS 手写规则(与 rules.py 对称)
│   ├── semgrep_scan.py        #  工位2c:跑 Semgrep 静态分析
│   ├── external_scanners.py   #  工位2d:跑 detekt/Lint/SwiftLint 并读 SARIF 报告
│   ├── prompts.py             #  工位3a:给 AI 的「工作说明书」(提示词)
│   ├── ai_review.py           #  工位3b:调大模型(Claude/DeepSeek/OpenAI)
│   └── post_comment.py        #  工位4:把结果回写成 PR 评论(幂等更新)
│
├── semgrep-rules/             # Semgrep 规则(加 .yml 自动生效)
│   ├── mobile.yml             #   Kotlin / Swift 移动端规则
│   └── polyglot.yml           #   Python / JS / TS 跨语言规则
│
├── demo-android/              # 故意埋了雷的安卓样例工程(本地测试用)
├── demo-ios/                  # 故意埋了雷的 iOS 样例工程
├── .github/workflows/         # 示范别人怎么在自己仓库接入
└── docs/LEARNING.md           # 你正在看的这份
```

### 推荐阅读顺序(跟着数据流走)

> 把数据想象成一个「包裹」:`main.py` 决定它走哪几个工位,每个工位往包裹里塞东西。

1. **`src/main.py`(必读,先看它)** — 90 行不到,是全局地图。
   你会看到它依次调用:采集 → 规则+Semgrep+外部工具 → AI → 评论。
   读懂它,你就知道后面每个文件「在什么时候被调用」。

2. **`src/collect_pr.py`** — 包裹是怎么造出来的。
   看两个数据结构:`ChangedFile`(一个文件改了什么)和 `PRContext`(整个 PR)。
   重点看 `added_lines()`:为什么我们只关心「新增的行」。

3. **`src/rules.py`** — 第一个真正「找毛病」的地方。
   先看最下面的 `run_rules`(总入口、按平台分发),再往上看每条 `rule_*` 函数。
   每条规则都是同一个套路:扫 `added_lines()` → 命中就产出一个 `Finding`。
   看完它,再看 `rules_ios.py` 你会发现是「同一套路、换清单」,几分钟就懂。

4. **`src/semgrep_scan.py` + `src/external_scanners.py`** — 「借助外部工具」的两个工位。
   关键看它们怎么把别人的输出(JSON / SARIF)翻译成我们统一的 `Finding`。

5. **`src/prompts.py` → `src/ai_review.py`** — AI 这一段。
   先读 prompts(我们对 AI 提了什么要求),再读 ai_review(怎么把请求发出去、
   失败了怎么优雅降级)。重点看 `PROVIDERS` 那张「换插头」表。

6. **`src/post_comment.py`** — 收尾。看 `MARKER` 那个隐藏标记,
   理解「为什么能更新同一条评论而不是刷屏」。

7. **`src/config.py`** — 任何时候想知道「这个开关从哪来」,来这看 `DEFAULTS`。

### 三个「贯穿全局」的关键约定(看到就不慌)

- **`Finding`(定义在 rules.py)**:所有工位产出的风险都长这个样子
  (文件 / 行号 / 等级 / 说明 / 建议)。它是流水线上的「通用货币」,
  正因如此,Semgrep、detekt、AI 的结果才能合并成一条评论。
- **优雅降级**:每个会失败的工位(AI、Semgrep、外部工具)失败时都是「跳过」,
  绝不让整个 CI 崩。看到 `try/except ... return []` 就是这个意思。
- **两种运行模式**:`--local 目录`(不连 GitHub,扫本地文件)和 GitHub 模式
  (读真实 PR)。看代码时注意 `local_dir` / `GITHUB_WORKSPACE` 这条分叉。

### 边看边动手(最快的学法)

```bash
python3 src/main.py --local demo-android   # 看它打印 [1/4]~[4/4],对照 main.py
cat demo-android/reports/mobile-pr-guard/local-findings.json   # 看产出的 Finding 长啥样
```

改一行 demo 代码(比如把 `!!` 删掉),再跑一次,看 finding 少了一条——
你就亲眼看见「某条规则 ↔ 某个产出」的对应关系了。

---

## 1. 什么是 PR(Pull Request)?

**比喻:交作业。**

你不能直接在「全班共用的作业本」(主分支 main)上乱写。
你先复印一份(开个分支),在复印件上写完,然后举手说:
「老师,我写好了,请把我的内容**合并**进正式本子。」——这个「请求合并」就是 PR。

PR 是个天然的「检查关卡」:东西还没进主线,正好在这里拦一道质检。
这就是为什么 PR Review 工具都挂在 PR 上,而不是挂在别处。

---

## 2. 什么是 diff?

**比喻:老师的红笔。**

老师批改时不会把你整篇作文重抄一遍,只用红笔圈出**你改动的地方**:
哪行加了(`+`)、哪行删了(`-`)。这份「只看改动」的对照表就是 diff。

为什么重要?因为一个 App 项目可能有几十万行代码,
但这次 PR 可能只改了 30 行。我们只审这 30 行,既省钱又精准。

> 在我们的代码里,`ChangedFile.added_lines()` 干的就是这件事:
> 从 diff 里把以 `+` 开头的「新增行」挑出来,只扫这些。

---

## 3. 什么是 GitHub Actions?(本项目的心脏)

**比喻:门口的自动感应装置。**

你家大门装了个感应器:**只要有人进门(触发条件),灯就自动亮(执行动作)。**
你不用守在门口,它自己反应。

GitHub Actions 就是 GitHub 给你仓库装的「感应器 + 自动工人」:

- **触发条件(on)**:比如「有人开 PR」。
- **工人(runner)**:GitHub 免费借给你一台干净的云电脑(`ubuntu-latest`)。
- **干的活(steps)**:在那台云电脑上,一步步执行你写的命令。

我们的 `example-usage.yml` 就是在说:

> 「**每当有人开/更新 PR,就借一台 Ubuntu,把代码拉下来,跑我们的质检脚本。**」

关键认知:**Actions = 事件触发的自动化流水线**。
它不是一直开机的服务器,而是「有事才临时开机、干完就关机」。
所以第一版根本不需要买服务器、不需要做网站——这就是为什么 MVP 要从 Action 起步。

---

## 4. 什么是 YAML?为什么配置都长那样?

**比喻:填表格,不是写程序。**

YAML 是一种「用缩进表示层级」的配置写法。它不是编程语言,就是**结构化的填空**:

```yaml
review:
  fail_on_high_risk: false
  comment_on_pr: true
```

读作:「review 这一项下面,有两个开关。」
缩进(空格)代表从属关系。**千万别用 Tab,YAML 只认空格**,这是新手最常踩的坑。

---

## 5. 什么是 Token / Secret?

**比喻:门禁卡 + 保险柜。**

- **GitHub Token** = 一张「门禁卡」,刷一下才允许脚本去读 PR、写评论。
  没有它,GitHub 不知道「你是谁、凭什么动我的 PR」。
- **ANTHROPIC_API_KEY** = 另一张门禁卡,刷一下才允许你调用 Claude(并计费)。

这些卡**绝对不能写进代码**(等于把家门钥匙贴在大门上)。
GitHub 提供一个**保险柜**叫 **Secrets**:你把卡放进去,
工作流里用 `${{ secrets.ANTHROPIC_API_KEY }}` 取用,别人看不到明文。

> 在我们的代码里,`os.environ["GITHUB_TOKEN"]` 就是从「保险柜递进来的环境变量」里取卡。

---

## 6. 什么是「静态分析 / Lint / detekt / Semgrep」?

**比喻:不点火就能查的安检。**

- **动态检查** = 把车开起来跑一圈看有没有问题(运行程序、跑测试)。
- **静态检查(静态分析)** = 车停着,光看图纸和零件就挑毛病。**不运行代码**。

我们第 2 周做的「规则扫描」就是最朴素的静态分析:
看到 `!!` 就提示 NPE 风险,看到 `http://` 就提示明文传输。
它靠**模式匹配(正则)**,所以便宜、秒出、可解释。

而成熟的现成工具是它的加强版:
- **Android Lint**:Google 官方,查 Android 特有问题(权限、API 兼容等)。
- **detekt**:专门查 Kotlin 代码风格和坏味道。
- **Semgrep**:跨语言的「语义级 grep」,能写更聪明的规则。

第二阶段我们会把这些工具的结果也喂给 AI,等于「安检员 + 老师傅」一起上。

> 进阶名词:**AST(抽象语法树)**。
> 正则是「按字面找」,容易误伤(比如注释里的 `!!`)。
> AST 是先把代码解析成一棵「语法结构树」,再按结构找,准得多。
> detekt/Semgrep 底层就是用 AST。MVP 阶段用正则够用,这是有意为之的取舍。

---

## 7. 为什么「先规则、后 AI」?

**比喻:先用尺子量,再请专家看。**

- 「这个 PR 加没加 CAMERA 权限?」——这是**事实**,用尺子(规则)一量就知道,
  不需要花钱问专家,而且专家也可能看漏。
- 「这段登录逻辑在弱网下会不会出问题?」——这是**判断**,需要专家(AI)结合上下文。

把确定的事交给规则,把模糊的事交给 AI。
而且我们把规则结果**一起塞进给 AI 的提示词**里,等于先把铁证摆在专家面前,
让它的评语更准、更不容易胡说。

---

## 8. 什么是 LLM API 调用?什么是 Prompt?

**比喻:给一位很强但没记忆的远程顾问发传真。**

Claude 不在你电脑里,它在云端。你通过 **API**(一个网络接口)给它「发传真」:
传真内容 = **Prompt(提示词)**,它读完回你一段文字。

两个关键点:

1. **它没有记忆**。每次调用都得把所有背景重新讲一遍
   (PR 标题、改了什么、规则结果……)。这就是 `build_user_prompt` 在拼的东西。
2. **说明书的质量决定结果质量**。我们在 `SYSTEM_PROMPT` 里立了铁律:
   「只基于 diff 说话 / 不确定就说需要人工确认 / 不许说空话 / 低风险别卡 PR」。
   这叫 **Prompt 工程**——把老师傅的审查习惯写成明文规矩。

> 模型选择:审代码我们默认 `claude-sonnet-4-6`(快、便宜、够聪明);
> 遇到特别复杂的 PR,可在配置里换成更强的 `claude-opus-4-8`。

---

## 9. 什么是「幂等更新评论」?

**比喻:同一张便利贴反复改,而不是贴一墙。**

PR 每推一次新 commit,我们的流水线就跑一次。如果每次都**新发**一条评论,
PR 底下很快贴满几十条,没人看。

做法:在评论里藏一个**隐形记号**(HTML 注释 `<!-- mobile-pr-guard-review -->`)。
下次跑的时候先找「带这个记号的旧评论」,找到就**改它**,找不到才**新发**。
于是一个 PR 永远只有**一条**Guard 评论,内容随最新结果更新。

「不管跑多少次,结果状态一致」——这个性质就叫**幂等**。

---

## 10. 什么是「优雅降级 / 兜底」?

**比喻:停电了也要有应急灯。**

AI 可能调用失败(没钱、超时、网络抖动)。绝对不能因为 AI 挂了,
就把人家整条 CI 带崩、害得 PR 合不了。

我们的 `ai_review.py` 里:AI 一旦出错,`_fallback_review` 立刻顶上,
退回到「只展示规则扫描结果」。功能打折,但不瘫痪。
**「失败不影响正常 CI」是我们对客户的核心承诺之一。**

---

## 11. 什么是「composite Action」?为什么能让别人一行接入?

**比喻:把一套工序打包成一个「按钮」。**

我们的流水线有好几步(装 Python、装依赖、跑脚本)。
`action.yml` 用 `using: composite` 把这几步**封装成一个动作**,
对外只暴露一个名字。别人就不用关心内部,直接:

```yaml
- uses: volley5566/mobile-pr-guard@v1
```

一行接入。这就是为什么「做成 Action」比「做成网站」更容易卖——
**接入成本极低**,改一个 yml 文件的事。

---

## 12. 后面才会用到的概念(先混个脸熟)

- **GitHub App**:比 Action 更重的「正式入驻」。Action 是你跑在别人仓库里的脚本;
  App 是一个有身份、能管理多个仓库、有后台的「正式应用」。
  等你有付费客户、要做控制台时再上。

- **FastAPI / PostgreSQL / Redis / Celery**:做后台时的标准件。
  分别是:接口框架(前台点单)、数据库(账本)、缓存(便签)、任务队列(后厨排号)。

- **LangGraph**:把「AI 工作流」画成一张有节点、有分支、能回头的流程图的框架。
  **MVP 千万别上**——你现在的流程是直线(采集→扫描→AI→评论),
  普通脚本就够。等流程出现「初审→二次验证→分级→人工反馈→回炉」这种带环、
  带条件分支的复杂度时,LangGraph 才划算。**先让它能审一个真实 PR,再让它变漂亮。**

---

## 13. Claude Code vs Claude API:同一个模型,两种用法

**比喻:同一个老师,一个是「请到家里手把手带」,一个是「发邮件问一道题」。**

- **Claude Code** = 会自己动手的实习生。给一句话,它自己读文件、写代码、跑命令、
  改 bug,**交互式、多步、会思考下一步**。(你现在对话的就是它。)
- **Claude API** = 一个问答窗口。递进去一段文字,吐回一段文字,**一问一答,不动手**。

**本项目用的是 API**(见 `ai_review.py`)。因为 GitHub Action 是无人值守、跑完即焚的环境,
你要的是「喂一个 PR、稳定吐一段 Markdown」这种**一次精准问答**,
不需要一个会到处乱翻、行为不可预测、还更慢更贵的实习生。
**判断口诀:要可预测的单次结果 → 用 API;要它自主完成开放式任务 → 用 Claude Code。**

---

## 14. 适配器模式:为什么换 DeepSeek 只改一行?

**比喻:出国带的「万能电源转接头」。**

你的吹风机(= 我们的 prompt)一点都不用改,只要**换个插头头子**,
就能插进美标、欧标、英标的墙插(= Claude / DeepSeek / OpenAI 各家接口)。

`ai_review.py` 里那张 `PROVIDERS` 表就是「各国插头规格说明书」:
每家需要哪把钥匙(环境变量)、连到哪个地址(base_url)、默认型号、用哪种调用风格。
客户只在 `mobile-pr-guard.yml` 写一行 `provider: deepseek` 就切换了。

**一个关键便宜事**:DeepSeek **兼容 OpenAI 的接口格式**,
所以用 `openai` SDK 改个 `base_url` 就能调它——
一份适配器,顺手把一票「OpenAI 兼容」的国产模型都支持了。

这对你的生意是卖点:出海/中小团队**最在意成本和可达性**,
「想用哪家模型自己挑」本身就是一句销售话术。

> 同理,平台也用了这个思路:`rules.py` 是 Android 规则,`rules_ios.py` 是 iOS 规则,
> **引擎共用,只换「违禁品清单」**。`platform: auto` 还能看文件自动判断该用哪套。

---

## 15. Semgrep vs detekt vs Lint:静态分析工具到底怎么选?

先认人(都是「不运行代码、只读源码找毛病」的静态分析工具):

| 工具 | 懂什么语言 | 擅长 | 怎么跑 | 依赖 |
|------|-----------|------|--------|------|
| **Android Lint** | 只懂 Android | API 兼容、资源、权限、性能 | `./gradlew lint` | 整个工程能编译 + Android SDK |
| **detekt** | **只懂 Kotlin** | 代码风格、复杂度、坏味道 | `./gradlew detekt` | 配好 Gradle 插件 + JDK |
| **SwiftLint** | 只懂 Swift | Swift 风格/规范 | `swiftlint` | Swift 工具链(通常 macOS) |
| **Semgrep** | **跨 30+ 语言**(Kotlin/Java/Swift…) | 安全 + 自定义规则 | `semgrep scan` | 一个 `pip install`,**不需要工程能编译** |

**比喻**:
- detekt / Lint / SwiftLint 像**专科医生**——只看一个器官(Kotlin / Android / Swift),
  看得深;但你得分别请三位医生,而且每位都要求「诊室按它的规矩装修好」
  (detekt 要工程能编译、要 JDK + Android SDK)。
- Semgrep 像**全科 + 安检仪**——一台机器扫所有语言,自带就能跑,
  不要求你的工程能编译(它只读源码的语法结构),规则你自己用 YAML 写。

**那为什么本项目先接 Semgrep、暂时不接 detekt?** 三个理由:

1. **环境轻**:detekt 要在 CI 里装 JDK + Android SDK + 让整个 Gradle 工程能 `build`,
   几分钟起步还常因环境炸;Semgrep 一个 `pip install` 就能跑。
2. **跨平台**:我们刚加了 iOS。Semgrep **一套引擎同时管 Kotlin 和 Swift**;
   换 detekt 就只能管 Kotlin,iOS 还得再请 SwiftLint。
3. **能自定义 + 偏安全**:Semgrep 让我们把「移动端老司机的安全直觉」写成可读规则
   (见 `semgrep-rules/mobile.yml`),这正是产品的核心卖点。

**注意:它们不是二选一。** 终极形态是都接——detekt/Lint 抓 Android 质量坑、
SwiftLint 抓 Swift、Semgrep 抓跨语言安全与自定义规则,结果全合并进同一条 PR 评论。
只是**接入顺序**上 Semgrep 性价比最高先做;detekt/SwiftLint 依赖「工程能编译 + 平台工具链」,
更适合放在团队自己已有的 CI 里跑,我们去**读它生成的报告**即可。

**正则 vs Semgrep(承接第 6、7 节)**:
`rules.py` 的正则是「按字符找」;Semgrep 是「按代码结构(语法树)找」。
例如 `Runtime.getRuntime().exec(...)` 即使中间换行、改变量名、加注释,
正则就漏了,Semgrep 照样命中——因为它理解这是「同一个方法调用」。

---

## 16. 怎么把 detekt / Lint / SwiftLint「可配置」地接进来?

**难点**:每个项目的命令都不一样——`./gradlew detekt`、`./gradlew app:lintDebug`、
`swiftlint`……报告路径不同、格式也不同。**写死任何一条命令都是错的。**

**解法两步走,叫「编排 + 摄取」(orchestrate + ingest):**

1. **编排**:不内置命令,让客户在 `mobile-pr-guard.yml` 里**自己写命令**。
   我们只负责「在仓库根目录,按你给的命令去跑」。
   (命令甚至能留空 —— 表示"你 CI 里别的步骤已经跑过了,我只来读报告"。)
2. **摄取**:跑完去读它吐出的报告,转成统一的 `Finding`。

```yaml
external_scanners:
  - name: detekt
    run: "./gradlew detekt"                  # 你的项目用什么命令,就写什么
    report: "**/build/reports/detekt/detekt.sarif"   # 报告在哪(支持 ** 通配)
    format: sarif
```

**关键概念:SARIF —— 静态分析结果的「普通话」。**

不同工具吐的报告五花八门,但它们**都能输出 SARIF**(Static Analysis Results
Interchange Format,微软牵头的行业标准 JSON)。
所以我们**只写一个 SARIF 解析器,就能同时读懂 detekt / Android Lint / SwiftLint**。

比喻:三个工具像说三种方言的老师,各自写一份病历。
与其学三种方言,不如要求他们都用**普通话(SARIF)**写病历,我们看一份模板就全懂了。
(老牌项目还常用 checkstyle XML,所以我们也顺手支持了这一种。)

**严重度翻译**:SARIF 的 `error / warning / note` → 我们的 `HIGH / MEDIUM / LOW`。

**一个容易踩的坑**:linter **发现问题时本来就会返回非 0 退出码**——
这不是"命令失败",所以我们跑完**照样去读报告**,绝不能因为非 0 就跳过。

这套设计的好处:**新接一个工具(比如 ktlint、infer)几乎不用写代码**——
只要它能输出 SARIF,客户加几行配置就行。这就是「可配置」的真正含义:
把"项目差异"交给配置,把"通用能力"留在代码里。

---

## 17. 一个仓库混了好几种语言(polyglot)怎么办?

现实里一个项目常常不止一种语言:Android(Kotlin)+ iOS(Swift)+ Python/Node 后端,
未来的 AI agent 项目更是 Python + Node 混搭。我们用【三层】来覆盖,各管一摊:

| 层 | 管什么 | 怎么扩展 |
|----|--------|----------|
| **移动专用规则**(rules.py / rules_ios.py) | Android、iOS 的深度专有坑 | `platform: auto` 可【同时】识别多个;也可写 `[android, ios]` / `all` |
| **Semgrep**(semgrep-rules/) | 跨语言通用 + 安全(Kotlin/Swift/Python/JS/TS…) | 往 `semgrep-rules/` 目录加个 `.yml` 就自动生效 |
| **外部工具**(external_scanners) | 任意语言的成熟 linter(eslint/pylint/detekt…) | 配置里加一项命令 + SARIF 报告 |

**关键点**:`platform` 现在返回的是一个【列表】,monorepo 同时有安卓和 iOS 时,
两套规则都会跑,而且每条规则只对自己的文件生效(安卓规则只看 Manifest/gradle,
iOS 规则只看 Info.plist/swift),不会互相误伤。

**比喻**:像机场的多条安检通道——国内/国际/中转各走各的(移动规则),
再加一台所有行李都过的总 X 光机(Semgrep)。哪条通道没人就空着,不影响别的。

> 这就是「灵活配置」的底层逻辑:**通用能力写进代码(三层引擎),项目差异交给配置
> (platform 列表、semgrep 规则文件、external_scanners 命令)**。
> 以后做混合语言的 agent 项目,这套结构直接能复用。

---

## 18. 这个项目算「harness」吗?顺便搞懂 agent

**harness(运行架/驱动壳)**:在 AI 语境里,指【包在大模型外面、驱动它干活的那层壳】——
管对话循环、调工具、喂上下文、解析输出、决定下一步。

**Claude Code 本身就是一个 harness**(我们正用它来开发本项目);
但 **Mobile PR Guard 这个产品【不是】harness**——它只是【调一次 LLM API】:
一段 prompt 进、一段 markdown 出,没有循环、没有工具调用、没有多轮。

按复杂度看这条阶梯(也是本项目未来的成长路线):

```
Level 0  单次 API 调用        ← Mobile PR Guard 现在在这(不是 agent)
Level 1  LLM + 工具(单轮)
Level 2  agent 循环(ReAct):模型自己决定→调工具→看结果→再决定  ← 需要 harness
Level 3  多 agent / 图编排(分支、状态、人审)               ← LangGraph 就是这层的 harness
```

**判断口诀**:有没有「模型自己决定下一步、并反复循环」?有 = agent(需要 harness);
没有、就是固定流水线一次过 = 不是 agent。我们现在是后者,所以【先别上 LangGraph】。
等流程变成「初审→二次验证→分级→人工反馈→回炉」这种带环、带分支的复杂度,
LangGraph 才划算——那时它就是你的 harness。**先让它能审一个真实 PR,再让它变聪明。**

---

## 19. 做完之后怎么「发布」?别人怎么用?

**最反直觉的一点:GitHub Action 没有「打包上传」这一步。**
不像 App「编译成安装包→传应用商店」,Action 的「安装包」就是【仓库本身】。

**比喻**:像「分享菜谱」。你把菜谱(代码仓库)放到公开处,贴个版本号(git tag);
别人在自己厨房(他们的 workflow)写一句「我要用 X 菜谱的 v1」就行。
没有二进制、没有上传、没有构建产物。`action.yml` 在仓库根目录就是这张菜谱的封面。

**别人接入只要 3 步**:
1. 在他们仓库放 `.github/workflows/guard.yml`,里面写 `uses: 你/mobile-pr-guard@v1`;
2. 在他们仓库 Settings → Secrets 填一把 API key;
3. 开 PR → 自动评论。

> 运行时分工:`uses:` 把【你的仓库】临时 checkout 来跑(`github.action_path`);
> 它读取的是【客户的代码】(`GITHUB_WORKSPACE`,所以客户要先 actions/checkout)。

**发布三层级**(投入从小到大):

| 层级 | 做法 | 何时 |
|------|------|------|
| ① 公开仓库 + 打 tag | `git push` + 打 `v1` 标签;别人 `uses: 你/repo@v1` | MVP 起步 |
| ② 上架 Marketplace | 建 Release 勾选 Publish;需 action.yml 有 branding(已有) | 要曝光 |
| ③ GitHub App | 集中安装 + 计费的正式应用 | 做 SaaS/收费后台时 |

**版本号约定**:`@v1`(浮动大版本,发补丁时把 v1 标签移过去,用户自动获益)/
`@v1.2.0`(锁死最稳)/ `@main`(永远最新,但你一改就影响所有人,危险)。

**想收费又不公开源码?**(对应路线图「先卖服务,不卖 SaaS」)
私有仓库的 Action 只能被同账号/组织引用,跨团队卖有三条路:
(a) 把 Action 复制进客户仓库,收「接入/维护服务费」(起步最快);
(b) 打成私有 Docker 镜像分发;(c) 做成 GitHub App(终局)。

---

## 20. 什么是 git hook / pre-commit?和 CI 有什么分工?

**git hook**:git 在某些时机自动执行的脚本。`pre-commit` 这个钩子在你 `git commit`
【完成之前】运行,它**退出非 0 就会中止这次提交**。

**比喻**:CI(PR 时)是**机场安检**——托运后在中立机场统一查,绕不过、全队强制;
pre-commit 是你家**门口的保安**——出门(提交)那一刻先拦你一下,快、早,但能绕过
(`git commit --no-verify`),也得每个人自己装。

| | pre-commit(本地) | CI(PR 时) |
|---|---|---|
| 何时 | `git commit` 那一刻 | 开/更新 PR 时 |
| 跑在哪 | 你自己电脑 | GitHub 服务器 |
| 强制力 | 可被 `--no-verify` 绕过 | 配合分支保护**强制** |
| 定位 | 个人提前预警 | 团队级门禁 |

**一个关键设计**:`.git/hooks/` 目录**不随仓库提交**(git 出于安全不允许),
所以我们把钩子放在**会被提交的 `hooks/` 目录**,再用 `git config core.hooksPath hooks`
让 git 去那里找——这样钩子能随仓库共享,每个开发者 clone 后跑一次 `install-hooks.sh` 即可。

我们的 pre-commit 复用了 CI 同一套规则 + Semgrep(只扫 `git diff --cached` 的暂存改动),
所以**本地拦到的和 PR 上报的完全一致**——不会出现"本地过了 CI 却挂"的割裂。

---

## 一句话总结学习路径

> 你不是在「学一堆名词」,你是在**搭一条流水线**,
> 每个名词都是流水线上的一个工位。先把直线流水线跑通(MVP),
> 再逐个工位升级(真静态分析工具、后台、GitHub App)。
