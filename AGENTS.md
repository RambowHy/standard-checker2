# 国家标准状态查询工具 - AGENTS.md

**Generated:** 2026-02-12  
**Stack:** Python + pandas + requests

## OVERVIEW
查询国家标准在 ndls.org.cn 的现行有效性及替代信息。支持单条/批量查询和 Excel 自动更新。

## STRUCTURE
```
./
├── standard_checker.py    # 主程序 - 查询逻辑 + CLI
└── standards.xlsx         # 输入数据文件
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| API配置 | L19-25 | API_URL, DETAIL_URL, HEADERS |
| 核心类 | L39-187 | `StandardChecker` - 查询核心逻辑 |
| CLI入口 | L249-317 | `main()` + argparse 参数解析 |
| Excel处理 | L190-246 | `update_excel()` - 文件读写 |
| 状态映射 | L28-36 | STATUS_MAP - API状态转友好名称 |

## KEY COMPONENTS

### StandardChecker
```python
query_single(standard_no)   # 查询单个标准
query_batch(standard_nos)   # 批量查询
_get_replacements(yf001)    # 获取替代标准列表
```

### API Endpoints
- `POST /api/standard/list` - 搜索标准
- `GET /api/standard/detail/{yf001}` - 获取标准详情

## CONVENTIONS
- 类名: `PascalCase`
- 函数: `snake_case`
- 私有方法: `_leading_underscore`
- 注释: Google风格 docstring
- 输出字段: 中文命名 (`标准号`, `状态`, `替代标准`)

## USAGE
```bash
# 查询单个标准
python standard_checker.py -s "GB 2757-2012"

# 批量查询
python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"

# 更新Excel
python standard_checker.py -f standards.xlsx -o output.xlsx

# 调整查询间隔（秒）
python standard_checker.py -s "GB 1234" -d 1.0
```

## DEPENDENCIES
```bash
pip install pandas requests openpyxl
```

## NOTES
- Excel必须包含 `标准号` 列
- API调用有 `delay` 间隔（默认0.5s），避免请求过快
- 结果被代替的标准会额外查询替代标准详情
- yf001 是 ndls.org.cn 内部标准ID，用于获取替代关系
- 查询结果写入列：`ndls状态`, `ndls查询时间`, `替代标准号`, `替代标准名`
