#!/bin/bash
# 启动Streamlit Web应用

echo "🚀 启动国家标准状态查询Web应用..."
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
  echo "❌ 错误: 未找到 Python3"
  exit 1
fi

# 检查依赖
if ! python3 -c "import streamlit" 2>/dev/null; then
  echo "📦 正在安装依赖..."
  python3 -m pip install -r requirements.txt
fi

echo "🌐 正在启动应用..."
echo "📍 应用将在浏览器中打开: http://localhost:8501"
echo ""

# 启动Streamlit
python3 -m streamlit run web_app.py
