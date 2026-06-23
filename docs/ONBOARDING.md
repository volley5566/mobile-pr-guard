# Mobile PR Guard · 试用接入指南(一页)

一个 **AI 代码评审**小工具:开发者提 PR/MR,它自动分析改动、跑规则 + Semgrep + AI,
把风险**贴成行内评论 + 一条汇总评论**。给 Android / iOS 团队用,也支持后端/前端语言。

> 默认**只评论、不卡合并**,失败也不影响你的 CI——零打扰,先试再说。

---

## 它会替你盯哪些事

| 类别 | 例子 |
|------|------|
| 权限/隐私 | 新增 `READ_MEDIA_IMAGES`、定位;iOS `Info.plist` 隐私用途、关闭 ATS |
| 安全 | 硬编码密钥、明文 `http://`、命令执行、WebView JS 注入 |
| 崩溃隐患 | `!!` / `GlobalScope`;Swift `try!` / `as!` / 主线程死锁 |
| 依赖 | 动态版本号、广告/统计/支付 SDK |
| 测试 | 改了业务却没动测试 |
| 发版 | 改了 `versionCode` / ProGuard / deeplink / `CFBundleVersion` |

---

## 接入(GitHub,3 步,约 5 分钟)

1. 把 `.github/workflows/example-usage.yml` 复制到你仓库,引用 `volley5566/mobile-pr-guard@v1`;
2. 仓库 **Settings → Secrets and variables → Actions** 加一把模型 key(三选一):
   `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`;
3. 在仓库根放一个 `mobile-pr-guard.yml`(参考 `mobile-pr-guard.yml.example`),写明 `provider`。

**GitLab**:把 `gitlab-ci.example.yml` 并进 `.gitlab-ci.yml`,在 CI/CD Variables 配模型 key
和有 `api` 权限的 `GITLAB_TOKEN`,开个 MR 即可。

开/更新 PR 后,几十秒内 PR 上会出现行内评论 + 一条 🛡️ 汇总评论(重复触发只更新同一条,不刷屏)。

---

## 误报了怎么办?(一键消音)

- **某一行**:行末或上一行写 `mpg-ignore` 注释,只静音那一行;
- **整片**:在 `mobile-pr-guard.yml` 的 `suppress:` 里按 规则+路径 静音。

被消音多少条会写进日志,不会偷偷吞掉。

---

## 数据与费用

- **数据**:只把这次 PR 的 diff + 规则结果发给你选的模型用于生成评语;不配 key 就只跑本地规则、数据不出仓库。
- **费用**:按模型 token 计,单个普通 PR 通常很少;想更省用 `provider: deepseek`。
- **不打扰**:默认 `fail_on_high_risk: false`(只评论不卡 CI);想当强制门禁再开,并配合分支保护。

---

## 怎么试最有代表性

- 选 **1–3 个有代表性的 PR**(最好涉及权限/网络/登录/支付/发版);
- 跑完对照 [反馈表](FEEDBACK.md) 记一下:**抓到几个真问题、几个误报、哪条规则吵**;
- 用真实结果决定:要不要常驻 CI、要不要调规则。

有问题随时找我们。
