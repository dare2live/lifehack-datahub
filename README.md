# LifeHack DataHub

独立数据工程项目，服务 `志途 LifeHack` 核心顾问工作台。

本项目负责外部数据的采集、解析、清洗、校验和发布。核心仓库只导入本项目产出的 data package，不直接爬网站、不解析 Excel、不维护反爬和字段清洗逻辑。

## 边界

- DataHub 可以接触原始 Excel、PDF、HTML、CSV。
- DataHub 输出 `manifest.json`、`quality_report.json` 和标准化数据文件。
- Core 只读取导出包，不 import 本项目 Python 模块。
- 本仓库不包含真实 Excel、DuckDB、原始下载文件或含个人信息的数据。

## 目录

```text
config/        数据源配置
datahub/
  connectors/  外部数据源连接器
  parsers/     Excel/PDF/HTML/CSV 解析
  normalizers/ 字段标准化和代码标准化
  validators/  schema、主键、行数、hash、质量检查
  exporters/   data package 发布
docs/          数据契约
scripts/       命令入口
tests/         契约测试
```

## 目标导出包

```text
exports/YYYY-MM-DD_ln_admission_plan/
  manifest.json
  quality_report.json
  fa_dim_ln_admission_plan.parquet
  fa_fact_ln_score_history.parquet
```

## 当前阶段

Phase 5+：已固化数据包契约和模块边界，提供本地已清洗 CSV/TSV/XLSX 到 data package 的生成入口，支持远程文件下载、受控手工 intake、教育部目录解析、辽宁投档分解析、辽宁一分一段转录校验与 OCR 复核工作区、学校身份桥表、历史位次 legacy snapshot、专业映射复核晋级，以及配置驱动的政策表数据包生成。

## 本地数据包生成

先审计数据源获取状态：

```bash
python3 scripts/build_package.py audit-sources
```

先按 `config/sources.json` 发现本地文件：

```bash
python3 scripts/build_package.py discover --source-key ln_admission_plan
```

如果 `config/sources.json` 为某个 source 配置了 `remote_files`，可以先下载到 raw 目录：

```bash
python3 scripts/build_package.py download \
  --source-key ln_admission_plan \
  --output-root raw
```

如果某个来源还没有达到可晋级为 `remote_files` 的稳定程度，先放入 `research_candidates`，再用探测命令记录可访问性、HTTP 状态、文件大小和 SHA-256。探测报告只用于来源研究，不会写入 raw，也不能导入 core：

```bash
python3 scripts/build_package.py probe-source-candidates \
  --source-key ln_projection_score \
  --output staging/source_research/ln_projection_score_candidates.json
```

再把已清洗文件生成 data package：

```bash
python3 scripts/build_package.py build-local \
  --source-key ln_admission_plan \
  --table fa_dim_ln_admission_plan \
  --input raw/ln_admission_plan/2026_cleaned.csv \
  --output-root exports \
  --package-id 2026_ln_admission_plan
```

字段别名和 schema 在 `config/source_schemas.json` 维护。`raw/` 和 `exports/` 默认被 `.gitignore` 排除。

教育部本科专业目录 PDF 可解析为标准 CSV：

```bash
python3 scripts/build_package.py parse-moe-major-catalog \
  --input raw/moe_major_catalog/2025-04-22/moe_major_catalog_2025.pdf \
  --output cleaned/moe_major_catalog_2025.csv
```

辽宁本科批投档最低分 XLSX 可解析为标准 CSV：

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

辽宁官方成绩统计表 PDF 可解析为一分一段分布，并与投档最低分派生 `fa_fact_ln_score_history`：

```bash
python3 scripts/build_package.py parse-ln-score-distribution \
  --input raw/ln_score_distribution/2025-06-24/ln_score_distribution_2025_history.pdf \
  --input raw/ln_score_distribution/2025-06-24/ln_score_distribution_2025_physics.pdf \
  --output cleaned/ln_score_distribution_2025.csv \
  --score-year 2025 \
  --source-date 2025-06-24

python3 scripts/build_package.py build-score-history-from-projection \
  --projection cleaned/ln_projection_score_2025.csv \
  --score-distribution cleaned/ln_score_distribution_2025.csv \
  --output-root exports \
  --package-id 2025_ln_score_history_derived
```

派生位次是最低分对应的一分一段累计人数，不是同分排序后的精确投档位次，质量报告会保留 warning。

2023/2024 已跑通真实派生 smoke：2023 生成 14,435 行、2024 生成 14,298 行 `fa_fact_ln_score_history`，两个包连续导入 core 临时库后可同时保留两年数据，`min_rank` 无空值。

