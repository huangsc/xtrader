#!/bin/bash

# XTrader 交易机器人启动脚本
# 使用方法: ./start_trading.sh [screen|nohup|tmux]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 虚拟环境不存在，正在创建..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📦 检查依赖..."
pip install -r requirements.txt > /dev/null 2>&1

# 选择运行方式
METHOD=${1:-screen}

case $METHOD in
    "screen")
        echo "🚀 使用screen启动交易机器人..."
        screen -dmS trading_bot python3 trading.py
        echo "✅ 交易机器人已在screen会话中启动"
        echo "💡 使用 'screen -r trading_bot' 连接到会话"
        echo "💡 使用 'screen -ls' 查看所有会话"
        ;;
    "tmux")
        echo "🚀 使用tmux启动交易机器人..."
        tmux new-session -d -s trading_bot python3 trading.py
        echo "✅ 交易机器人已在tmux会话中启动"
        echo "💡 使用 'tmux attach-session -t trading_bot' 连接到会话"
        ;;
    "nohup")
        echo "🚀 使用nohup启动交易机器人..."
        nohup python3 trading.py > trading.log 2>&1 &
        echo "✅ 交易机器人已在后台启动"
        echo "💡 使用 'tail -f trading.log' 查看日志"
        echo "💡 使用 'ps aux | grep trading.py' 查看进程"
        ;;
    *)
        echo "❌ 未知的启动方式: $METHOD"
        echo "支持的方式: screen, tmux, nohup"
        exit 1
        ;;
esac 