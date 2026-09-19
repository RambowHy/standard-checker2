# AGENTS.md

查询国家标准在 ndls.org.cn 的状态及替代关系。Python 3.11+，CLI（argparse + pandas）+ Streamlit Web 两种入口，共用核心模块。

## 架构（v3.0 重构后的关键事实）

- `core.py` 是唯一应放公共逻辑的地方：常量（`API_URL`/`DETAIL_URL`/`STATUS_MAP`/`USER_AGENTS`）、数据模型（`StandardResult`/`ReplacementStandard`/`QueryStats`）、`normalize_standard_nos`（strip + 保序去重）、`ProgressTracker`、`BaseStandardChecker`（含 `query_single` 重试与限流逻辑）。
- `standard_checker.py`：`StandardChecker(BaseStandardChecker)`，CLI 专属的 `query_batch` / `update_excel`（临时文件 + `os.replace` 原子写）/ argparse `main()`。
- `web_checker.py`：`WebStandardChecker(BaseStandardChecker)`，仅增加带回调和 `should_stop` 取消支持的 `query_batch_with_callback`。
- `web_app.py`：Streamlit 界面，不写查询逻辑；查询在 daemon 线程中跑，`@st.fragment(run_every=1.0)` 轮询 job 状态并渲染进度/取消按钮/结果（需要 streamlit>=1.37）。
- 改查询行为时改 `core.py`，两个入口自动生效；不要在子类里复制请求/重试代码。
- `StandardResult` 等 dataclass 的字段名是**故意用中文**（`标准号`/`状态`/`错误`/`替代标准`），Excel 输出列依赖这些名字，不要改成英文。

## 命令

```bash
pip install -r requirements.txt

# 测试（unittest，无 pytest 配置；42 个测试全部 mock 网络，不访问真实 API）
python -m unittest test_core -v
python -m unittest test_core.TestBaseStandardChecker.test_query_single_success  # 单个

# CLI
python standard_checker.py -s "GB 2757-2012"                       # 单个/多个（空格分隔）
python standard_checker.py -f input.xlsx -d 5.0                    # 更新 Excel，默认覆盖原文件
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
- 标准号经 `normalize_standard_nos` strip + 去重后查询；回填用 `df['标准号'].isin(result_map)` 匹配，重复行全部回填，不能只填 `index[0]`。
- 写 Excel 必须走 `tempfile` + `os.replace` 原子替换（覆盖原文件时避免损坏）。
- `*.xlsx`、`*.xls`、`*.pkl` 均已在 `.gitignore`，仓库中没有也不要提交样例数据文件。

## 断点续传（容易踩坑）

- 进度 pickle（`PROGRESS_VERSION=2`，core.py）存的是 `{标准号: StandardResult}` 查询结果，不只是标准号；续跑时已完成条目必须从 tracker 取回结果回填（`get_result`），不能只返回本轮新查的结果。版本不兼容或文件损坏时自动删除并从头开始。
- 只有成功结果写入 tracker（失败条目不持久化，下次运行自动重试）。
- CLI 进度文件按输入文件命名：`<input.xlsx>.progress.pkl`（在 `update_excel` 内拼接）；Web 按上传文件内容 md5 命名 `.web_query_progress_<hash>.pkl`，经 `WebStandardChecker(progress_file=...)` 注入，不同文件互不干扰。
- 全部完成后进度文件自动清理；`--clear-progress` / Web「重置进度」手动清理（无 checker 时 `ProgressTracker(...).clear()` 直接删文件）。

## ndls.org.cn API 契约

- `POST /api/standard/list`，body `{"a100": 标准号, "page": 1, "limit": 10}`；重试分两类：限流（message 含「限流」/「验证码」、HTTP 429）走**长冷却** `RATE_LIMIT_COOLDOWN*2^n`（60/120/180s，封顶 180，±20% 抖动）；5xx/超时/连接异常走短退避（`delay*2^n`）；4xx（非 429）立即失败。冷却/等待统一走 `_interruptible_sleep`（1 秒分片，支持取消）。
- 批量编排在基类 `_run_recovery_batch`（返回 `BatchOutcome{results,failures,rate_limited,cancelled}`）：限流失败先跳过、连续 3 条熔断（`CONSECUTIVE_RATE_LIMIT_BREAK`）、本轮结束等 60s（`RECOVERY_ROUND_WAIT`）对限流条目补查一次；最终限流失败错误固定为 `RATE_LIMIT_FAIL_MSG`，写回 Excel 状态列。CLI/Web 都委托该方法，勿在子类另写循环。
- 批量循环把 `sleep_after=(i < total)` 传给 `query_single`，最后一条不再 sleep；成功后的间隔走 `_random_delay()`：`delay*(1±jitter_ratio)`，构造参数 `jitter_ratio` 默认 0.5（实际约 0.5–1.5 倍 delay），设 0 为固定间隔。HTTP 超时由构造参数 `timeout` 控制（默认 15s）。
- `GET /api/standard/detail/{yf001}`：仅当状态属于 `REPLACEMENT_STATUSES`（被代替/作废/废止/已修订）时调用（作废状态也会带替代关系）；`a461list` 元素可能是「被GB 2716-2018代替」或纯标准号「GB/T 31114-2024」两种格式，正则提取时纯号需原样保留，再逐个查名称。现行状态不查详情（其 a461list 是关联引用，不是代替关系）。
- 响应字段：`a000` 状态原文（经 `STATUS_MAP` 转中文展示）、`a100` 标准号、`a298` 标准名、`yf001` 详情 ID。
- 请求需带 `Origin/Referer: https://www.ndls.org.cn`，重试时轮换 User-Agent。
