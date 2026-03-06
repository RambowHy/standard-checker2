# 国家标准状态查询工具 - AGENTS.md

**Generated:** 2026-03-06  
**Stack:** Python 3.x + pandas + requests + Streamlit

---

## OVERVIEW

查询国家标准在 ndls.org.cn 的现行有效性及替代信息。支持三种使用方式：
- **CLI模式**: `standard_checker.py` - 命令行批量查询
- **Web模式**: `web_app.py` + `web_checker.py` - Streamlit Web界面
- **可执行程序**: PyInstaller打包的 `.exe` 文件

---

## PROJECT STRUCTURE

```
./
├── standard_checker.py    # CLI主程序 - 查询逻辑 + 命令行入口
├── web_app.py             # Web界面 - Streamlit应用
├── web_checker.py         # Web查询模块 - 适配Streamlit的查询器
├── requirements.txt       # 依赖列表
├── 标准查询工具.spec       # PyInstaller打包配置
├── start_web.sh           # Linux/macOS启动脚本
├── start_web.bat          # Windows启动脚本
└── standards.xlsx         # 示例输入数据文件
```

---

## BUILD / RUN / TEST COMMANDS

### 安装依赖
```bash
pip install -r requirements.txt
```

### CLI模式运行
```bash
# 查询单个标准
python standard_checker.py -s "GB 2757-2012"

# 批量查询（空格分隔）
python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"

# 更新Excel文件（推荐间隔3-5秒）
python standard_checker.py -f standards.xlsx -d 3.0

# 指定输出文件
python standard_checker.py -f input.xlsx -o output.xlsx

# 清除进度重新开始
python standard_checker.py -f standards.xlsx --clear-progress

# 使用代理
python standard_checker.py -f standards.xlsx --proxy http://127.0.0.1:7890
```

### Web模式运行
```bash
# Linux/macOS
./start_web.sh

# Windows
start_web.bat

# 或直接运行
streamlit run web_app.py
# 访问 http://localhost:8501
```

### 构建可执行程序（Windows）
```bash
# 安装打包工具
pip install pyinstaller

# 使用spec文件构建
pyinstaller "标准查询工具.spec"

# 或直接构建
pyinstaller --onefile --name "标准查询工具" standard_checker.py

# 输出位置: dist/标准查询工具.exe
```

### 代码检查（推荐）
```bash
# 类型检查（如已安装mypy）
mypy standard_checker.py web_checker.py

# 代码格式化（如已安装black）
black standard_checker.py web_checker.py web_app.py
```

---

## WHERE TO LOOK

| 任务 | 文件 | 位置/行号 |
|------|------|-----------|
| API配置 | standard_checker.py | L24-25, web_checker.py L19-20 |
| 核心查询类 | standard_checker.py | `StandardChecker` L107-391 |
| Web查询类 | web_checker.py | `WebStandardChecker` L89-323 |
| 进度跟踪器 | standard_checker.py | `ProgressTracker` L48-104 |
| CLI入口 | standard_checker.py | `main()` L481-581 |
| Excel处理 | standard_checker.py | `update_excel()` L394-478 |
| 状态映射 | standard_checker.py | `STATUS_MAP` L37-45 |
| User-Agent轮换 | standard_checker.py | `USER_AGENTS` L28-34 |
| Web界面 | web_app.py | `main()` L72-280 |

---

## CODE STYLE GUIDELINES

### 缩进与格式
- **缩进**: 2空格
- **行宽**: 无严格限制，保持可读性
- **编码声明**: 文件头部 `# -*- coding: utf-8 -*-`

### 命名规范
```python
# 类名: PascalCase
class StandardChecker:
class ProgressTracker:

# 函数名: snake_case
def query_single(standard_no):
def update_excel(input_file):

# 私有方法: 单下划线前缀
def _get_replacements(self, yf001):
def _update_headers(self):
def _calculate_wait_time(self, retry_count):

# 常量: 大写下划线
API_URL = "https://..."
STATUS_MAP = {...}
USER_AGENTS = [...]

# 变量: snake_case
standard_no = "GB 2757-2012"
retry_count = 0
```

