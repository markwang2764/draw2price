#!/bin/bash

# ============================================
# 快速查看服务器错误日志
# ============================================

SERVER_IP="8.136.55.76"
SERVER_USER="root"
SERVER_PORT="22"

echo "============================================"
echo "  查看服务器最近的日志"
echo "============================================"
echo ""

echo "📋 最近 50 行后端日志 (包含错误):"
echo "----------------------------------------"
ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "journalctl -u mistral-backend -n 50 --no-pager"

echo ""
echo "============================================"
echo "💡 提示: 运行以下命令查看实时日志:"
echo "   ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP"
echo "   journalctl -u mistral-backend -f --no-pager"
echo "============================================"
