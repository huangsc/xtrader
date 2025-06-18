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

# 检查配置文件中的testnet设置
TESTNET_STATUS=$(python3 -c "
import json
with open('config.json', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')
    clean_lines = []
    for line in lines:
        if '//' in line and not line.strip().startswith('\"'):
            line = line.split('//')[0].rstrip()
        clean_lines.append(line)
    clean_content = '\n'.join(clean_lines)
    config = json.loads(clean_content)
print(config['api']['testnet'])
")

# 如果是实盘模式，给出警告和设置选项
if [ "$TESTNET_STATUS" = "False" ]; then
    echo "⚠️  检测到实盘交易模式！"
    echo "💡 后台运行实盘模式需要设置环境变量："
    echo "   export XTRADER_CONFIRM_LIVE=true"
    echo ""
    read -p "是否设置环境变量并继续？(y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        export XTRADER_CONFIRM_LIVE=true
        echo "✅ 已设置环境变量，继续启动..."
    else
        echo "❌ 已取消启动"
        echo "💡 建议修改config.json中的testnet为true使用测试模式"
        exit 1
    fi
fi

# 选择运行方式
METHOD=${1:-screen}

case $METHOD in
    "screen")
        echo "🚀 使用screen启动交易机器人..."
        screen -dmS trading_bot bash -c "export XTRADER_CONFIRM_LIVE=$XTRADER_CONFIRM_LIVE; python3 trading.py"
        echo "✅ 交易机器人已在screen会话中启动"
        echo "💡 使用 'screen -r trading_bot' 连接到会话"
        echo "💡 使用 'screen -ls' 查看所有会话"
        ;;
    "tmux")
        echo "🚀 使用tmux启动交易机器人..."
        tmux new-session -d -s trading_bot bash -c "export XTRADER_CONFIRM_LIVE=$XTRADER_CONFIRM_LIVE; python3 trading.py"
        echo "✅ 交易机器人已在tmux会话中启动"
        echo "💡 使用 'tmux attach-session -t trading_bot' 连接到会话"
        ;;
    "nohup")
        echo "🚀 使用nohup启动交易机器人..."
        XTRADER_CONFIRM_LIVE=$XTRADER_CONFIRM_LIVE nohup python3 trading.py > trading.log 2>&1 &
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