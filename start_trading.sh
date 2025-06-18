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
# 直接使用trading.py中的配置加载函数
import sys
import os
sys.path.append('.')

try:
    # 临时重定向输出，避免打印配置加载信息
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    
    from trading import load_config
    config, trade_symbols = load_config('config.json')
    
    # 恢复输出
    sys.stdout = old_stdout
    
    print(config['TESTNET'])
except Exception as e:
    # 恢复输出
    sys.stdout = old_stdout
    print('true')  # 默认为测试模式
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