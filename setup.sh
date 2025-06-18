#!/bin/bash

echo "🔧 交易机器人配置初始化脚本"
echo "================================"

# 检查config.json是否存在
if [ -f "config.json" ]; then
    echo "⚠️  config.json 已存在"
    read -p "是否覆盖现有配置？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "已取消初始化"
        exit 0
    fi
fi

# 复制示例配置文件
echo "📋 复制配置文件模板..."
cp config.json.example config.json

# 检查Python环境
echo "🐍 检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未找到，请先安装Python3"
    exit 1
fi

# 安装依赖
echo "📦 安装依赖包..."
pip3 install -r requirements.txt

echo ""
echo "✅ 初始化完成！"
echo ""
echo "📝 接下来请："
echo "1. 编辑 config.json 文件，填入你的API密钥"
echo "2. 设置 testnet: true 进行测试"
echo "3. 运行: python3 trading.py"
echo ""
echo "🔗 获取Binance API密钥: https://www.binance.com/zh-CN/my/settings/api-management"
echo "🔗 获取Telegram Bot Token: https://t.me/BotFather"
echo ""
echo "⚠️  重要提示："
echo "- 请先在测试网测试至少一周"
echo "- 实盘交易前仔细检查所有配置"
echo "- 建议初始资金不超过总资金的10%" 