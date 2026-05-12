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
  --intake-manifest raw/ln_score_distribution/2024-06-25/_page_images_manifest.json
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