导入实际 core 库前必须先做只读对账。对账字段和作用域由 `config/source_schemas.json` 的 `fa_fact_ln_score_history.audit` 维护，命令只读打开 core DB，不会写入 `university.db`：

```bash
python3 scripts/build_package.py audit-score-history-package-against-core \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2023_ln_score_history_derived_pdf_mirror \
  --package-dir exports/2024_ln_score_history_derived_pdf_mirror \
  --report audits/score_history_2023_2024_against_core.json
```

若报告出现 `different_rows`、`core_only_rows` 或重叠作用域下的 `package_only_rows`，先做代码体系/来源体系 reconciliation，不直接覆盖实际工作库。报告中的 `reconciliation_hints.same_values_different_key_candidates` 会按配置化匹配列提示“同校同年同分同位次但专业代码不同”的疑似代码漂移。

2023/2024 已补充可文本解析的转载 PDF 镜像，配置为 `mirror_pdf`，不能冒充辽宁官网原始长期来源。真实 smoke 已解析 2023 年 1,076 行、2024 年 1,086 行，并通过 `fa_fact_ln_score_distribution` 质量闸门：

```bash
python3 scripts/build_package.py download \
  --source-key ln_score_distribution \
  --output-root raw

python3 scripts/build_package.py parse-ln-score-distribution \
  --input raw/ln_score_distribution/2023-06-24/ln_score_distribution_2023_physics_gengsan_mirror.pdf \
  --input raw/ln_score_distribution/2023-06-24/ln_score_distribution_2023_history_jiaoyuwu_mirror.pdf \
  --output cleaned/ln_score_distribution_2023_pdf_mirror.csv \
  --score-year 2023 \
  --source-date 2023-06-24 \
  --subject-cat 物理类 \
  --subject-cat 历史类

python3 scripts/build_package.py parse-ln-score-distribution \
  --input raw/ln_score_distribution/2024-06-24/ln_score_distribution_2024_physics_jhgk_mirror.pdf \
  --input raw/ln_score_distribution/2024-06-24/ln_score_distribution_2024_history_jhgk_mirror.pdf \
  --output cleaned/ln_score_distribution_2024_jhgk_mirror.csv \
  --score-year 2024 \
  --source-date 2024-06-24 \
  --subject-cat 物理类 \
  --subject-cat 历史类
```

2022/2023/2024 成绩统计表仍保留官方图片页，2022 另保留中新网辽宁转载镜像作为兜底候选来源。可先采集图片和 SHA-256 manifest，后续再 OCR 或受控人工转录；所有镜像都不能冒充辽宁官网原始长期来源：

```bash
python3 scripts/build_package.py download-page-images \
  --source-key ln_score_distribution \
  --output-root raw
```

macOS 环境可使用系统 Vision OCR 生成可复查的 JSONL 中间产物，识别语言和等级由 `config/sources.json` 维护：

```bash
python3 scripts/build_package.py ocr-page-images \
  --source-key ln_score_distribution \
  --input-root raw \
  --output-root ocr \
  --manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json
```

OCR JSONL 不能直接发布为正式数据。先生成带解析状态、累计校验状态、原始文本和置信度的候选 CSV。若同一图片同一表格块有足够锚点，解析器会按配置把漏识别分数列的行标为 `inferred_score`，也可用连续累计规则把单数字行标为 `inferred_row`；仍需后续质量闸门：

```bash
python3 scripts/build_package.py parse-ln-score-distribution-ocr \
  --ocr-jsonl ocr/ln_score_distribution/2024-06-25/_ocr__page_images_index.jsonl \
  --output staging/ln_score_distribution_2024_ocr_candidates.csv \
  --source-date 2024-06-25
```

候选 CSV 用于人工复核或后续表格识别增强；只有复核后的 cleaned CSV 才能进入 `build-local`。

再把候选 CSV 转成可分派的复核任务表：

```bash
python3 scripts/build_package.py build-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --output staging/ln_score_distribution_2024_review_tasks.csv
```

复核任务表会按失败原因和位置排序，并预留 `corrected_score`、`corrected_score_count`、`corrected_cumulative_rank` 给人工校对。低分段页面如果只有一侧边界锚点，系统会按 `parser.ocr_table.single_boundary_suggestion` 预填 `suggested_score/suggested_score_count/suggested_cumulative_rank`，但这些建议不会自动进入 cleaned CSV，必须由人工复制到 corrected 字段并把状态改为 approved/corrected 后才会生效。

为了让人工复核能按原图推进，可把总任务表拆成本地工作区。工作区会按图片生成批次 CSV、进度 manifest 和一个只引用本地原图的 HTML 核对页；状态和可编辑字段由 `config/sources.json` 的 `parser.ocr_review_workspace` 维护：

