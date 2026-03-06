@echo off
chcp 65001 >nul
REM 本地 Windows 打包脚本

echo ========================================
echo 国家标准查询工具 - Windows 打包脚本
echo ========================================
echo.

REM 检查 Python 环境
python --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.11+
  pause
  exit /b 1
)

echo [1/4] 检查 Python 环境...
python --version

REM 安装 PyInstaller
echo.
echo [2/4] 安装/更新 PyInstaller...
python -m pip install --upgrade pyinstaller

REM 安装项目依赖
echo.
echo [3/4] 安装项目依赖...
python -m pip install -r requirements.txt

REM 开始打包
echo.
echo [4/4] 开始打包可执行文件...
echo.

REM 使用 spec 文件打包
pyinstaller "标准查询工具.spec" --clean

REM 检查打包结果
if exist "dist\标准查询工具.exe" (
  echo.
  echo ========================================
  echo [成功] 打包完成！
  echo ========================================
  echo.
  echo 可执行文件位置: dist\标准查询工具.exe
  echo 文件大小:
  for %%I in (dist\标准查询工具.exe) do echo   %%~zI 字节 ^(约 %%~nI MB^)
  echo.
  echo 使用方法:
  echo   标准查询工具.exe -s "GB 2757-2012"
  echo   标准查询工具.exe -f standards.xlsx -d 3.0
  echo.
) else (
  echo.
  echo [错误] 打包失败，请检查错误信息
)

pause