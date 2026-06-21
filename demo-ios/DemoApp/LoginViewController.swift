import UIKit
import CoreLocation

class LoginViewController: UIViewController {

    // 硬编码密钥 -> HIGH
    private let apiKey = "EXAMPLE_FAKE_TOKEN_do_not_use_0011"

    // 隐式解包可选 -> LOW(为 nil 时访问即崩溃)
    private var session: URLSession!

    override func viewDidLoad() {
        super.viewDidLoad()

        let raw = UserDefaults.standard.string(forKey: "token")
        let token = raw as! String                       // as! 强转 -> MEDIUM

        // 明文 http -> HIGH(ATS 会拦 + 中间人风险)
        let url = URL(string: "http://api.demo.com/login?token=\(token)")!

        let nonce = arc4random()                         // 不安全随机 -> Semgrep 命中
        let data = try! Data(contentsOf: url)            // try! 强制 try -> MEDIUM

        DispatchQueue.main.sync {                         // 主线程 sync -> HIGH(死锁)
            self.render(data)
        }
    }

    private func render(_ data: Data) { /* ... */ }
}
