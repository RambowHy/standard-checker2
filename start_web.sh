#!/bin/bash

set -e

echo "启动国家标准状态查询 Web 应用..."
echo ""

if ! command -v python3 &> /dev/null; then
  echo "错误: 未找到 Python3"
  exit 1
fi

if ! python3 -c "import streamlit" 2>/dev/null; then
  echo "正在安装依赖..."
  python3 -m pip install -r requirements.txt
fi

local_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$local_ip" ]; then
  local_ip="服务器局域网IP"
fi

echo "正在启动应用..."
echo "本机访问: http://localhost:8501"
echo "局域网访问: http://${local_ip}:8501"
echo ""

python3 -m streamlit run web_app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true