### 注释规范
```python
# 使用Google风格docstring（中文）
def query_single(self, standard_no: str) -> Tuple[Optional[str], Optional[str], List[dict]]:
    """
    查询单个标准
    
    Args:
        standard_no: 标准号，如 "GB 2757-2012"
        
    Returns:
        tuple: (状态, 错误信息, 替代标准列表)
    """
```

### 类型注解
```python
from typing import Optional, Tuple, List, Dict, Callable

# 函数参数和返回值使用类型注解
def query_batch(
    self, 
    standard_nos: List[str], 
    tracker: Optional[ProgressTracker] = None,
    resume: bool = True
) -> List[dict]:
```

### 输出字段命名
- 使用中文命名输出字段: `标准号`, `状态`, `替代标准`
- Excel列名: `ndls状态`, `ndls查询时间`, `替代标准号`, `替代标准名`

---

## ERROR HANDLING

### 重试机制
- 最大重试次数: 可配置，默认5次
- 等待策略: 指数退避 + 随机抖动
- 限流检测: 检查API返回的 `message` 字段

```python
# 重试等待计算
def _calculate_wait_time(self, retry_count: int) -> float:
    base_wait = self.delay * (2 ** retry_count)
    jitter = random.uniform(0, 1)
    return base_wait + jitter
```

### 异常处理模式
```python
try:
    response = self.session.post(API_URL, json=data, timeout=15)
    # 处理响应...
except requests.exceptions.Timeout:
    # 超时处理
except requests.exceptions.RequestException as e:
    # 请求异常处理
except Exception as e:
    # 通用异常处理
```

---

## KEY COMPONENTS

### StandardChecker (CLI版)
```python
checker = StandardChecker(delay=3.0, max_retries=5, use_proxy=None)

# 核心方法
query_single(standard_no)     # 查询单个标准
query_batch(standard_nos)     # 批量查询，支持断点续传
_get_replacements(yf001)      # 获取替代标准列表
```

### WebStandardChecker (Web版)
```python
checker = WebStandardChecker(delay=3.0, max_retries=5, use_proxy=None)

# 支持回调的批量查询
query_batch_with_callback(
    standard_nos,
    progress_callback=lambda cur, total, msg: ...,
    log_callback=lambda msg: ...
)
```

### ProgressTracker
```python
tracker = ProgressTracker(progress_file=".query_progress.pkl")

# 方法
tracker.mark_completed(standard_no)   # 标记完成
tracker.mark_failed(standard_no, err) # 标记失败
tracker.is_completed(standard_no)     # 检查是否完成
tracker.clear()                        # 清除进度
```

---

## API ENDPOINTS

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/standard/list` | POST | 搜索标准，参数 `a100` (标准号) |
| `/api/standard/detail/{yf001}` | GET | 获取标准详情，返回替代关系 |

### 响应字段映射
- `a000`: 标准状态
- `a100`: 标准号
- `a298`: 标准名称
- `yf001`: 内部ID（用于查询详情）
- `a461list`: 替代标准列表

---

## IMPORTANT NOTES

1. **Excel文件要求**: 必须包含 `标准号` 列
2. **查询间隔**: 建议3-5秒，避免触发限流
3. **断点续传**: 进度保存在 `.progress.pkl` 文件
4. **User-Agent轮换**: 每次重试自动更换UA
5. **代理支持**: 通过 `--proxy` 参数或 `use_proxy` 参数配置
6. **yf001**: ndls.org.cn内部标准ID，用于获取替代关系
7. **被代替标准**: 会额外查询替代标准的名称

---

## DEPENDENCIES

```
streamlit>=1.28.0    # Web界面
pandas>=2.0.0        # Excel处理
requests>=2.31.0     # HTTP请求
openpyxl>=3.1.0      # Excel读写
xlsxwriter>=3.1.0    # Excel写入
```

---

## CONVENTIONS SUMMARY

| 类别 | 规范 |
|------|------|
| 缩进 | 2空格 |
| 类名 | PascalCase |
| 函数名 | snake_case |
| 私有方法 | `_leading_underscore` |
| 常量 | UPPER_SNAKE_CASE |
| 变量 | snake_case |
| 注释 | Google风格 docstring（中文） |
| 类型注解 | 使用 `typing` 模块 |
| 输出字段 | 中文命名 |