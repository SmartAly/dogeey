#!/bin/bash
# Dogeey WebUI 启动脚本 - 守护进程模式

LOG_FILE="/tmp/dogeey_webui.log"
PID_FILE="/tmp/dogeey_webui.pid"
WORK_DIR="/Users/aly/Documents/trae_projects/dogeey"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "⚠️  WebUI已在运行 (PID: $OLD_PID)"
        exit 0
    else
        echo "🧹 清理旧的PID文件"
        rm -f "$PID_FILE"
    fi
fi

# 启动进程
cd "$WORK_DIR"
nohup python3 -m uvicorn dogeey.web.backend:app --host 127.0.0.1 --port 8080 > "$LOG_FILE" 2>&1 &
NEW_PID=$!

# 保存PID
echo "$NEW_PID" > "$PID_FILE"

# 等待并检查
sleep 3
if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "✅ Dogeey WebUI启动成功! PID: $NEW_PID"
    echo "📋 日志: $LOG_FILE"
    echo "🌐 地址: http://127.0.0.1:8080"
else
    echo "❌ 启动失败，查看日志:"
    tail -20 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
