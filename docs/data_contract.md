# Data Package Contract

DataHub 向 core 发布的是不可变数据包。

## manifest.json

字段：

- `package_id`
- `built_at`
- `source_version`
- `source_lineage`（可选，来自 `_intake_manifest.json` 的受控手工来源链路）
- `tables`
- `files`
- `hashes`
- `quality_report`

## quality_report.json

字段：

- `row_counts`
- `primary_key_checks`
- `null_checks`
- `year_coverage`
- `warnings`
- `errors`

## 表命名

所有 core 可导入表必须使用 `fa_` 前缀。

## 本地清洗文件入口

DataHub 可以从本地已清洗 CSV/TSV/XLSX 生成 data package，但原始文件不进入 Git。

示例：

```bash
python3 scripts/build_package.py build-local \
  --source-key ln_admission_plan \
  --table fa_dim_ln_admission_plan \
  --input raw/ln_admission_plan/2026_cleaned.csv \
  --output-root exports \
  --package-id 2026_ln_admission_plan \
  --intake-manifest raw/ln_admission_plan/2026-06-20/_intake_manifest.json
```

字段别名、主键、必填列和数字列维护在 `config/source_schemas.json`。

### 本地报考工作簿解析

本地已清洗“报考数据”工作簿通常不是目标表结构，而是多个 sheet 混合招生计划、学校/专业增强字段，以及 2022-2025 历史最低分/位次。DataHub 用 `config/ln_application_workbook.json` 维护 sheet 选择、批次、科类、字段别名、年份列和重复主键策略，再输出标准 cleaned CSV：

```bash
python3 scripts/build_package.py parse-ln-application-workbook \
  --input "/Users/dp/Documents/M/lifehack/26年报考数据/26年本科批报考数据8.27.xlsx" \
  --plan-output cleaned/ln_application_workbook_plan.csv \
  --score-output cleaned/ln_application_workbook_score_history.csv \
  --report cleaned/ln_application_workbook_report.json
```

该入口只读 Excel，输出 `fa_dim_ln_admission_plan` 与 `fa_fact_ln_score_history` 两张 cleaned CSV 及解析报告，不生成 data package、不写 core。确认 `duplicate_counts` 和 `ignored_sheets` 后，再用 `build-local` 进入数据包契约。默认配置只接收普通类本科批 `物理类/历史类` sheet，特殊类型、提前批、艺术/体育/专科需增加 profile 或 sheet rule 后再解析，避免把不同录取规则混进同一批次。

真实 smoke：`26年本科批报考数据8.27.xlsx` 已先通过 `intake-manual --source-key ln_application_workbook` 登记到 ignored raw 区，`_intake_manifest.json` 记录本地原文件 SHA-256、来源说明、证据链接和采集人；再从 raw 副本解析出 14,196 条招生计划、46,597 条历史分数/位次。随后分别用 `build-local --source-key ln_admission_plan` 和 `build-local --source-key ln_score_history` 携带同一 intake manifest 生成 `2026_ln_application_workbook_plan_intake` 与 `2026_ln_application_workbook_score_history_intake` 包，两个包 manifest 校验无错误，并已通过 core importer `--dry-run`。Excel、cleaned CSV、raw 和 exports 均为本地 ignored 产物，不进入 Git。

招生计划包进入实际 core 之前必须先做只读对账。`audit-admission-plan-package-against-core` 按 `config/source_schemas.json` 中 `fa_dim_ln_admission_plan.audit` 的 scope 和 compare 列输出匹配、package-only、core-only、字段差异与样本；它不导入、不删除、不修改 `university.db`：

```bash
python3 scripts/build_package.py audit-admission-plan-package-against-core \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --package-dir exports/2026_ln_admission_plan \
  --report audits/admission_plan_2026_against_core.json
```

审计后如仍需人工判断，使用 `build-admission-plan-reconciliation-plan` 生成本地 review plan。它只把审计差异转成 `value_drift/package_only_unmatched/core_only_unmatched` 任务，状态、优先级和建议动作来自 `config/source_schemas.json`，不能作为数据包导入 core：

```bash
python3 scripts/build_package.py build-admission-plan-reconciliation-plan \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --package-dir exports/2026_ln_admission_plan \
  --output-dir staging/admission_plan_reconciliation_2026
```

复核推进时使用 `audit-admission-plan-reconciliation-plan` 看进度，用 `build-admission-plan-reconciliation-review-batch` 拆出小批次，再用 `merge-admission-plan-reconciliation-review-batch` 合并回总计划。合并时只回写 `config/source_schemas.json` 中 `batch_editable_columns` 指定的复核列，不允许批次修改主键、学校、专业或计划数：

```bash
python3 scripts/build_package.py audit-admission-plan-reconciliation-plan \
  --plan-csv staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan.csv \
  --report staging/admission_plan_reconciliation_2026/readiness_report.json

python3 scripts/build_package.py build-admission-plan-reconciliation-review-batch \
  --plan-csv staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan.csv \
  --output-dir staging/admission_plan_reconciliation_2026/review_batch_initial \
  --limit-per-issue 20

python3 scripts/build_package.py merge-admission-plan-reconciliation-review-batch \
  --plan-csv staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan.csv \
  --batch-csv staging/admission_plan_reconciliation_2026/review_batch_initial/admission_plan_reconciliation_review_batch.csv \
  --output staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan_merged.csv
```

core-backed `exclude_row` 不进入普通 data package，而是单独生成删除迁移计划。该命令要求完整 plan 已复核完成，只输出待删除主键 CSV/JSON，不执行 SQL，不写 core，不是 data package：

```bash
python3 scripts/build_package.py build-admission-plan-delete-plan \
  --plan-csv staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan_merged.csv \
  --output-dir staging/admission_plan_reconciliation_2026/delete_plan
```

### 招生计划过渡包

`ln_admission_plan` 的完整官方分发目前是志愿填报系统和《辽宁招生考试》杂志，公开站点没有稳定完整附件。为了让 core 里现有清洗数据也进入 DataHub 包链路，可先生成过渡 snapshot：

```bash
python3 scripts/build_package.py build-admission-plan-snapshot \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-root exports \
  --package-id legacy_ln_admission_plan_snapshot
```

该包只读 core，输出 `fa_dim_ln_admission_plan` 标准 data package，并在 `quality_report.warnings` 和 `manifest.source_lineage` 中标注 `legacy_core_snapshot`。它不能替代后续带 intake manifest 的官方导出文件。

