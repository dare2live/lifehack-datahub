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

注意：派生的 `min_rank` 是最低分对应的一分一段累计人数，不是同分排序后的精确投档位次。`quality_report.warnings` 会保留 `rank_is_score_cumulative_rank`。2023/2024 成绩统计表在辽宁官方页面目前以图片发布，仍需后续图片解析或受控人工复核。

2023/2024 官方图片页可先用 `download-page-images` 采集原图并生成 manifest。manifest 兼容 `build-local --intake-manifest`，后续无论使用 OCR 还是人工转录，发布包都能追溯到原始图片 SHA-256：

```bash
python3 scripts/build_package.py download-page-images \
  --source-key ln_score_distribution \
  --output-root raw
```

真实 smoke 已验证该命令可从 2023 官方页面采集 20 张图、从 2024 官方页面采集 21 张图。

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

真实 smoke：2024 OCR JSONL 生成 1,861 条候选、650 条直接 parsed 行、194 条 inferred_score 行、88 条 inferred_row 行、680 条累计校验 OK；2023 OCR JSONL 生成 1,450 条候选、227 条直接 parsed 行、116 条 inferred_score 行、2 条 inferred_row 行、265 条累计校验 OK。`inferred_row` 使用同图同块锚点和连续累计规则补齐单数字行，参数由 `parser.ocr_table.infer_single_number_rows` 控制。该结果说明 OCR 候选仍需要人工复核或更强表格结构识别，不能跳过 `build-local` 质量闸门。

候选 CSV 可以继续转成可分派的复核任务表，优先级和建议动作由 `config/sources.json` 的 `parser.ocr_review.issue_actions` 维护：

```bash
python3 scripts/build_package.py build-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --output staging/ln_score_distribution_2024_review_tasks.csv
```

真实 smoke：2024 候选生成 1,181 条复核任务，失败原因分布为 `incomplete=803, duplicate_score=184, invalid_score=122, cumulative_mismatch=68, extra_tokens=4`；2023 候选生成 1,185 条复核任务，失败原因分布为 `incomplete=975, invalid_score=130, duplicate_score=49, cumulative_mismatch=31`。复核任务表只用于校对，不是 data package。

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

真实 smoke：2024 工作区生成 21 个图片批次、1,181 条待复核任务；2023 工作区生成 20 个图片批次、1,185 条待复核任务。未修改批次可无损合并回总表，`updated_rows=0`。

复核完成后，使用 review task 中的 `corrected_score/corrected_score_count/corrected_cumulative_rank` 合并出 cleaned CSV：

```bash
python3 scripts/build_package.py apply-ln-score-distribution-review \
  --candidate-csv staging/ln_score_distribution_2024_ocr_candidates.csv \
  --review-csv staging/ln_score_distribution_2024_review_tasks_merged.csv \
  --output cleaned/ln_score_distribution_2024.csv
```

默认严格模式会拒绝未完成复核任务、重复主键和累计校验错误。真实 smoke：未复核的 2024 review tasks 被严格模式拒绝；`--allow-unresolved` 仅输出 680 行部分清洗结果并报告 1,181 条 unresolved、35 条累计质量错误。未复核的 2023 review tasks 在 `--allow-unresolved` 下仅输出 265 行部分清洗结果并报告 1,185 条 unresolved、19 条累计质量错误。部分清洗结果不能导入 core，也不能作为正式 data package。

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
