package com.demo

import android.app.Activity
import android.os.Bundle
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch

class LoginActivity : Activity() {

    private val apiKey = "EXAMPLE_FAKE_TOKEN_do_not_use_0011"   // 硬编码密钥 -> HIGH

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val token = intent.getStringExtra("token")!!          // !! 强解包 -> NPE 风险
        val url = "http://api.demo.com/login?token=$token"     // 明文 http -> HIGH

        GlobalScope.launch {                                   // GlobalScope -> 泄漏风险
            login(url)
        }

        Runtime.getRuntime().exec("logcat -c $token")          // 命令执行 -> Semgrep 命中
    }

    private fun login(url: String) { /* ... */ }
}
