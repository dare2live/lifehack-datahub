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

## 专业映射复核数据包

`major_mapping_review` source 从 core 的 `university.db` 只读读取：

- `fa_bridge_major_tdx`：现有正式映射。
- `fa_mart_major_mapping_review_queue`：已批准的复核候选。

DataHub 输出完整 `fa_bridge_major_tdx.csv`，而不是只输出增量，避免 core 侧导入时需要知道 DataHub 的内部合并逻辑。复核行不使用招生计划里的本地 `major_code_sample` 作为正式 `major_code`，而是生成 `REVIEW_NAME_<hash>`，防止学校本地专业代码污染 code-based lookup；推荐系统仍通过 `major_name` 命中这些映射。
