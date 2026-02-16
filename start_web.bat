@echo off
chcp 65001 >nul
REM 启动Streamlit Web应用

echo 🚀 启动国家标准状态查询Web应用...
echo.

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
  echo ❌ 错误: 未找到 Python
  pause
  exit /b 1
)

REM 检查依赖
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
  echo 📦 正在安装依赖...
  pip install -r requirements.txt
)

echo 🌐 正在启动应用...
echo 📍 应用将在浏览器中打开: http://localhost:8501
echo.

REM 启动Streamlit
streamlit run web_app.py

pause
