# 国家标准状态查询工具

查询国家标准在 [ndls.org.cn](https://www.ndls.org.cn) 的现行有效性及替代信息，提供 CLI 命令行和 Streamlit Web 两种使用方式。

- 支持单条 / 批量标准号查询
- 直接读写 Excel，自动补全状态与替代标准列
- 「被代替」标准自动追踪替代标准的编号和名称
- 断点续传：中断后重新运行自动跳过已完成条目
- 限流 / 验证码自动指数退避重试，重试时轮换 User-Agent
- 支持 HTTP 代理

## 环境要求

- Python 3.11+

```bash
pip install -r requirements.txt
```

## CLI 模式

```bash
# 查询单个标准
python standard_checker.py -s "GB 2757-2012"

# 批量查询（空格分隔）
python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"

# 更新 Excel 文件（默认覆盖原文件，建议间隔 3-5 秒）
python standard_checker.py -f input.xlsx -d 3.0

# 输出到新文件
python standard_checker.py -f input.xlsx -o output.xlsx

# 清除断点进度，从头查询
python standard_checker.py -f input.xlsx --clear-progress

# 使用代理
python standard_checker.py -f input.xlsx --proxy http://127.0.0.1:7890
```

参数说明：

| 参数 | 说明 |
|------|------|
| `-s, --standards` | 要查询的标准号，空格分隔 |
| `-f, --file` | 待更新的 Excel 文件 |
| `-o, --output` | 输出文件路径，默认覆盖原文件 |
| `-d, --delay` | 查询间隔（秒），默认 3.0，建议 3-5 |
| `--proxy` | 代理地址 |
| `--clear-progress` | 清除进度后重新开始 |
| `--no-resume` | 禁用断点续传（默认启用） |

## Web 模式

```bash
# Linux / macOS
./start_web.sh

# Windows
start_web.bat

# 或直接运行
streamlit run web_app.py
```

启动后访问 http://localhost:8501（监听 0.0.0.0，局域网可访问）。在侧边栏设置查询间隔、重试次数和代理，上传 Excel 后点击「开始查询」，可查看实时进度和日志，完成后一键下载结果文件。

## Excel 文件格式

输入文件必须包含名为 `标准号` 的列，其他列保持不变：

| 标准号 | 其他列... |
|--------|-----------|
| GB 2757-2012 | ... |
| GB/T 8170-2008 | ... |

程序会自动补齐以下输出列：

- `ndls状态`：查询到的状态
- `ndls查询时间`：查询时间戳
- `替代标准号`：替代标准编号（多个以逗号分隔）
- `替代标准名`：替代标准名称

支持 `.xlsx` 和 `.xls` 格式。

## 状态说明

接口返回的原始状态经映射后展示为：现行有效、已作废、已废止、已被代替、已修订、历史标准、未生效；查不到的条目标记为「未找到」。

## 断点续传

- CLI 模式进度文件按输入文件命名：`<输入文件>.progress.pkl`
- Web 模式固定使用 `.web_query_progress.pkl`
- 全部条目查询完成后进度文件自动清理；中断后重新运行即从断点继续

## 限流与重试

查询间隔建议保持 3-5 秒。接口返回限流或验证码提示时，按 `间隔 × 2^重试次数 + 随机抖动` 指数退避，默认最多重试 5 次。

## 项目结构

| 文件 | 职责 |
|------|------|
| `core.py` | 公共核心：API 常量、数据模型、进度跟踪器、查询器基类（请求 / 重试 / 替代关系查询） |
| `standard_checker.py` | CLI 入口：批量查询、Excel 更新、argparse |
| `web_checker.py` | Web 查询器：在基类上增加进度 / 日志回调 |
| `web_app.py` | Streamlit 界面 |
| `test_core.py` | 单元测试（全部 mock 网络，不访问真实 API） |

修改查询逻辑只需改 `core.py`，CLI 和 Web 两个入口同时生效。

## 运行测试

```bash
python -m unittest test_core -v
```

## 依赖

- streamlit
- pandas
- requests
- openpyxl
