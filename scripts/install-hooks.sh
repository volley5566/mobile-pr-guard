#!/bin/sh
# 一键安装 Mobile PR Guard 的本地 git 钩子。
# 原理:让 git 去 hooks/ 目录找钩子(该目录已随仓库提交,全队共享)。
# 每个开发者在 clone 后跑一次即可。
set -e
ROOT="$(git rev-parse --show-toplevel)"
git config core.hooksPath hooks
chmod +x "$ROOT/hooks/pre-commit"
echo "✅ 已安装:提交时将自动运行 Mobile PR Guard 检查(HIGH 风险会拦下提交)。"
echo "   跳过单次:git commit --no-verify"
echo "   卸载:git config --unset core.hooksPath"
