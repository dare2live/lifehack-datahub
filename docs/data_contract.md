# Data Package Contract

DataHub 向 core 发布的是不可变数据包。

## manifest.json

字段：

- `package_id`
- `built_at`
- `source_version`
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
  --package-id 2026_ln_admission_plan
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

## 证据域数据包

推荐和报告需要的学校、专业、政策证据由 DataHub 产出标准包，core 只消费：

- `fa_dim_school_profile`：高校基础画像，主键 `national_school_code`。
- `fa_bridge_school_identity`：辽宁本地院校代码到教育部学校标识码的桥表，主键 `local_system, local_school_code`。
- `fa_fact_school_outcome`：高校出口指标，主键 `school_code, metric_key, metric_year, source_url`。
- `fa_fact_major_outcome`：专业出口指标，主键 `major_code, metric_key, metric_year, source_url`。
- `fa_dim_policy_industry_map`：政策到 TDX 行业映射，主键 `tdx_l2`。
- `fa_dim_policy_plan_history`：十三五/十四五兑现回测，主键 `plan_period, tdx_l2`。

这些表的字段、别名、必填列、数字列维护在 `config/source_schemas.json`；来源状态维护在 `config/sources.json`。没有明确来源 URL 或证据摘录的主观判断不得发布为 outcome 数据包。

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

## 专业映射复核数据包

`major_mapping_review` source 从 core 的 `university.db` 只读读取：

- `fa_bridge_major_tdx`：现有正式映射。
- `fa_mart_major_mapping_review_queue`：已批准的复核候选。

DataHub 输出完整 `fa_bridge_major_tdx.csv`，而不是只输出增量，避免 core 侧导入时需要知道 DataHub 的内部合并逻辑。复核行不使用招生计划里的本地 `major_code_sample` 作为正式 `major_code`，而是生成 `REVIEW_NAME_<hash>`，防止学校本地专业代码污染 code-based lookup；推荐系统仍通过 `major_name` 命中这些映射。
