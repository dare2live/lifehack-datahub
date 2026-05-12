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

Phase 5 原型：已固化数据包契约和模块边界，并提供本地已清洗 CSV/TSV/XLSX 到 data package 的生成入口。下一步逐步接入辽宁招生计划、辽宁历史分数线、教育部专业目录等数据源。

## 本地数据包生成

```bash
python3 scripts/build_package.py build-local \
  --source-key ln_admission_plan \
  --table fa_dim_ln_admission_plan \
  --input raw/ln_admission_plan/2026_cleaned.csv \
  --output-root exports \
  --package-id 2026_ln_admission_plan
```

字段别名和 schema 在 `config/source_schemas.json` 维护。`raw/` 和 `exports/` 默认被 `.gitignore` 排除。