```bash
python3 scripts/build_package.py build-ln-score-distribution-review-workspace \
  --review-csv staging/ln_score_distribution_2024_review_tasks.csv \
  --image-manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json \
  --output-dir staging/ln_score_distribution_2024_review_workspace
```

HTML 核对页会根据 `ocr_table.block_x_ranges` 和每条任务的 `row_y/block_index` 在原图上显示行定位框。定位框只用于人工找行，不参与数据合并；行高和开关由 `parser.ocr_review_workspace.row_locator` 配置。

分批 CSV 修正后，再合并回完整复核表：

```bash
python3 scripts/build_package.py merge-ln-score-distribution-review-workspace \
  --review-csv staging/ln_score_distribution_2024_review_tasks.csv \
  --workspace-dir staging/ln_score_distribution_2024_review_workspace \
  --output staging/ln_score_distribution_2024_review_tasks_merged.csv
```

若复核表已有 `suggested_*`，可先把建议值预填到 `corrected_*`，降低人工逐格抄写成本。该步骤不会把行标记为 approved/corrected，仍需人工打开原图核对并改状态：

```bash
python3 scripts/build_package.py prefill-ln-score-distribution-review-suggestions \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --output staging/ln_score_distribution_2024_review_tasks_prefilled.csv
```

人工复核后，用 corrected 字段合并回 cleaned CSV。默认严格模式会拒绝未复核任务、重复主键和累计校验错误；`--allow-unresolved` 只用于迭代检查，不可导入 core：

```bash
python3 scripts/build_package.py apply-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --output cleaned/ln_score_distribution_2024.csv
```

复核推进过程中，可先生成 readiness audit，明确当前还差多少人工复核、严格合并是否可通过、cleaned CSV 是否已经满足 package 质量门禁：

```bash
python3 scripts/build_package.py audit-ln-score-distribution-readiness \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --cleaned-csv cleaned/ln_score_distribution_2024.csv \
  --report staging/ln_score_distribution_2024_readiness.json
```

OCR 或人工转录后的 `fa_fact_ln_score_distribution` CSV 必须再经过 `build-local`。该入口会校验分数范围、单分人数、累计排名，以及“上一累计 + 本分人数 = 当前累计”，避免错误转录进入 core：

```bash
python3 scripts/build_package.py build-local \
  --source-key ln_score_distribution \
  --table fa_fact_ln_score_distribution \
  --input cleaned/ln_score_distribution_2024.csv \
  --output-root exports \
  --package-id 2024_ln_score_distribution \
  --intake-manifest raw/ln_score_distribution/2024-06-25/_page_images_index.json
```

## 专业映射复核晋级

core 负责生成和维护人工复核队列，DataHub 只读读取其中已批准的结果，并输出完整 `fa_bridge_major_tdx` 数据包：

```bash
python3 scripts/build_package.py build-review-mapping \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-root exports \
  --package-id 2026_major_mapping_review
```

输出包仍需由 core 的 `backend/scripts/import_data_package.py` 导入。DataHub 不写 core 数据库。

## Outcome 采集队列

学校和专业 outcome 先生成采集任务队列，再由人工或后续采集器补证据 URL、摘录和指标值。队列由 `config/outcome_collection.json` 和 `config/outcome_metrics.json` 控制：

```bash
python3 scripts/build_package.py build-outcome-collection-plan \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-dir staging/outcome_collection \
  --school-limit 80 \
  --major-limit 80
```

该命令只读 core DB，默认按配置过滤普通类本科批，输出 CSV/JSON 采集计划，不是 data package，也不能导入 core。采集计划 CSV 预留 `metric_value/source_url/evidence_quote/metric_scope` 等证据列，人工或后续采集器补齐后，可先跑审计报告确认指标、状态和证据完整度：

```bash
python3 scripts/build_package.py audit-outcome-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --report staging/outcome_collection/outcome_collection_audit.json
```

采集任务经过人工核对并标记为 `verified/ready/collected` 后，再从采集表生成标准 outcome 数据包。该入口会先运行采集审计，再复用 `build-local` 的 schema、主键、metric key、单位和值域校验：

```bash
python3 scripts/build_package.py build-outcome-from-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-root exports \
  --package-id 2026_outcome_collection
```

## 政策表数据包

政策行业映射和规划兑现回测由 `config/policy_industry_map.json`、`config/policy_plan_history.json` 维护，不在 core 里硬编码生产：

```bash
python3 scripts/build_package.py build-policy-industry-map \
  --output-root exports \
  --package-id 2026_policy_industry_map

python3 scripts/build_package.py build-policy-plan-history \
  --output-root exports \
  --package-id 2026_policy_plan_history
```

builder 会输出 `manifest.json`、`quality_report.json` 和对应 `fa_` 表 CSV，后续仍由 core importer 导入。