## 远程文件下载入口

先用 source audit 看清楚每个数据源的获取状态：

```bash
python3 scripts/build_package.py audit-sources
```

`config/sources.json` 的每个 source 可以维护 `remote_files`：

```json
{
  "url": "https://example.com/file.xlsx",
  "file_name": "2026.xlsx",
  "source_date": "2026-05-13",
  "sha256": "optional"
}
```

下载命令只把文件写入 raw 目录，不解析、不导入 core：

```bash
python3 scripts/build_package.py download --source-key ln_admission_plan --output-root raw
```

下载完成后，DataHub 会在每个 `raw/{source_key}/{source_date}/` 目录生成 `_remote_manifest.json`，字段兼容 `build-local --intake-manifest`。这样由远程稳定来源解析出的 cleaned CSV 也能把原始 URL、SHA-256、文件大小、来源说明和目标表写进 package lineage。

## 候选来源探测入口

尚未稳定到可配置为 `remote_files` 的 URL 必须先放在 `research_candidates`。探测命令只检查候选 URL 的可访问性、HTTP 状态、文件大小和 SHA-256，不写 raw，也不晋级来源：

```bash
python3 scripts/build_package.py probe-source-candidates \
  --source-key ln_projection_score \
  --output staging/source_research/ln_projection_score_candidates.json
```

候选来源晋级为 `remote_files` 前必须满足：

- 来源页面或附件可重复访问。
- 下载物有稳定 SHA-256。
- 来源说明能区分官方原始来源、官方转载、第三方镜像。
- 已有 source-specific parser 或受控人工 intake 流程。

## 受控手工文件入口

对 `manual_required`、`source_collection_required`、`curation_required`、`curated_seed_configured`、`research_required` 状态的数据源，DataHub 使用 `intake-manual` 登记原始文件。它只复制文件到 raw 区并写入 `_intake_manifest.json`，记录采集人、来源说明、证据链接、文件大小和 SHA-256；不解析文件，不导入 core，也不允许把 raw 文件提交到 Git。

示例：

```bash
python3 scripts/build_package.py intake-manual \
  --source-key ln_admission_plan \
  --input ~/Downloads/2026_liaoning_plan.xlsx \
  --output-root raw \
  --source-date 2026-06-20 \
  --acquired-by data_reviewer \
  --official-distribution 网报志愿系统 \
  --evidence-url https://jyt.ln.gov.cn/jyt/jyzx/jyyw/2025062010482638109/index.shtml \
  --notes "从官方志愿系统导出，未人工改列名"
```

教育部本科专业目录 PDF 通过 source-specific parser 生成 `fa_dim_major_catalog` 清洗 CSV：

```bash
python3 scripts/build_package.py parse-moe-major-catalog \
  --input raw/moe_major_catalog/2025-04-22/moe_major_catalog_2025.pdf \
  --output cleaned/moe_major_catalog_2025.csv
```

辽宁本科批投档最低分官方 XLSX 通过 source-specific parser 生成 `fa_fact_ln_projection_score` 清洗 CSV。官方附件是 Office 加密容器，parser 需要显式传入配置中维护的候选密码：

```bash
python3 scripts/build_package.py parse-ln-projection-score \
  --input raw/ln_projection_score/2025-07-20/ln_projection_score_2025_history.xlsx \
  --input raw/ln_projection_score/2025-07-20/ln_projection_score_2025_physics.xlsx \
  --output cleaned/ln_projection_score_2025.csv \
  --score-year 2025 \
  --batch 本科批 \
  --source-date 2025-07-20 \
  --password VelvetSweatshop
```

`ln_projection_score` 当前配置覆盖 2023-2025 辽宁招生考试之窗附件。2023 附件通过辽宁招生考试之窗官方页面 `IMS_20230720_42967_xuHWw7pSO3.htm` 反查得到，HTTP 200、Excel 文件类型和 SHA-256 均已核验。

## 辽宁成绩统计表与历史位次派生

`ln_score_distribution` 维护辽宁官方普通高考成绩统计表（一分一段）附件。2025 年普通类历史/物理 PDF 可直接解析为 `fa_fact_ln_score_distribution`：

```bash
python3 scripts/build_package.py parse-ln-score-distribution \
  --input raw/ln_score_distribution/2025-06-24/ln_score_distribution_2025_history.pdf \
  --input raw/ln_score_distribution/2025-06-24/ln_score_distribution_2025_physics.pdf \
  --output cleaned/ln_score_distribution_2025.csv \
  --score-year 2025 \
  --source-date 2025-06-24
```

投档最低分本身不包含最低位次。DataHub 用官方投档最低分 + 官方一分一段累计人数，派生 `fa_fact_ln_score_history.min_rank`：

```bash
python3 scripts/build_package.py build-score-history-from-projection \
  --projection cleaned/ln_projection_score_2025.csv \
  --score-distribution cleaned/ln_score_distribution_2025.csv \
  --output-root exports \
  --package-id 2025_ln_score_history_derived
```

注意：派生的 `min_rank` 是最低分对应的一分一段累计人数，不是同分排序后的精确投档位次。`quality_report.warnings` 会保留 `rank_is_score_cumulative_rank`。2023/2024 已补充转载 PDF 镜像，登记为 `mirror_pdf`，可文本解析但不能冒充辽宁官网原始长期来源；真实 smoke 已解析 2023 年 1,076 行、2024 年 1,086 行 `fa_fact_ln_score_distribution` 并通过质量闸门。2022 已补充辽宁招生考试之窗官方图片页，`parse_mode=grid_image_table` 可生成 `fa_fact_ln_score_distribution` 标准包；中新网辽宁转载图片页保留为兜底镜像候选源。

真实派生 smoke：2023 投档最低分 14,435 行 + 2023 一分一段 PDF 镜像 1,076 行，生成 14,435 行 `fa_fact_ln_score_history`，unmatched=0、质量错误为空；2024 投档最低分 14,298 行 + 2024 一分一段 PDF 镜像 1,086 行，生成 14,298 行，unmatched=0、质量错误为空。core importer 修复 `upsert_or_replace_package` 后，连续导入 2023/2024 两个数据包的临时库同时保留两年数据，且 `min_rank` 无空值。

2022 官方派生 smoke：辽宁招生考试之窗 2022 历史类/物理类投档最低分官方附件解析 14,203 行，叠加 2022 官方图片表格一分一段，生成 `2022_ln_score_history_derived_official_projection_grid` 标准包，`fa_fact_ln_score_history` 14,203 行，unmatched=0、quality report 无错误，manifest 校验和 core importer `--dry-run` 均通过。导入实际 core 前必须先对账：当前 package-vs-core 审计显示 `safe_to_import_without_reconciliation=false`，因为 2022 本科批普通类存在专业代码漂移、package-only/core-only 和分数位次差异；已生成 16,963 行 reconciliation plan，未复核时构建可导入包和 delete plan 都会被拒绝。

实际 core 库导入前先运行 package-vs-core 对账，避免不同来源或院校/专业代码体系的派生包直接覆盖工作库。对账主键、作用域列、对比列和 sample limit 均由 `config/source_schemas.json` 维护：

```bash
python3 scripts/build_package.py audit-score-history-package-against-core \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2023_ln_score_history_derived_pdf_mirror \
  --package-dir exports/2024_ln_score_history_derived_pdf_mirror \
  --report audits/score_history_2023_2024_against_core.json
```

该命令只读 core DB。报告中 `decision.reconciliation_required=true` 时，先处理 `different_rows`、`package_only_rows`、`core_only_rows` 的来源和代码差异，再决定导入策略。报告会额外输出 `reconciliation_hints.same_values_different_key_candidates`，用配置化匹配列识别“同校同年同分同位次但专业代码不同”的疑似代码漂移。

对账后生成可复核任务表：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-plan \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2023_ln_score_history_derived_pdf_mirror \
  --package-dir exports/2024_ln_score_history_derived_pdf_mirror \
  --output-dir staging/score_history_reconciliation_2023_2024
```

输出 `score_history_reconciliation_plan.csv/json`。CSV 任务类型包括 `major_code_drift_candidate`、`value_drift`、`package_only_unmatched`、`core_only_unmatched`、`core_only_zero_placeholder`；任务状态、优先级、建议动作、匹配置信度和 0 分/0 位次占位识别均由 `config/source_schemas.json` 维护。它是人工复核计划，不是 data package，不能导入 core。

复核推进中用 readiness audit 做门禁：

```bash
python3 scripts/build_package.py audit-score-history-reconciliation-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --report staging/score_history_reconciliation_2023_2024/readiness_report.json
```

审计会校验任务列、任务 ID、issue type、状态、review decision、JSON 字段和 ready 状态必填列。只有 `ready.package_ready=true` 时，后续才可以进入可导入 package 构建；当前真实 2023/2024 队列仍是 `todo=24,478`，`package_ready=false`。

配置明确的低风险任务可以先应用自动复核规则。规则维护在 `config/source_schemas.json.audit.reconciliation.review.auto_decision_rules`，当前覆盖 core 侧 `min_score/min_rank` 均为 0 的 `core_only_zero_placeholder`、能被官方参考包精确佐证的 package/core 单侧行和值差异，以及“官方 package 行精确匹配且只有一个 core 候选”的专业代码漂移。输出仍是 review plan，不会写库：

```bash
python3 scripts/build_package.py apply-score-history-reconciliation-auto-decisions \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --output staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_auto.csv \
  --report staging/score_history_reconciliation_2023_2024/auto_decision_report.json
```

真实 smoke：对本地报考工作簿历史分数 reconciliation plan 应用 `core_zero_placeholder_to_delete_plan`，10,461 条任务中 10,184 条 `core_only_zero_placeholder` 自动标为 `reviewed/exclude_row`，其余 277 条非占位差异仍为 `todo`；readiness audit 无错误但 `package_ready=false`，因此不会越过后续复核和写库门禁。再传入 2025 官方派生包作为 `--reference-package-dir` 后，276 条 `core_only_unmatched` 被官方参考包确认并标为 `keep_core_row`，1 条 `package_only_unmatched` 标为 `use_package_row`，readiness 变为 `package_ready=true`。

含删除决策的 reviewed plan 必须拆成两个产物。`build-score-history-from-reconciliation-plan --allow-core-exclude-rows` 只生成非删除行的数据包；`build-score-history-delete-plan` 只生成 core-backed `exclude_row` 删除候选。真实 run 已生成 277 行补丁包并通过 core importer `--dry-run` 后实际导入，同时生成 10,184 行 delete plan；core `apply_delete_plan.py` 先 dry-run 确认所有 key 均匹配，再以 migration id `2025-score-history-workbook-reconciled-official-reference-zero-placeholders` 执行，删除 10,184 行旧零占位记录。

2022 官方派生包 reconciliation 已用同一规则继续降噪：16,963 条任务中 3,638 条零占位、5,346 条 package-only、3,712 条 value drift 和 2,047 条单候选专业代码漂移被自动标为 reviewed，剩余 2,220 条仍为 todo（1,773 条 core-only、447 条多候选专业代码漂移）。已生成 120 行小批复核包，后续人工或证据核验完成前仍不能生成可导入包或 delete plan。

为了让人工复核先从小样本启动，可按 issue type 抽取 pending 任务：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-review-batch \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --output-dir staging/score_history_reconciliation_2023_2024/review_batch_initial \
  --limit-per-issue 20
```

真实 smoke 已生成初始 80 行 review batch，四类 issue type 各 20 行。该 batch 是本地工作文件，复核结果必须合并回完整 reconciliation plan 后再跑 readiness audit。

合并复核结果：

```bash
python3 scripts/build_package.py merge-score-history-reconciliation-review-batch \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --batch-csv staging/score_history_reconciliation_2023_2024/review_batch_initial/score_history_reconciliation_review_batch.csv \
  --output staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --report staging/score_history_reconciliation_2023_2024/merge_report.json
```

合并按 `task_id` 定位，只回写 `batch_editable_columns` 配置列，不能通过 batch 修改主键、分数、位次和来源证据。真实 smoke 已对未编辑初始 batch 合并验证：输入 24,478 行、batch 80 行、`updated_rows=0`，再次 readiness audit 仍为 `todo=24,478`、`package_ready=false`。

完整 plan 达到 `package_ready=true` 后，才允许构建可导入包：

```bash
python3 scripts/build_package.py build-score-history-from-reconciliation-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --output-root exports \
  --package-id 2024_2023_ln_score_history_reconciled
```

构建器按 `review_decision` 输出选择后的 `fa_fact_ln_score_history` 行：`use_package_row` 使用 package 侧数据，`keep_core_row` 保留 core 侧数据，`map_package_to_core_major_code` 使用 core 专业代码对齐 package 分数/位次，package-only 的 `exclude_row` 会跳过；`needs_source_research` 属于 blocking decision，readiness 不会通过。带 core 侧证据的 `exclude_row` 会被拒绝，因为当前 core importer 不能通过 CSV package 删除已有行，删除语义必须另行设计。真实未复核 2023/2024 plan 已验证会被拒绝：`pending=24478`，不会生成 data package。

core-backed `exclude_row` 不进入普通 data package，而是单独生成删除迁移计划：

```bash
python3 scripts/build_package.py build-score-history-delete-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --output-dir staging/score_history_reconciliation_2023_2024/delete_plan
```

该命令要求完整 plan 已复核完成，只输出待删除主键 CSV/JSON，不执行 SQL，不写 core，不是 data package。真实未复核 2023/2024 plan 已验证会被拒绝：`pending=24478`，不会生成 delete plan。

2022/2023/2024 官方图片页和 2022 镜像图片页可先用 `download-page-images` 采集图片并生成 manifest。manifest 兼容 `build-local --intake-manifest`，后续无论使用 OCR 还是人工转录，发布包都能追溯到原始图片 SHA-256：

```bash
python3 scripts/build_package.py download-page-images \
  --source-key ln_score_distribution \
  --output-root raw
```

真实 smoke 已验证该命令可采集 2022 辽宁招生考试之窗官方页 8 张图、2022 中新网镜像页 20 张图、2023 官方页 20 张图、2024 官方页 21 张图，共 69 张图。

2022 官方图片源 smoke：8 张官方图经 macOS Vision 生成 1,302 条 OCR observation；物理类解析 400 条候选，其中 337 条完整、71 条待复核；历史类解析 295 条候选，其中 131 条完整、177 条待复核。readiness audit 仍报告严格合并不可通过，必须人工核对 248 条复核任务后才能生成 cleaned CSV。相比此前 2022 中新网镜像 1,225 条待复核任务，官方图显著降低人工复核量。后续 source probe 还登记了学信网页面列出的 2022 历史/物理 DOCX 附件 URL，但直连仍返回 412，只能保留在 `research_candidates`，不能晋级为 `remote_files`。

2023/2024 继续保留来源研究记录。2023 中国教育电视台转载页列出普通类物理/历史学信网附件，但直连 file.do 返回 412，只能作为候选证据；2024 中国教育电视台转载页列出普通类物理/历史 PDF，已核验 HTTP 200、PDF 类型和 SHA-256，但仍是转载镜像，不替代辽宁官网原始长期源。`audit-score-source-coverage` 会把这些 URL 计入 `research_candidate_count` 和 `candidate_urls`，提醒后续采集继续寻找官方可重复文件源或完成官方图片差异审计。

2023/2024 官方图片页已配置普通类图片分组：1-4 张为历史类，5-8 张为物理类，后续体育/艺术图片不参与普通投档位次派生。该配置只定义来源切片，不代表解析结果可发布。grid OCR 候选 CSV 必须先与镜像 PDF、人工复核结果或其他基准 CSV 做差异审计：

```bash
python3 scripts/build_package.py parse-ln-score-distribution-image-groups \
  --manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json \
  --output-dir staging/ln_score_distribution_2024_official_grid_candidates \
  --work-dir staging/ln_score_distribution_2024_official_grid_rows \
  --summary-report staging/ln_score_distribution_2024_official_grid_candidates/summary.json

python3 scripts/build_package.py audit-score-distribution-csvs \
  --candidate staging/ln_score_distribution_2024_official_grid_candidates/ln_score_distribution_2024_ordinary_history_official_grid_candidate.csv \
  --candidate staging/ln_score_distribution_2024_official_grid_candidates/ln_score_distribution_2024_ordinary_physics_official_grid_candidate.csv \
  --baseline cleaned/ln_score_distribution_2024_jhgk_mirror.csv \
  --report staging/ln_score_distribution_2024_official_grid_vs_mirror.json
```

该命令只读 CSV，不写 core。报告会按 `subject_cat, score_year, score` 主键比较候选和基准的 `score_count/cumulative_rank`，并给出缺行、独有行、数值差异和分数序列摘要；`decision.reconciliation_required=true` 时，候选来源不能晋级为标准包。

grid OCR 解析参数由 `config/sources.json` 统一维护，包括人数列多数字取值策略和累计人数突跳修复阈值。当前真实复跑结果只证明候选质量提升，不代表可发布：2024 官方图片候选 1,051 行，对 1,086 行镜像基准仍缺 35 行、219 行数值不同；2023 官方图片候选 951 行，对 1,076 行镜像基准仍缺 125 行、423 行数值不同。两年仍必须保留为复核/阻断状态。

macOS 环境可使用系统 Vision OCR 生成可复查的 JSONL 中间产物。OCR 参数不写在代码里，由 `config/sources.json` 的 `ln_score_distribution.ocr` 维护：

```bash
python3 scripts/build_package.py ocr-page-images \
  --source-key ln_score_distribution \
  --input-root raw \
  --output-root ocr \
  --manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json
```

OCR manifest 会保留输入图片 manifest、证据 URL、目标表、识别语言、识别等级、图片 SHA-256 和每张图的 observation 数；JSONL 每行是一张图片的文本 observation 和归一化坐标，后续表格解析或人工复核都从这个中间产物继续。

OCR JSONL 下一步先进入候选解析，不直接发布为正式表。候选 CSV 会保留解析状态、累计校验状态、原始 OCR 文本和最低置信度；若同一图片同一表格块有足够锚点，解析器会把漏识别分数列但人数/累计齐全的行标为 `inferred_score`：

```bash
python3 scripts/build_package.py parse-ln-score-distribution-ocr \
  --ocr-jsonl ocr/ln_score_distribution/2024-06-25/_ocr__page_images_index.jsonl \
  --output staging/ln_score_distribution_2024_ocr_candidates.csv \
  --source-date 2024-06-25
```

真实 smoke：2024 OCR JSONL 生成 1,861 条候选、650 条直接 parsed 行、194 条 inferred_score 行、88 条 inferred_row 行、680 条累计校验 OK；2023 OCR JSONL 生成 1,450 条候选、227 条直接 parsed 行、116 条 inferred_score 行、2 条 inferred_row 行、265 条累计校验 OK；2022 镜像 OCR JSONL 生成 1,705 条候选、271 条直接 parsed 行、286 条 inferred_score 行、43 条 inferred_row 行、480 条累计校验 OK。`inferred_row` 使用同图同块锚点和连续累计规则补齐单数字行，参数由 `parser.ocr_table.infer_single_number_rows` 控制。该结果说明 OCR 候选仍需要人工复核或更强表格结构识别，不能跳过 `build-local` 质量闸门。

候选 CSV 可以继续转成可分派的复核任务表，优先级和建议动作由 `config/sources.json` 的 `parser.ocr_review.issue_actions` 维护：

```bash
python3 scripts/build_package.py build-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --output staging/ln_score_distribution_2024_review_tasks.csv
```

低分段页面如果只有一侧边界锚点，复核任务表会按 `parser.ocr_table.single_boundary_suggestion` 生成 `suggested_score/suggested_score_count/suggested_cumulative_rank`。对官方图片中“只识别到累计人数”的行，复核任务表还会按 `parser.ocr_table.sequence_suggestion` 利用同一科类年份的连续分数、相邻累计人数和表格块锚点生成建议值。这些字段只降低人工抄录成本，不会被 `apply-ln-score-distribution-review` 自动采信；必须由人工核对原图后复制到 `corrected_score/corrected_score_count/corrected_cumulative_rank`，并把 `review_status` 改为 `approved` 或 `corrected` 后才会进入 cleaned CSV。

真实 smoke：2024 候选生成 1,181 条复核任务，失败原因分布为 `incomplete=803, duplicate_score=184, invalid_score=122, cumulative_mismatch=68, extra_tokens=4`；2023 候选生成 1,185 条复核任务，失败原因分布为 `incomplete=975, invalid_score=130, duplicate_score=49, cumulative_mismatch=31`；2022 镜像候选生成 1,225 条复核任务，失败原因分布为 `incomplete=999, invalid_score=106, duplicate_score=87, cumulative_mismatch=33`；2022 官方图复核任务保持 248 条，其中物理类 71 条/13 条带建议值，历史类 177 条/13 条带建议值。复核任务表只用于校对，不是 data package。

复核任务可继续拆成本地工作区。工作区按原图生成批次 CSV、进度 manifest 和 HTML 核对页；pending 状态和可编辑字段由 `config/sources.json` 的 `parser.ocr_review_workspace` 维护：

```bash
python3 scripts/build_package.py build-ln-score-distribution-review-workspace \
  --review-csv staging/ln_score_distribution_2024_review_tasks.csv \
  --image-manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json \
  --output-dir staging/ln_score_distribution_2024_review_workspace
```

人工修正各批次 CSV 后，先合并回完整复核表：

```bash
python3 scripts/build_package.py merge-ln-score-distribution-review-workspace \
  --review-csv staging/ln_score_distribution_2024_review_tasks.csv \
  --workspace-dir staging/ln_score_distribution_2024_review_workspace \
  --output staging/ln_score_distribution_2024_review_tasks_merged.csv
```

如果复核任务中已有 `suggested_*`，可先预填到 `corrected_*`，减少人工录入。预填参数由 `config/sources.json` 的 `parser.ocr_review.prefill_suggestions` 控制；该配置禁止把建议值直接标记为 approved/drop，因此预填结果仍会被严格合并拒绝，直到人工核对原图并改为 `approved` 或 `corrected`：

```bash
python3 scripts/build_package.py prefill-ln-score-distribution-review-suggestions \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --output staging/ln_score_distribution_2024_review_tasks_prefilled.csv
```

真实 smoke：2022 镜像复核表 1,225 行中，预填 310 行 `corrected_*`，全部 `review_status` 仍为 `todo`；2022 官方图复核表中，物理类预填 13 行、历史类预填 13 行，`review_status` 仍全部为 `todo`。readiness audit 仍报告官方物理 `unresolved_rows=71`、官方历史 `unresolved_rows=177`，证明预填不会绕过人工复核。

真实 smoke：2024 工作区生成 21 个图片批次、1,181 条待复核任务；2023 工作区生成 20 个图片批次、1,185 条待复核任务；2022 镜像工作区生成 19 个图片批次、1,225 条待复核任务；2022 官方图预填工作区生成物理 3 个图片批次/71 条任务、历史 4 个图片批次/177 条任务。未修改批次可无损合并回总表，`updated_rows=0`。

工作区 HTML 会用 `ocr_table.block_x_ranges` 和任务中的 `row_y/block_index` 在原图上绘制定位框，帮助人工快速找到待核对行。定位框参数由 `parser.ocr_review_workspace.row_locator` 维护，只影响复核体验，不进入 cleaned CSV 或 package。真实 smoke：2022 镜像 prefilled review 生成 19 个图片批次，1,225 条任务均有 locator row。

复核完成后，使用 review task 中的 `corrected_score/corrected_score_count/corrected_cumulative_rank` 合并出 cleaned CSV：

```bash
python3 scripts/build_package.py apply-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --output cleaned/ln_score_distribution_2024.csv
```

默认严格模式会拒绝未完成复核任务、重复主键和累计校验错误。真实 smoke：未复核的 2024 review tasks 被严格模式拒绝；`--allow-unresolved` 仅输出 680 行部分清洗结果并报告 1,181 条 unresolved、35 条累计质量错误。未复核的 2023 review tasks 在 `--allow-unresolved` 下仅输出 265 行部分清洗结果并报告 1,185 条 unresolved、19 条累计质量错误。部分清洗结果不能导入 core，也不能作为正式 data package。

每个年份进入 `build-local` 前，应先跑 readiness audit，输出候选解析状态、复核任务状态、严格合并结果和 cleaned CSV 质量门禁：

```bash
python3 scripts/build_package.py audit-ln-score-distribution-readiness \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --cleaned-csv cleaned/ln_score_distribution_2024.csv \
  --report staging/ln_score_distribution_2024_readiness.json
```

真实 smoke：2022 镜像候选 + 未复核任务的 readiness audit 报告 `candidate_rows=1705`、`review_task_rows=1225`、`suggested_review_rows=310`、`unresolved_rows=1225`，`strict_apply.ok=false`，blocking reason 为 `strict_review_apply_failed/cleaned_csv_not_ready`。

OCR 或人工转录后的 cleaned CSV 不允许直接进入 core，必须通过 `build-local` 生成标准包。`build-local` 对 `fa_fact_ln_score_distribution` 会强制校验：

- `score` 在 0-750 分范围内。
- `score_count` 和 `cumulative_rank` 为正数。
- 同一科类、同一年份内，按分数从高到低累计时，当前 `cumulative_rank = previous_cumulative_rank + score_count`。

```bash
python3 scripts/build_package.py build-local \
  --source-key ln_score_distribution \
  --table fa_fact_ln_score_distribution \
  --input cleaned/ln_score_distribution_2024.csv \
  --output-root exports \
  --package-id 2024_ln_score_distribution \
  --intake-manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json
```

该 package 的 `manifest.source_lineage` 会保留图片采集 manifest 中的 evidence URL、采集人、来源日期和每张原图 SHA-256。

## 证据域数据包

推荐和报告需要的学校、专业、政策证据由 DataHub 产出标准包，core 只消费：

- `fa_dim_school_profile`：高校基础画像，主键 `national_school_code`。
- `fa_bridge_school_identity`：辽宁本地院校代码到教育部学校标识码的桥表，主键 `local_system, local_school_code`。
- `fa_fact_school_outcome`：高校出口指标，主键 `school_code, metric_key, metric_year, source_url`。
- `fa_fact_major_outcome`：专业出口指标，主键 `major_code, metric_key, metric_year, source_url`。
- `fa_dim_policy_industry_map`：政策到 TDX 行业映射，主键 `tdx_l2`。
- `fa_dim_policy_plan_history`：十三五/十四五兑现回测，主键 `plan_period, tdx_l2`。

这些表的字段、别名、必填列、数字列维护在 `config/source_schemas.json`；来源状态维护在 `config/sources.json`。没有明确来源 URL 或证据摘录的主观判断不得发布为 outcome 数据包。

学校和专业 outcome 的 `metric_key` 必须先登记到 `config/outcome_metrics.json`。`build-local` 会校验 metric key、单位和取值范围；未登记指标不会被打包发布。

## 职业数据链路

职业相关数据先由配置生成采集计划，再由受控批次补证据和指标值，最后发布 `fa_fact_career_signal` 并加工 `fa_mart_career_score`。采集源、指标口径、值域、评分权重和批次可回写列维护在 `config/career_data_sources.json`，表结构维护在 `config/source_schemas.json`：

```bash
python3 scripts/build_package.py download \
  --source-key career_occupation_catalog \
  --output-root raw

python3 scripts/build_package.py parse-digital-occupation-catalog \
  --input raw/career_occupation_catalog/2022-10-28/digital_occupation_catalog_2022.html \
  --output cleaned/digital_occupation_catalog_2022.csv \
  --source-title 国家职业分类大典首次标识数字职业 \
  --source-url https://chinajob.mohrss.gov.cn/c/2022-10-28/363399.shtml \
  --source-date 2022-10-28 \
  --availability-date 2022-10-28

python3 scripts/build_package.py build-local \
  --source-key career_occupation_catalog \
  --table fa_dim_career_occupation \
  --input cleaned/digital_occupation_catalog_2022.csv \
  --output-root exports \
  --package-id 2022_digital_occupation_catalog

python3 scripts/build_package.py build-career-source-plan \
  --output-dir staging/career_source_plan \
  --occupation-input cleaned/career_occupation_seed.csv \
  --city 沈阳 \
  --metric-year 2026

python3 scripts/build_package.py download-scs-resources \
  --source-key career_civil_service_posts \
  --output-root raw

python3 scripts/build_package.py parse-scs-position-workbook \
  --input raw/career_civil_service_posts/2025-10-14/中央机关及其直属机构2026年度考试录用公务员招考简章.zip \
  --output cleaned/career_civil_service_posts/2026_scs_positions.csv \
  --source-title 中央机关及其直属机构2026年度考试录用公务员招考简章 \
  --source-url http://dl.scs.gov.cn/download/8a81f6d19780e4080199e13f881f0153 \
  --source-date 2025-10-14 \
  --availability-date 2025-10-14

python3 scripts/build_package.py build-local \
  --source-key career_civil_service_posts \
  --table fa_fact_civil_service_position \
  --input cleaned/career_civil_service_posts/2026_scs_positions.csv \
  --output-root exports \
  --package-id 2026_scs_civil_service_positions

python3 scripts/build_package.py build-career-source-review-batch \
  --plan-csv staging/career_source_plan/career_source_plan.csv \
  --output-dir staging/career_source_plan/batch_001 \
  --limit-per-source 20

python3 scripts/build_package.py merge-career-source-review-batch \
  --plan-csv staging/career_source_plan/career_source_plan.csv \
  --batch-csv staging/career_source_plan/batch_001/career_source_review_batch.csv \
  --output staging/career_source_plan/career_source_plan_merged.csv \
  --report staging/career_source_plan/career_source_merge.json

python3 scripts/build_package.py audit-career-source-plan \
  --plan-csv staging/career_source_plan/career_source_plan_merged.csv \
  --report staging/career_source_plan/career_source_audit.json

python3 scripts/build_package.py build-career-signal-from-source-plan \
  --plan-csv staging/career_source_plan/career_source_plan_merged.csv \
  --output-root exports \
  --package-id 2026_career_signal_shenyang
```

数字职业 HTML 解析器只把官方页面里的职业编码和名称转成职业目录种子表；职业大类映射由 `occupation_family_by_code_prefix` 配置维护，行业映射和关键词后续由单独配置/采集批次补齐。

真实 smoke：`career_occupation_catalog` 远程下载已校验 SHA-256 并生成 `_remote_manifest.json`；HTML 解析出 73 条数字职业，`build-local --intake-manifest` 生成 `2022_digital_occupation_catalog` 标准包，quality report 无错误，DataHub `validate` 与 core importer `--dry-run` 均通过。

国家公务员局下载资源 API 登记在 `career_civil_service_posts.resource_api`，职位表列映射登记在 `career_civil_service_posts.position_parser`，职位明细表契约为 `fa_fact_civil_service_position`。`download-scs-resources` 只做官方附件 raw intake：保存 API 响应、筛选后的资源文件和 `_scs_resource_manifest.json`；`parse-scs-position-workbook` 只把官方 `.xls` 转成可复核职位明细 CSV，不把职位表直接解析为职业指标。真实 smoke：API 返回 8 个资源，配置筛出并下载 1 个“中央机关及其直属机构2026年度考试录用公务员招考简章.zip”，文件大小 1,860,532 字节，SHA-256 为 `0055e7eb78906e2dcefb8e31963e2fd74baf980aa98893eebb54fd9d7f9176cb`；职位表解析出 20,714 条职位、招考人数合计 38,119；`2026_scs_civil_service_positions` 包 quality report 无错误、manifest 校验通过，core importer `--dry-run` 通过。后续需要按专业/职业映射统计岗位数，再进入 `career_source_plan` 复核和 `fa_fact_career_signal` 出包门禁。

职业复核种子分两类：国考职位表种子只保存复核结论，证据仍来自重新生成的职位匹配计划；薪酬调查、招聘快照等受控报告类种子必须携带 `config/career_data_sources.json.audit.required_seed_copy_fields_by_source` 指定的指标值、口径、来源、摘录和日期字段，用于重放完整信号。国考职位表真实 run：以本地 core 73 条职业目录生成 44 条候选复核行，当前 25 条已核职业信号生成 `2026_career_signal_civil_service_verified_v2` 和 `2026_career_score_civil_service_verified_v2` 标准包，manifest 校验、core importer dry-run 和本地实导均通过；19 条候选保持 `in_progress`。薪酬调查真实 run：以本地 core 73 条职业目录生成宁波 2024 年 `career_salary_survey` 采集计划 219 行，重放 15 条宁波薪酬调查种子，覆盖 5 个职业的 `salary_p25/salary_median/salary_p75`；审计无错误，生成 `2024_ningbo_salary_career_signal_v1` 15 行和 `2024_ningbo_salary_career_score_v1` 5 行，manifest 校验、core importer dry-run 和本地实导均通过。招聘快照首批真实 run：以本地 core 73 条职业目录生成广州 2025 年 `career_recruitment_snapshot` 采集计划 365 行，重放广州市人社局公开供求分析中的 2 条 `shortage_rank` 种子，生成 `2025_guangzhou_shortage_career_signal_v1` 2 行和 `2025_guangzhou_shortage_career_score_v1` 2 行；该评分包保留 `below_minimum_signal_count`，用于提示当前只有单一紧缺排行证据。

`apply-career-shortage-page` 负责把公开供求分析 HTML 转为 `career_source_plan` 候选证据：它只解析已 intake 的 HTML，不直接写 core；只回填 `shortage_rank` 行的指标值、来源、摘录和候选状态；后续仍通过 `apply-career-source-review-seeds` 或人工复核批次晋级。真实广州页面解析出 30 个排行项，与当前 core 职业目录精确匹配 2 项，重放种子后 `audit-career-source-plan` 返回 `verified=2/todo=363/errors=[]`。

批次命令按 `source_key, target_table, occupation_code, occupation_name, metric_key, metric_year, city` 定位任务，只允许回写配置列，防止局部文件改掉职业、指标、来源或目标表。通过审计后，`build-career-signal-from-source-plan` 只读取完整状态的职业信号行，复用标准数据包质量门禁生成 `fa_fact_career_signal`，再用 `build-career-score` 生成职业评分加工包。

Outcome 数据采集不直接从搜索结果进 core。先用 core 招生计划生成高优先级采集队列：

```bash
python3 scripts/build_package.py build-outcome-collection-plan \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-dir staging/outcome_collection \
  --school-limit 80 \
  --major-limit 80
```

采集队列由 `config/outcome_collection.json` 维护：目标实体来自 `fa_dim_ln_admission_plan`，默认过滤普通类本科批，优先级按招生计划行数排序，指标必须在 `config/outcome_metrics.json` 注册，搜索 query 模板也在配置中维护。它只输出任务 CSV/JSON，不是 data package；人工或后续采集器补齐来源 URL、证据摘录和指标值后，才可通过 `build-local` 生成 `fa_fact_school_outcome` / `fa_fact_major_outcome` 包。

采集批次也必须从总计划派生，不能另起一张临时事实表。`build-outcome-collection-batch` 按 `config/outcome_collection.json` 的 `review_batch.selection_statuses`、`limit_per_domain` 和 `editable_columns` 拆出小批 CSV；`merge-outcome-collection-batch` 只允许回写配置列，并用 `domain, entity_code, metric_key, metric_year` 定位任务，防止采集批次篡改实体、指标或优先级：

```bash
python3 scripts/build_package.py build-outcome-collection-batch \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-dir staging/outcome_collection/batch_001 \
  --limit-per-domain 20

python3 scripts/build_package.py merge-outcome-collection-batch \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --batch-csv staging/outcome_collection/batch_001/outcome_collection_batch.csv \
  --output staging/outcome_collection/outcome_collection_plan_merged.csv \
  --report staging/outcome_collection/outcome_collection_merge.json
```

采集推进过程中应先审计任务表，而不是直接打包。`audit-outcome-collection-plan` 会检查 metric 是否登记、单位和值域是否匹配、完成状态是否有 `metric_value/source_url/evidence_quote`，并输出 domain/metric/status 进度：

```bash
python3 scripts/build_package.py audit-outcome-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --report staging/outcome_collection/outcome_collection_audit.json
```

真实 smoke：用 core DB 生成学校 5 个、专业 5 个的小样本采集队列，共 40 条任务；审计结果为 `todo=40`、`complete_rows=0`、`errors=[]`，说明当前仍是采集计划，不能作为 outcome 数据包导入 core。

报告 PDF/OFD 只能先转成待复核候选，不直接改采集计划。进入 extraction plan 前，DataHub 会检查本地路径、扩展名和文件签名；`.pdf` 必须以 `%PDF` 开头，HTML 伪装文件会以 `local_report_path_is_html` 阻断。`extract-outcome-report-candidates` 使用 `config/outcome_metrics.json` 中的 `aliases` 从报告文本抽取指标候选，输出列包含 `candidate_value/evidence_quote/page_number/match_alias/confidence/review_status`。`review_status` 固定为 `needs_review`，人工核对报告上下文后，才能把值、摘录和口径复制到 outcome collection batch：

```bash
python3 scripts/build_package.py extract-outcome-report-candidates \
  --input raw/outcome_report/2022-12-31/lnu_2022_employment_quality.pdf \
  --output staging/outcome_report_candidates/lnu_2022_candidates.csv \
  --domain school \
  --entity-code 10140 \
  --entity-name 辽宁大学 \
  --metric-year 2022 \
  --source-title '辽宁大学2022届毕业生就业质量年度报告' \
  --source-url 'https://www.lnu.edu.cn/info/15026/78891.htm' \
  --source-date 2022-12-31 \
  --availability-date 2022-12-31
```

真实 smoke：辽宁大学官方 2022 届毕业生就业质量年度报告 PDF 产出 4 条 `civil_service_rate` 候选；沈阳工业大学官方 2023-2024 本科教学质量报告 PDF 产出 1 条 `employment_rate` 候选；东北财经大学 2023-2024 本科教学质量报告 OFD 可从 `TextObject/TextCode` 抽取 1 条 `employment_rate=0.8864` 候选。候选 CSV 只用于复核，不是 data package，也不会导入 core。

候选人工核对后，通过 `merge-outcome-report-candidates` 回写完整采集计划。该命令只接受 `config/outcome_collection.json.candidate_merge.approved_statuses` 中配置的状态，默认仅 `approved`；合并后目标状态、可回写列也由同一段配置控制：

```bash
python3 scripts/build_package.py merge-outcome-report-candidates \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --candidate-csv staging/outcome_report_candidates/lnu_2022_candidates_reviewed.csv \
  --output staging/outcome_collection/outcome_collection_plan_with_report_candidates.csv \
  --report staging/outcome_collection/outcome_report_candidate_merge.json
```

真实 smoke：4 条辽宁大学候选中只有 1 条被标为 `approved`，合并报告 `approved_candidate_rows=1`、`updated_rows=1`；再跑 `audit-outcome-collection-plan` 得到 `verified=1`、`errors=[]`。未批准候选不会写入采集计划，也不能进入 outcome package。

当采集任务被人工核对并标记为完成状态后，才可从采集表生成标准 outcome 数据包：

```bash
python3 scripts/build_package.py build-outcome-from-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-root exports \
  --package-id 2026_outcome_collection
```

该入口只读取 `verified/ready/collected` 行，会先运行 outcome collection audit，再复用 `build-local` 的 schema、主键、metric key、单位和值域校验。真实 smoke：`/tmp` 中 1 条学校 verified outcome 和 1 条专业 verified outcome 成功生成 `fa_fact_school_outcome`、`fa_fact_major_outcome` 两个标准包，质量报告无错误。

端到端真实 smoke：辽宁大学报告候选合并后的 1 条 `verified` 采集行已生成 `lnu_2022_outcome_candidate_merge_smoke_school` 包，`fa_fact_school_outcome` 1 行，quality report 无错误；manifest `source_lineage` 已记录采集计划路径、来源 URL、报告标题、指标和状态统计；DataHub `validate` 返回 `errors=[]`，core importer `--dry-run` 通过。学校 outcome 复核种子当前覆盖 19 条已核指标：2024 学校 outcome 覆盖辽宁大学就业率/升学率、沈阳工业大学就业率、辽宁工程技术大学就业率/升学率、吉林大学就业率/深造率、辽宁师范大学就业率/深造率、渤海大学就业率、大连交通大学就业率/国企签约比例、大连工业大学就业率/考研比例/党政机关事业单位等去向比例、大连民族大学就业率、东北财经大学就业率；大连大学 2023 届就业落实率按 `metric_year=2023` 独立维护，避免把 2023-2024 学年报告中的 2023 届指标混入 2024 届口径；辽宁大学 2022 届国有企业就业比例按 `metric_year=2022` 独立维护，口径明确不含党政机关和事业单位。种子重放、采集计划审计、`ln_outcome_school_2024_seeded_v7_school`、`2023_dlu_school_outcome_seeded_v1_school` 与 `2022_lnu_school_outcome_soe_seeded_v1_school` manifest 校验、core importer `--dry-run` 和本地 core 实导均通过。

政策映射和规划兑现回测不再由 core 建表脚本生产。DataHub 用版本化配置生成标准包：

```bash
python3 scripts/build_package.py build-policy-industry-map \
  --output-root exports \
  --package-id 2026_policy_industry_map

python3 scripts/build_package.py build-policy-plan-history \
  --output-root exports \
  --package-id 2026_policy_plan_history
```

配置文件分别是 `config/policy_industry_map.json` 和 `config/policy_plan_history.json`。builder 会校验主键、必填列、政策标签、强度/兑现分范围和 `key_themes_json` 格式，并把官方规划页面写入 `manifest.source_lineage`。

教育部全国高等学校名单通过 `school_profile` source 下载，并用 parser 生成 `fa_dim_school_profile`：

```bash
python3 scripts/build_package.py parse-moe-school-profile \
  --input raw/school_profile/2025-06-20/moe_school_profile_2025.xls \
  --output cleaned/moe_school_profile_2025.csv \
  --source-date 2025-06-20 \
  --availability-date 2025-06-27
```

注意：教育部“学校标识码”不是辽宁招生计划里的本地院校代码。`fa_dim_school_profile` 以 `national_school_code` 为主键；`fa_bridge_school_identity` 单独负责把辽宁本地院校代码稳定对齐到全国学校标识码。

桥表由 core 招生计划库和教育部学校画像 CSV 共同生成：

```bash
python3 scripts/build_package.py build-school-identity \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --school-profile cleaned/moe_school_profile_2025.csv \
  --output-root exports \
  --package-id 2025_school_identity_bridge
```

第一版只发布唯一学校名精确匹配结果；未匹配本地院校代码进入 quality report 的 warning，不做模糊自动合并。

## 历史位次过渡包

`ln_score_history` 的官方可重复来源仍未确认。为了让当前 core 中已有的清洗结果也进入 DataHub 数据包链路，可以先生成 legacy snapshot：

```bash
python3 scripts/build_package.py build-score-history-snapshot \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-root exports \
  --package-id legacy_ln_score_history_snapshot
```

该包只导出 `min_score/min_rank` 等推荐必需字段完整的行，并在 `quality_report.warnings` 和 `manifest.source_lineage` 中标注 `legacy_core_snapshot`。它不是官方来源替代品，后续仍必须寻找辽宁官方多年份录取位次来源。

## 专业映射复核数据包

`major_mapping_review` source 从 core 的 `university.db` 只读读取：

- `fa_bridge_major_tdx`：现有正式映射。
- `fa_mart_major_mapping_review_queue`：已批准的复核候选。

DataHub 输出完整 `fa_bridge_major_tdx.csv`，而不是只输出增量，避免 core 侧导入时需要知道 DataHub 的内部合并逻辑。复核行不使用招生计划里的本地 `major_code_sample` 作为正式 `major_code`，而是生成 `REVIEW_NAME_<hash>`，防止学校本地专业代码污染 code-based lookup；推荐系统仍通过 `major_name` 命中这些映射。
