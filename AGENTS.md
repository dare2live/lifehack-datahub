# Agent Rules

- 不提交 Excel、CSV、Parquet、DuckDB、SQLite、下载缓存或任何原始数据文件。
- 不写 `/Users/dp/Documents/M/stock/chunky-monkey-v2/data/smartmoney.duckdb`。
- 不 import ChunkyMonkey 项目模块。
- 输出给 core 的表名必须使用 `fa_` 前缀。
- 数据包必须包含 `manifest.json` 和 `quality_report.json`。
- 任何 connector 只负责获取原始材料；字段清洗进入 normalizers，质量判断进入 validators，导出进入 exporters。
- 可配置的数据源 URL、文件名、字段别名、年份参数放在 `config/`，不要硬编码到业务逻辑。
- 项目整体按“最小模块化”管理：各类事实、指标、映射、评分和中间结果优先进入 `fa_` 数据表；来源、字段别名、阈值、权重、评分档案、采集批次、审计规则和导出参数优先进入 `config/`；代码只保留读取配置、校验、编排流程和可复用加工机制。新增能力先复用已有 schema、config、builder、validator 和 package exporter，避免为单个来源或页面写散落逻辑。
- 数据更新必须先经过 `config/data_update_policy.json` 生成计划：非标数据走 raw/candidate/review/approved/published 晋级；旧数据覆盖走分区替换、主键 upsert 或已复核 delete plan；并发只允许发生在无依赖且同配置允许的来源之间。
- 正式采集前先跑 `audit-data-update-policy` 和 `build-data-update-readiness-plan`；URL/hash/API/schema/证据摘录/指标注册/lineage/旧数据处理策略必须形成可审计检查行，阻断项未清零时不得发布 data package。
- core importer `--dry-run` 只验证包能否被当前 core schema 和 load mode 接受，不代表来源证据、人工复核或 reconciliation readiness 已完成；影响推荐结果的数据包必须先通过 DataHub 业务门禁再导入。
- 面向家庭可见的屏幕、报告和说明文本必须使用客观描述，避免内部岗位称谓、口播提示、操作者视角和命令式执行提示。
