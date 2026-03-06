# Windows 可执行程序打包指南

本文档介绍如何将国家标准查询工具打包成 Windows 可执行程序（.exe）。

---

## 方式一：GitHub Actions 自动构建（推荐）

### 配置说明

项目已配置 GitHub Actions 自动构建，每次推送到 `main` 分支时会自动打包。

### 使用步骤

1. **推送代码到 GitHub**
   ```bash
   git add .
   git commit -m "Update code"
   git push origin main
   ```

2. **查看构建状态**
   - 访问仓库的 Actions 页面
   - 查看 "Build Windows Executable" 工作流

3. **下载可执行程序**
   - 构建成功后，在 Releases 页面下载 `标准查询工具.exe`
   - 或在 Actions 页面下载 artifact

### 优点
- ✅ 无需本地 Windows 环境
- ✅ 自动化构建，稳定可靠
- ✅ 自动创建 Release

---

## 方式二：本地 Windows 手动打包

### 环境要求

- Windows 10 或更高版本
- Python 3.11+（建议使用 Python 3.11）

### 打包步骤

#### 方法 A：使用打包脚本（推荐）

双击运行 `build_local.bat`，脚本会自动：
1. 检查 Python 环境
2. 安装 PyInstaller
3. 安装项目依赖
4. 打包生成 .exe 文件

#### 方法 B：使用命令行

```bash
# 1. 安装 PyInstaller
python -m pip install pyinstaller

# 2. 安装项目依赖
python -m pip install -r requirements.txt

# 3. 使用 spec 文件打包
pyinstaller "标准查询工具.spec" --clean

# 或直接打包（不使用 spec 文件）
pyinstaller --onefile --name "标准查询工具" --console standard_checker.py
```

### 输出位置

生成的可执行文件位于：`dist\标准查询工具.exe`

---

## 方式三：在 Linux/macOS 上交叉编译（不推荐）

由于 PyInstaller 不支持跨平台打包，建议使用 GitHub Actions 或在 Windows 上打包。

---

## 打包配置说明

### PyInstaller 参数

| 参数 | 说明 |
|------|------|
| `--onefile` | 打包成单个可执行文件 |
| `--name` | 指定输出文件名 |
| `--console` | 保留控制台窗口（用于查看输出） |
| `--clean` | 清理临时文件后重新打包 |

### spec 文件配置

`标准查询工具.spec` 包含以下配置：

- **hiddenimports**: 显式包含的依赖模块
- **excludes**: 排除的不必要模块（减小文件体积）
- **upx**: 启用 UPX 压缩（进一步减小体积）

---

## 使用可执行程序

### 基本用法

```bash
# 查询单个标准
标准查询工具.exe -s "GB 2757-2012"

# 批量查询
标准查询工具.exe -s "GB 2762-2017" "GB/T 8170-2008"

# 更新 Excel 文件
标准查询工具.exe -f standards.xlsx -d 3.0

# 指定输出文件
标准查询工具.exe -f input.xlsx -o output.xlsx

# 使用代理
标准查询工具.exe -f standards.xlsx --proxy http://127.0.0.1:7890
```

### 注意事项

1. **首次运行**：杀毒软件可能误报，请添加信任
2. **文件位置**：建议将 .exe 文件与 Excel 数据文件放在同一目录
3. **文件大小**：约 20-30MB（包含 Python 运行时和所有依赖）
4. **系统要求**：Windows 10 或更高版本

---

## 常见问题

### 1. 打包后文件体积过大

**原因**：包含了完整的 Python 运行时和所有依赖库

**解决**：
- 已在 spec 文件中排除不必要模块
- 启用 UPX 压缩

### 2. 杀毒软件误报

**原因**：PyInstaller 打包的程序可能被识别为可疑文件

**解决**：
- 在杀毒软件中添加信任
- 或使用代码签名证书签名（需付费）

### 3. 运行时缺少模块

**原因**：某些隐式导入的模块未被包含

**解决**：
- 在 spec 文件的 `hiddenimports` 中添加缺失模块
- 重新打包

### 4. 打包失败

**排查步骤**：
1. 确认 Python 版本（建议 3.11）
2. 更新 PyInstaller：`pip install --upgrade pyinstaller`
3. 清理构建缓存：删除 `build/` 和 `dist/` 目录
4. 检查依赖是否正确安装

---

## 依赖清单

打包时包含的主要依赖：

```
pandas>=2.0.0
requests>=2.31.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
```

**注意**：Streamlit 依赖未包含，因此 Web 模式无法在 .exe 中使用。如需 Web 模式，请直接运行 Python 脚本。

---

## 文件结构

```
项目目录/
├── standard_checker.py      # CLI 主程序（打包入口）
├── web_app.py               # Web 界面（不打包）
├── web_checker.py           # Web 查询模块（不打包）
├── 标准查询工具.spec         # PyInstaller 配置
├── build_local.bat          # 本地打包脚本
├── .github/
│   └── workflows/
│       └── build.yml        # GitHub Actions 配置
└── dist/
    └── 标准查询工具.exe      # 输出的可执行文件
```