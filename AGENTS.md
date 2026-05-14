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

## Parallel Agent Rules

- 可以并行调用多个 agent 处理无依赖、无写入冲突的任务，例如：不同来源的只读调研、不同学校/年份的审计、不同配置文件的独立检查、互不重叠的测试验证。
- 并行前必须明确每个 agent 的目标、输入文件、允许修改范围、禁止修改范围和交付格式；涉及代码修改时优先划分互不重叠的文件所有权。
- 不把当前关键路径的下一步阻塞任务交给后台 agent 等待；主执行者应继续推进本地可做且不重叠的工作。
- 不允许多个 agent 同时编辑同一文件、同一配置段、同一 raw/staging/export 产物、同一个 review batch 或同一个目标表发布链路；这类任务必须串行。
- worker agent 必须知道自己不是唯一操作者，不得回滚他人改动；交付时列出改动文件、验证命令、未验证项和残留风险。
- explorer agent 用于具体代码库问题或来源结构问题；不要重复派发相同探索任务。
- 合并并行结果前必须重新检查 `git status -sb`、diff、manifest/quality report、readiness/audit 报告和必要测试；并行完成不等于可以跳过 DataHub 门禁。
