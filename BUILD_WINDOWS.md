# Windows 可执行程序构建说明

## 方法一：GitHub Actions 自动构建（推荐）

每次推送到 `main` 分支时，GitHub Actions 会自动构建 Windows 可执行程序。

### 获取可执行程序：

1. **推送到 GitHub 后**，访问仓库的 Actions 页面查看构建状态
2. **构建完成后**，在 Release 页面下载 `标准查询工具.exe`

### 手动触发构建：
```bash
git push origin main
```

然后访问: `https://github.com/RambowHy/standard-checker2/actions`

---

## 方法二：本地 Windows 构建

在 Windows 电脑上执行以下步骤：

### 1. 安装依赖
```bash
pip install pyinstaller pandas requests openpyxl
```

### 2. 构建单文件可执行程序
```bash
pyinstaller --onefile --name "标准查询工具" standard_checker.py
```

或使用配置文件：
```bash
pyinstaller "标准查询工具.spec"
```

### 3. 输出位置
生成的可执行程序位于：`dist/标准查询工具.exe`

---

## 方法三：交叉编译（Linux/macOS）

使用 Wine + PyInstaller（不推荐，可能有兼容性问题）：

```bash
# 安装 Wine（仅适用于 Linux/macOS）
# 然后在 Wine 环境中安装 Python 和 PyInstaller
# 最后运行构建命令
```

---

## 构建配置说明

### PyInstaller 参数
- `--onefile`: 打包成单个可执行文件
- `--name`: 指定输出文件名
- `--console`: 保留控制台窗口（用于查看输出）

### 包含的依赖
- pandas: 处理 Excel 文件
- requests: HTTP 请求
- openpyxl: Excel 读写支持

---

## 使用可执行程序

```bash
# 单个标准查询
标准查询工具.exe -s "GB 2757-2012"

# 批量查询
标准查询工具.exe -s "GB 2762-2017" "GB/T 8170-2008"

# Excel 更新
标准查询工具.exe -f standards.xlsx -o output.xlsx
```

---

## 注意事项

1. **文件大小**: 单文件包含 Python 运行时和依赖，约 20-30MB
2. **杀毒软件**: 某些杀毒软件可能误报 PyInstaller 打包的程序，请添加信任
3. **依赖项**: 确保同目录下有 `standards.xlsx` 文件（如需 Excel 功能）
