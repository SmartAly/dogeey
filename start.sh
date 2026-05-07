#!/bin/bash
# Dogeey 快速启动脚本

echo "🤖 Dogeey 启动脚本"
echo "================================"

# 检查Python版本
python3 --version >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ 未找到Python3，请先安装Python 3.10+"
    exit 1
fi

# 检查是否安装
pip3 show dogeey >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "📦 正在安装Dogeey..."
    pip3 install -e .
fi

# 检查配置
if [ ! -f ~/.dogeey/config.json ]; then
    echo "⚙️  首次运行，需要配置..."
    dogeey init
fi

# 启动选项
echo ""
echo "请选择启动方式："
echo "  1) CLI模式 - 运行指令"
echo "  2) WebUI模式 - 启动网页界面"
echo "  3) 测试 - 运行基本测试"
echo ""
read -p "请输入选项 (1-3): " choice

case $choice in
    1)
        read -p "请输入指令: " instruction
        dogeey run "$instruction" -v
        ;;
    2)
        echo "🌐 启动WebUI..."
        dogeey webui
        ;;
    3)
        echo "🧪 运行测试..."
        python3 test_basic.py
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac
