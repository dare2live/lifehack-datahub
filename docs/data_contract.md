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

顾问本地已清洗“报考数据”工作簿通常不是目标表结构，而是多个 sheet 混合招生计划、学校/专业增强字段，以及 2022-2025 历史最低分/位次。DataHub 用 `config/ln_application_workbook.json` 维护 sheet 选择、批次、科类、字段别名、年份列和重复主键策略，再输出标准 cleaned CSV：

```bash
python3 scripts/build_package.py parse-ln-application-workbook \
  --input "/Users/dp/Documents/M/lifehack/26年报考数据/26年本科批报考数据8.27.xlsx" \
  --plan-output cleaned/ln_application_workbook_plan.csv \
  --score-output cleaned/ln_application_workbook_score_history.csv \
  --report cleaned/ln_application_workbook_report.json
```

该入口只读 Excel，输出 `fa_dim_ln_admission_plan` 与 `fa_fact_ln_score_history` 两张 cleaned CSV 及解析报告，不生成 data package、不写 core。确认 `duplicate_counts` 和 `ignored_sheets` 后，再用 `build-local` 进入数据包契约。默认配置只接收普通类本科批 `物理类/历史类` sheet，特殊类型、提前批、艺术/体育/专科需增加 profile 或 sheet rule 后再解析，避免把不同录取规则混进同一批次。

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
  --acquired-by consultant \
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

`ln_projection_score` 当前配置覆盖 2024-2025 辽宁招生考试之窗附件，以及 2023 中国教育在线转载镜像附件。2023 镜像页面标注来源为辽宁招生考试之窗，但仍按镜像来源记录，不替代辽宁官网原始长期源。

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

注意：派生的 `min_rank` 是最低分对应的一分一段累计人数，不是同分排序后的精确投档位次。`quality_report.warnings` 会保留 `rank_is_score_cumulative_rank`。2023/2024 已补充转载 PDF 镜像，登记为 `mirror_pdf`，可文本解析但不能冒充辽宁官网原始长期来源；真实 smoke 已解析 2023 年 1,076 行、2024 年 1,086 行 `fa_fact_ln_score_distribution` 并通过质量闸门。2022 已补充辽宁招生考试之窗官方图片页，仍需 OCR 或受控人工复核；中新网辽宁转载图片页保留为兜底镜像候选源。

真实派生 smoke：2023 投档最低分 14,435 行 + 2023 一分一段 PDF 镜像 1,076 行，生成 14,435 行 `fa_fact_ln_score_history`，unmatched=0、质量错误为空；2024 投档最低分 14,298 行 + 2024 一分一段 PDF 镜像 1,086 行，生成 14,298 行，unmatched=0、质量错误为空。core importer 修复 `upsert_or_replace_package` 后，连续导入 2023/2024 两个数据包的临时库同时保留两年数据，且 `min_rank` 无空值。

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

2022 官方图片源 smoke：8 张官方图经 macOS Vision 生成 1,302 条 OCR observation；物理类解析 400 条候选，其中 337 条完整、71 条待复核；历史类解析 295 条候选，其中 131 条完整、177 条待复核。readiness audit 仍报告严格合并不可通过，必须人工核对 248 条复核任务后才能生成 cleaned CSV。相比此前 2022 中新网镜像 1,225 条待复核任务，官方图显著降低人工复核量。

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

低分段页面如果只有一侧边界锚点，复核任务表会按 `parser.ocr_table.single_boundary_suggestion` 生成 `suggested_score/suggested_score_count/suggested_cumulative_rank`。这些字段只降低人工抄录成本，不会被 `apply-ln-score-distribution-review` 自动采信；必须由人工核对原图后复制到 `corrected_score/corrected_score_count/corrected_cumulative_rank`，并把 `review_status` 改为 `approved` 或 `corrected` 后才会进入 cleaned CSV。

真实 smoke：2024 候选生成 1,181 条复核任务，失败原因分布为 `incomplete=803, duplicate_score=184, invalid_score=122, cumulative_mismatch=68, extra_tokens=4`；2023 候选生成 1,185 条复核任务，失败原因分布为 `incomplete=975, invalid_score=130, duplicate_score=49, cumulative_mismatch=31`；2022 镜像候选生成 1,225 条复核任务，失败原因分布为 `incomplete=999, invalid_score=106, duplicate_score=87, cumulative_mismatch=33`。复核任务表只用于校对，不是 data package。

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

真实 smoke：2022 镜像复核表 1,225 行中，预填 310 行 `corrected_*`，全部 `review_status` 仍为 `todo`；readiness audit 仍报告 `unresolved_rows=1225` 和 `strict_apply.ok=false`，证明预填不会绕过人工复核。

真实 smoke：2024 工作区生成 21 个图片批次、1,181 条待复核任务；2023 工作区生成 20 个图片批次、1,185 条待复核任务；2022 镜像工作区生成 19 个图片批次、1,225 条待复核任务。未修改批次可无损合并回总表，`updated_rows=0`。

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

当采集任务被人工核对并标记为完成状态后，才可从采集表生成标准 outcome 数据包：

```bash
python3 scripts/build_package.py build-outcome-from-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-root exports \
  --package-id 2026_outcome_collection
```

该入口只读取 `verified/ready/collected` 行，会先运行 outcome collection audit，再复用 `build-local` 的 schema、主键、metric key、单位和值域校验。真实 smoke：`/tmp` 中 1 条学校 verified outcome 和 1 条专业 verified outcome 成功生成 `fa_fact_school_outcome`、`fa_fact_major_outcome` 两个标准包，质量报告无错误。

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
