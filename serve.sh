#!/bin/bash
# serve.sh - 启动本地HTTP服务器，模拟GitHub Pages环境
# 用法: ./serve.sh [端口号]
cd "$(dirname "$0")"
PORT="${1:-8765}"
echo "============================================"
echo "  本地预览服务已启动"
echo "  地址: http://localhost:${PORT}"
echo "  按 Ctrl+C 停止"
echo "============================================"
python3 -m http.server "$PORT"
