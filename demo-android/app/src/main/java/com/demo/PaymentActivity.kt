package com.demo

import android.app.Activity
import android.os.Bundle

// 一个故意埋了多种风险的支付页,用来演示 Mobile PR Guard 的 PR 评论。
class PaymentActivity : Activity() {

    private val authToken = "EXAMPLE_FAKE_TOKEN_payment_998877"   // 硬编码 token -> HIGH

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val amount = intent.getStringExtra("amount")!!            // !! 强解包 -> NPE 风险
        val url = "http://pay.demo.com/charge?amount=$amount"     // 明文 http -> HIGH

        Runtime.getRuntime().exec("echo $amount")                 // 命令执行 -> Semgrep 命中

        charge(url)
    }

    private fun charge(url: String) { /* ... */ }
}
// 触发 CI 重跑(验证行号修复:!! 应报第 14 行、http 第 15 行)
