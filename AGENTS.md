# Agent Rules

- 不提交 Excel、CSV、Parquet、DuckDB、SQLite、下载缓存或任何原始数据文件。
- 不写 `/Users/dp/Documents/M/stock/chunky-monkey-v2/data/smartmoney.duckdb`。
- 不 import ChunkyMonkey 项目模块。
- 输出给 core 的表名必须使用 `fa_` 前缀。
- 数据包必须包含 `manifest.json` 和 `quality_report.json`。
- 任何 connector 只负责获取原始材料；字段清洗进入 normalizers，质量判断进入 validators，导出进入 exporters。
- 可配置的数据源 URL、文件名、字段别名、年份参数放在 `config/`，不要硬编码到业务逻辑。
- 面向家庭可见的屏幕、报告和说明文本必须使用客观描述，避免内部岗位称谓、口播提示、操作者视角和命令式执行提示。
