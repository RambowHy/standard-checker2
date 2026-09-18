# AGENTS.md

查询国家标准在 ndls.org.cn 的状态及替代关系。Python 3.11+，CLI（argparse + pandas）+ Streamlit Web 两种入口，共用核心模块。

## 架构（v3.0 重构后的关键事实）

- `core.py` 是唯一应放公共逻辑的地方：常量（`API_URL`/`DETAIL_URL`/`STATUS_MAP`/`USER_AGENTS`）、数据模型（`StandardResult`/`ReplacementStandard`/`QueryStats`）、`ProgressTracker`、`BaseStandardChecker`（含 `query_single` 重试与限流逻辑）。
- `standard_checker.py`：`StandardChecker(BaseStandardChecker)`，CLI 专属的 `query_batch` / `update_excel` / argparse `main()`。
- `web_checker.py`：`WebStandardChecker(BaseStandardChecker)`，仅增加带回调的 `query_batch_with_callback`。
- `web_app.py`：Streamlit 界面，不写查询逻辑。
- 改查询行为时改 `core.py`，两个入口自动生效；不要在子类里复制请求/重试代码。
- `StandardResult` 等 dataclass 的字段名是**故意用中文**（`标准号`/`状态`/`错误`/`替代标准`），Excel 输出列依赖这些名字，不要改成英文。

## 命令

```bash
pip install -r requirements.txt

# 测试（unittest，无 pytest 配置；34 个测试全部 mock 网络，不访问真实 API）
python -m unittest test_core -v
python -m unittest test_core.TestBaseStandardChecker.test_query_single_success  # 单个

# CLI
python standard_checker.py -s "GB 2757-2012"                       # 单个/多个（空格分隔）
python standard_checker.py -f input.xlsx -d 3.0                    # 更新 Excel，默认覆盖原文件
python standard_checker.py -f input.xlsx -o out.xlsx --clear-progress
python standard_checker.py -f input.xlsx --proxy http://127.0.0.1:7890

# Web（0.0.0.0:8501，headless，见 .streamlit/config.toml）
./start_web.sh        # 或 streamlit run web_app.py
```

- 无 lint / typecheck / formatter 配置（mypy、black 未纳入项目，勿声称已通过）。
- 缩进统一 **2 空格**（非 Python 默认的 4 空格），文件头保留 `# -*- coding: utf-8 -*-`。

## 测试约定

- 所有 HTTP 调用必须用 `unittest.mock` patch（`session.post`/`session.get`/`core.time.sleep`），测试中 `delay=0`。
- Excel 相关测试在 `tempfile` 目录生成真实 xlsx 读写，tearDown 清理。

## Excel 契约

- 输入必须有 `标准号` 列；自动补齐输出列：`ndls状态`、`ndls查询时间`、`替代标准号`、`替代标准名`。
- `*.xlsx`、`*.xls`、`*.pkl` 均已在 `.gitignore`，仓库中没有也不要提交样例数据文件。

## 断点续传（容易踩坑）

- CLI 进度文件按输入文件命名：`<input.xlsx>.progress.pkl`（在 `update_excel` 内拼接，非默认构造参数）；Web 固定用 `.web_query_progress.pkl`（所有上传文件共享一份）。
- pickle 内含 `PROGRESS_VERSION`（core.py），版本不兼容或文件损坏时自动删除并从头开始，不报错中断。
- 全部完成后进度文件自动清理；`--clear-progress` / Web「重置进度」手动清理。

## ndls.org.cn API 契约

- `POST /api/standard/list`，body `{"a100": 标准号, "page": 1, "limit": 10}`；`code != 0` 且 message 含「限流」或「验证码」时按指数退避（`delay * 2**retry_count + 随机抖动`）重试，默认间隔 3s、最多 5 次；其他错误不重试。
- `GET /api/standard/detail/{yf001}`：仅当状态为「被代替」时调用；`a461list` 元素形如「被GB 2716-2018代替」，需正则提取标准号，再逐个查名称。
- 响应字段：`a000` 状态原文（经 `STATUS_MAP` 转中文展示）、`a100` 标准号、`a298` 标准名、`yf001` 详情 ID。
- 请求需带 `Origin/Referer: https://www.ndls.org.cn`，重试时轮换 User-Agent。
