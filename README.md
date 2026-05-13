# LifeHack DataHub

独立数据工程项目，服务 `志途 LifeHack` 核心决策工作台。

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

## 职业数据链路

职业相关数据不放在 core 里硬编码。DataHub 先生成采集计划，再把受控清洗后的职业信号发布为 `fa_fact_career_signal`，最后加工为 `fa_mart_career_score`：

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

python3 scripts/build_package.py build-career-source-plan \
  --output-dir staging/career_source_plan_from_core \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --source-key career_recruitment_snapshot \
  --city 沈阳 \
  --metric-year 2026 \
  --occupation-limit 80

python3 scripts/build_package.py audit-career-source-coverage \
  --report staging/career_source_plan/career_source_coverage.json

python3 scripts/build_package.py audit-career-source-plan \
  --plan-csv staging/career_source_plan/career_source_plan.csv \
  --report staging/career_source_plan/career_source_audit.json

python3 scripts/build_package.py build-career-source-review-batch \
  --plan-csv staging/career_source_plan/career_source_plan.csv \
  --output-dir staging/career_source_plan/batch_001 \
  --limit-per-source 20

python3 scripts/build_package.py merge-career-source-review-batch \
  --plan-csv staging/career_source_plan/career_source_plan.csv \
  --batch-csv staging/career_source_plan/batch_001/career_source_review_batch.csv \
  --output staging/career_source_plan/career_source_plan_merged.csv \
  --report staging/career_source_plan/career_source_merge.json

python3 scripts/build_package.py build-career-signal-from-source-plan \
  --plan-csv staging/career_source_plan/career_source_plan_merged.csv \
  --output-root exports \
  --package-id 2026_career_signal_shenyang

python3 scripts/build_package.py build-career-score \
  --signal-input exports/2026_career_signal_shenyang/fa_fact_career_signal.csv \
  --output-root exports \
  --package-id 2026_career_score_shenyang
```

`career_occupation_catalog` 已配置中国就业网数字职业 HTML 表格种子来源，`parse-digital-occupation-catalog` 会解析职业编码和名称，并用 `config/career_data_sources.json.occupation_family_by_code_prefix` 补齐职业大类，随后通过标准 `build-local` 生成 `fa_dim_career_occupation` 包。

真实 smoke：远程下载已校验 SHA-256 并生成 `_remote_manifest.json`；HTML 解析出 73 条数字职业，`build-local --intake-manifest` 生成 `2022_digital_occupation_catalog` 标准包，quality report 无错误，manifest 校验通过，core importer `--dry-run` 通过。

`build-career-source-plan` 可选读取标准职业清单（`occupation_code/occupation_name/tdx_l2/tdx_l2_name`），把来源配置展开成“职业 × 指标 × 城市”的采集任务；`audit-career-source-plan` 检查状态、指标注册、证据 URL、摘录、来源日期和值域。采集执行时先用 `build-career-source-review-batch` 从总计划拆出小批 CSV，只补 `config/career_data_sources.json.review_batch.editable_columns` 允许的证据列，再用 `merge-career-source-review-batch` 回写总计划；职业、指标、城市、来源和目标表字段不会被批次覆盖。`build-career-signal-from-source-plan` 只读取完整状态的职业信号行，并复用标准数据包质量门禁生成 `fa_fact_career_signal`。采集源、指标口径、评分权重维护在 `config/career_data_sources.json`；目标表契约维护在 `config/source_schemas.json`。招聘平台数据只允许通过公开授权 API、官方附件、人工导出或可复核快照进入 raw，不在本项目写反爬绕过逻辑。

当 core 已导入 `fa_dim_career_occupation` 时，`build-career-source-plan --core-db ...` 可只读读取职业目录生成采集任务，避免另存一份职业 CSV。真实 smoke 用本地 core DB 和 3 个职业目录行生成 12 条招聘快照任务；输出仍在 ignored staging/tmp，不是 data package。

真实 smoke：招聘快照来源生成 4 条职业信号采集任务，按 `limit_per_source=2` 拆出 2 条批次，原样合并 `updated_rows=0`，随后审计 `errors=[]`。输出均在 ignored `staging/`，不是 data package，也不会写 core。

`audit-career-source-coverage` 只审计配置覆盖，不采集数据。当前 7 个职业信号指标都已被至少一个来源承接：公考/编制指标来自官方职位表入口，招聘数量、薪资和工作强度来自受控招聘快照或薪酬调查。该报告会标出哪些来源是官方入口、哪些仍需人工快照，避免后续把无证据口径直接写入 `fa_fact_career_signal`。

规范化语义层用于解决城市、学校、校区、专业、职业、行业、企业和指标在不同来源中的重复命名问题。实体与别名进入 `fa_dim_entity_registry/fa_bridge_entity_alias`，指标与别名进入 `fa_dim_metric_registry/fa_bridge_metric_alias`；清洗步骤、匹配置信度、模型入参门禁和输出策略维护在 `config/entity_normalization.json`。后续 builder 不应在业务逻辑里重复写“沈阳/沈阳市/辽宁沈阳”或“软件工程师/后端开发/程序员”这类临时清洗规则。

```bash
python3 scripts/build_package.py build-entity-normalization-registry \
  --region-profile-input exports/region_profile/fa_dim_region_profile.csv \
  --school-profile-input exports/school_profile/fa_dim_school_profile.csv \
  --major-catalog-input exports/major_catalog/fa_dim_major_catalog.csv \
  --career-occupation-input exports/career_occupation/fa_dim_career_occupation.csv \
  --policy-industry-input exports/policy_industry/fa_dim_policy_industry_map.csv \
  --output-root exports \
  --package-id 2026_entity_normalization_registry
```

数据更新治理用于确定数据什么时候重跑、怎么增量、旧数据如何覆盖、失败来源如何阻断依赖。`config/data_update_policy.json` 统一维护 `full_replace/partition_replace/primary_key_upsert/append_snapshot/manual_review_promote/derived_rebuild` 六类更新模式、非标数据晋级规则、来源有效性检测和串并行调度分组；运行元数据进入 `fa_meta_source_snapshot/fa_meta_source_health/fa_meta_update_run/fa_meta_update_run_step/fa_meta_nonstandard_review_queue`。非标数据只允许停留在 raw、候选和复核队列，复核通过后才发布标准包。

`build-data-update-plan` 会把更新策略拓扑排序成可审计执行计划，用于判断哪些源必须串行、哪些源可以同阶段并行、哪些衍生 mart 要等待上游数据包完成。该输出不是 data package，不抓取数据，也不写 core：

```bash
python3 scripts/build_package.py audit-data-update-policy

python3 scripts/build_package.py build-data-update-plan \
  --source-key city_development_score \
  --output-dir staging/update_plans/city_development
```

`build-data-update-readiness-plan` 在执行计划基础上展开每个来源的前置检查项，把增量策略、旧数据处理、promotion gate、有效性证据和失败修复方式写成 CSV。它仍然不抓取、不写库，只用于采集前门禁和人工排期：

```bash
python3 scripts/build_package.py build-data-update-readiness-plan \
  --source-key city_development_score \
  --output-dir staging/update_plans/city_development_readiness
```

`build-data-update-batch-plan` 在执行计划之上生成批次视图：同一 phase 内按 `execution_group` 分组，标明串行/并发、最大并发数、依赖闸门、失败策略和目标表锁。它回答“这批源是一起跑、排队跑，还是必须等上游完成后再跑”：

```bash
python3 scripts/build_package.py build-data-update-batch-plan \
  --source-key city_development_score \
  --output-dir staging/update_plans/city_development_batches
```

运行原则：`remote_file` 先验证 URL/hash/文件类型/source_date；`web_api` 先验证 endpoint、业务状态、响应 schema、配额和密钥不落盘；`manual_file` 先做受控 intake；`collection_plan` 先补齐证据 URL、摘录、日期、指标注册和值域；`derived_mart` 必须有上游 package lineage、评分档案、原因码和非空输出。任何阻断项未解决时，只能停留在 raw、候选、复核或 staging，不能发布标准包，也不能导入 core。

增量不是“直接改旧表”。DataHub 用 `state_management` 统一管理 snapshot_id、content_hash、partition state、supersede 和 delete policy：远程文件 hash 变化先生成新 raw snapshot 和差异报告；分区数据只替换命中分区；快照类数据只追加；非标网页/OCR/PDF/招聘和租售信息先进入候选与小批复核；删除已有 core 行必须由 reconciliation plan 产出 delete plan，且 core 侧先 dry-run。来源健康状态统一记录为 `healthy/degraded/unavailable/stale_source/schema_changed/hash_changed/quota_limited/manual_review_pending`，失败源只阻断依赖它的下游，保留上一次可用数据包。

城市上市公司信号由已复核的公司城市快照聚合，不直接读取或写入 ChunkyMonkey。字段别名、默认口径和聚合指标维护在 `config/city_listed_company_signal.json`：

```bash
python3 scripts/build_package.py build-city-listed-company-signal \
  --company-input cleaned/company_city_snapshot.csv \
  --output-root exports \
  --package-id 2026_city_listed_company_signal \
  --metric-year 2026 \
  --source-date 2026-05-13
```

输出 `fa_fact_city_listed_company_signal` 后，再作为城市发展底盘评分的上市公司产业厚度输入。

城市经济、公共资源和城市排名信号先生成目标城市清单，再展开采集计划并按证据完整度审计。目标城市清单从 core 招生计划只读抽取，并用 `fa_dim_region_profile` 或受控 CSV 补齐 `adcode`：

```bash
python3 scripts/build_package.py build-city-context-target-cities \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --region-profile-csv staging/region_profile/fa_dim_region_profile.csv \
  --output-dir staging/city_context

python3 scripts/build_package.py build-city-context-collection-plan \
  --city-input staging/city_context/target_cities.csv \
  --output-dir staging/city_context \
  --metric-year 2025

python3 scripts/build_package.py audit-city-context-collection-plan \
  --plan-csv staging/city_context/city_context_collection_plan.csv

python3 scripts/build_package.py build-city-context-review-batch \
  --plan-csv staging/city_context/city_context_collection_plan.csv \
  --output-dir staging/city_context/review_batches \
  --limit-per-domain 20

python3 scripts/build_package.py merge-city-context-review-batch \
  --plan-csv staging/city_context/city_context_collection_plan.csv \
  --batch-csv staging/city_context/review_batches/city_context_review_batch.csv \
  --output staging/city_context/city_context_collection_plan.reviewed.csv

python3 scripts/build_package.py build-city-context-from-collection-plan \
  --plan-csv staging/city_context/city_context_collection_plan.reviewed.csv \
  --output-root exports \
  --package-id 2026_city_context_{domain}
```

采集计划不是 data package，不能导入 core。只有证据列完整并通过审计的行，才允许由 `build-city-context-from-collection-plan` 转成 `fa_fact_city_economic_indicator`、`fa_fact_city_public_resource` 或 `fa_fact_city_ranking_signal` 标准包。排名信号的源选择和维度维护在 `config/city_context_collection.json`，当前只纳入连续发布、方法论可解释且维度交叉较少的来源：第一财经新一线城市商业魅力、智联招聘/泽平宏观人才吸引力、国家创新型城市创新能力、Nature Index 科研城市和 GaWC 世界城市网络连接度。

城市发展底盘评分不在 core 里直接计算。先由 DataHub 采集并复核 `fa_fact_city_economic_indicator`、`fa_fact_city_public_resource` 和 `fa_fact_city_listed_company_signal`，再统一生成 `fa_mart_city_development_score`：

```bash
python3 scripts/build_package.py build-city-development-score \
  --economic-input cleaned/city_economic_indicator.csv \
  --public-resource-input cleaned/city_public_resource.csv \
  --listed-company-input cleaned/city_listed_company_signal.csv \
  --output-root exports \
  --package-id 2026_city_development_score
```

GDP、人均指标、医疗资源、教育资源、轨道交通、公共服务和上市公司产业厚度的评分范围与权重维护在 `config/city_development_score.json`。该 mart 只解释城市长期承载能力和机会密度，不直接决定录取分档。

专业到城市就业机会的评分不直接写在 core。先用 `fa_bridge_major_employment_role` 表达专业可进入的直接岗位、通用职能岗位、公共部门/升学路径，再用 `fa_fact_company_role_demand_signal` 表达企业和上市公司岗位需求，最后生成 `fa_mart_major_city_employment_fit`：

```bash
python3 scripts/build_package.py build-major-city-employment-fit \
  --role-input cleaned/major_employment_role.csv \
  --demand-input cleaned/company_role_demand_signal.csv \
  --output-root exports \
  --package-id 2026_major_city_employment_fit
```

评分档案、组件权重、岗位需求指标、上市公司计分和主角色选择权重维护在 `config/major_city_employment_fit.json`。这样会计、人力资源、法律等通用岗位不会被强行塞进单一行业结论，而是通过就业角色、城市岗位需求和上市公司适配进入同一张 mart。

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

下载器会在每个 `raw/{source_key}/{source_date}/` 目录写入 `_remote_manifest.json`，记录原始文件 URL、SHA-256、大小、来源说明和目标表；后续 `build-local --intake-manifest` 可把这份 lineage 写进数据包 manifest。

如果某个来源还没有达到可晋级为 `remote_files` 的稳定程度，先放入 `research_candidates`，再用探测命令记录可访问性、HTTP 状态、文件大小和 SHA-256。探测报告只用于来源研究，不会写入 raw，也不能导入 core：

```bash
python3 scripts/build_package.py probe-source-candidates \
  --source-key ln_projection_score \
  --output staging/source_research/ln_projection_score_candidates.json
```

历史位次派生依赖“投档最低分 + 一分一段”两类输入。来源研究先跑覆盖审计，按年份标出官方文件、镜像文件、官方图片、候选链接和派生阻断项，不下载、不入库、不晋级候选：

```bash
python3 scripts/build_package.py audit-score-source-coverage \
  --report staging/source_research/score_source_coverage.json
```

当前配置下，2025 为官方远程文件可派生；2024 投档最低分是辽宁官网附件、一分一段仍用镜像 PDF 加官方图片页留痕；2023 两类输入均含镜像降级；2022 投档最低分已补辽宁招生考试之窗官方附件直链，历史类 `2022ptlbk0720w01.xlsx`、物理类 `2022ptlbk0720l01.xlsx` 已核验 HTTP 200、文件类型和 SHA-256，`parse-ln-projection-score` 可解析 14,203 行。2022 一分一段官方图片源已在 `page_image_sources` 标记 `parse_mode=grid_image_table`，覆盖审计识别为 `official_image_derivable`；导入 core 前仍必须走 raw manifest、quality report 和 importer dry-run。

高德地图数据走 Web API connector。API key 只从环境变量读取，不写入配置或 manifest；原始响应写入 ignored `raw/`，后续再由 parser/normalizer 生成标准包：

```bash
export AMAP_WEB_SERVICE_KEY=...

python3 scripts/build_package.py build-school-identity-review-plan \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --school-profile exports/2025_moe_school_profile/fa_dim_school_profile.csv \
  --output-dir staging/school_identity_review

python3 scripts/build_package.py build-school-identity \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --school-profile exports/2025_moe_school_profile/fa_dim_school_profile.csv \
  --review-plan staging/school_identity_review/school_identity_review_plan.csv \
  --output-root exports \
  --package-id 2026_school_identity

python3 scripts/build_package.py build-school-location-geocode-input \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --school-profile exports/2025_moe_school_profile/fa_dim_school_profile.csv \
  --school-identity exports/2026_school_identity/fa_bridge_school_identity.csv \
  --output-dir staging/school_location_geocode

python3 scripts/build_package.py audit-school-location-geocode-input \
  --plan-csv staging/school_location_geocode/school_location_geocode_plan.csv \
  --input-csv staging/school_location_geocode/amap_geocode_input.csv \
  --output staging/school_location_geocode/readiness_audit.json

python3 scripts/build_package.py fetch-amap-web-api \
  --source-key school_location_geocode \
  --operation geocode \
  --input staging/school_location_geocode/amap_geocode_input.csv \
  --address-column geocode_query \
  --city-column city \
  --output-root raw

python3 scripts/build_package.py fetch-amap-web-api \
  --source-key region_profile_geocode \
  --operation district \
  --output-root raw
```

学校地址 geocode 原始响应需要再转成标准包，才能进入 core：

```bash
python3 scripts/build_package.py build-school-location-from-amap-geocode \
  --raw-jsonl raw/school_location_geocode/2026-05-13/amap_web_api_geocode.jsonl \
  --raw-manifest raw/school_location_geocode/2026-05-13/_amap_web_api_geocode.json \
  --output-root exports \
  --package-id 2026_school_location_geocode
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

如果本地报考工作簿是多 sheet 形态，且同时包含招生计划和 2022-2025 历史分数/位次，先用配置驱动 parser 拆成标准 cleaned CSV。sheet 选择、批次、科类、字段别名、年份列和重复主键策略维护在 `config/ln_application_workbook.json`：

```bash
python3 scripts/build_package.py parse-ln-application-workbook \
  --input "/Users/dp/Documents/M/lifehack/26年报考数据/26年本科批报考数据8.27.xlsx" \
  --plan-output cleaned/ln_application_workbook_plan.csv \
  --score-output cleaned/ln_application_workbook_score_history.csv \
  --report cleaned/ln_application_workbook_report.json
```

生成的 cleaned CSV 仍不进入 Git。确认报告后，再分别用 `build-local --table fa_dim_ln_admission_plan` 和 `build-local --table fa_fact_ln_score_history` 生成数据包。

招生计划包导入实际 core 前，先做只读对账。审计范围、比较列和样本上限维护在 `config/source_schemas.json`，报告只输出差异，不写 core：

```bash
python3 scripts/build_package.py audit-admission-plan-package-against-core \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2026_ln_admission_plan \
  --report audits/admission_plan_2026_against_core.json
```

若审计报告仍有 `package_only_rows`、`core_only_rows` 或 `different_rows`，再生成本地复核任务表。任务类型和优先级也维护在 `config/source_schemas.json`，任务表不是 data package，不能导入 core：

```bash
python3 scripts/build_package.py build-admission-plan-reconciliation-plan \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2026_ln_admission_plan \
  --output-dir staging/admission_plan_reconciliation_2026
```

复核推进也走小批量任务表，批次只允许回写状态、复核结论、复核人、复核时间和备注：

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

已复核确认应删除 core 侧旧招生计划行的任务，单独生成删除迁移计划。该命令只输出待删除主键，不执行 SQL，也不是 data package：

```bash
python3 scripts/build_package.py build-admission-plan-delete-plan \
  --plan-csv staging/admission_plan_reconciliation_2026/admission_plan_reconciliation_plan_merged.csv \
  --output-dir staging/admission_plan_reconciliation_2026/delete_plan
```

当前 core 已有的清洗招生计划可先生成过渡 snapshot，避免核心库成为唯一数据落点。该包会标注 `legacy_core_snapshot`，不能替代后续官方系统/杂志导出的受控 intake：

```bash
python3 scripts/build_package.py build-admission-plan-snapshot \
  --core-db ../lifehack/backend/data/university.db \
  --output-root exports \
  --package-id legacy_ln_admission_plan_snapshot
```

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

审计之后可生成可复核任务表。任务状态、优先级、建议动作、匹配置信度和 0 分/0 位次占位识别由同一份 schema 配置维护，输出只是本地 review plan，不能导入 core。core-only 且 `min_score/min_rank` 均为 0 的旧占位记录会标成 `core_only_zero_placeholder`，便于人工确认后进入 delete plan；它仍不会自动删除 core 数据：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-plan \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2023_ln_score_history_derived_pdf_mirror \
  --package-dir exports/2024_ln_score_history_derived_pdf_mirror \
  --output-dir staging/score_history_reconciliation_2023_2024
```

复核推进过程中先跑 readiness audit，确认还有多少任务未处理、哪些 review decision 不合规、是否可以进入后续可导入包构建：

```bash
python3 scripts/build_package.py audit-score-history-reconciliation-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --report staging/score_history_reconciliation_2023_2024/readiness_report.json
```

人工复核启动时可先抽一个小批次；默认每类数量由配置维护，也可用参数覆盖：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-review-batch \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --output-dir staging/score_history_reconciliation_2023_2024/review_batch_initial \
  --limit-per-issue 20
```

复核者编辑 batch CSV 后，用 task_id 合并回完整 plan。合并只回写配置允许的复核列，不会修改主键、分数、位次等证据字段：

```bash
python3 scripts/build_package.py merge-score-history-reconciliation-review-batch \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --batch-csv staging/score_history_reconciliation_2023_2024/review_batch_initial/score_history_reconciliation_review_batch.csv \
  --output staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --report staging/score_history_reconciliation_2023_2024/merge_report.json
```

只有完整 plan 的 readiness audit 返回 `package_ready=true` 后，才能构建可导入的 `fa_fact_ln_score_history` 包：

```bash
python3 scripts/build_package.py build-score-history-from-reconciliation-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --output-root exports \
  --package-id 2024_2023_ln_score_history_reconciled
```

当前真实 2023/2024 队列仍会被拒绝：`pending=24478`，不会生成 package。`exclude_row` 只适用于排除 package-only 行；如果任务带有 core 侧证据，构建器会拒绝，因为当前 core importer 不能通过 CSV package 删除已有行。

对于已复核确认需要删除 core 侧历史位次行的任务，单独生成删除迁移计划。该命令只输出待删除主键，不执行 SQL，也不是 data package：

```bash
python3 scripts/build_package.py build-score-history-delete-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_merged.csv \
  --output-dir staging/score_history_reconciliation_2023_2024/delete_plan
```

当前真实未复核队列同样会被拒绝：`pending=24478`，不会生成 delete plan。

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
  --major-limit 80 \
  --metric-year 2025
```

该命令只读 core DB，默认按配置过滤普通类本科批，输出 CSV/JSON 采集计划，不是 data package，也不能导入 core。`--metric-year` 可覆盖配置默认年份，用于按 2022、2024 或 2025 等目标报告年份生成任务，并与 `config/outcome_report_sources.json` 中的报告来源种子匹配。先用报告源计划把同一学校/专业的多个指标聚合成“找报告”任务，避免重复搜索同一份就业质量报告或本科教学质量报告：

```bash
python3 scripts/build_package.py build-outcome-report-source-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-dir staging/outcome_report_sources

python3 scripts/build_package.py audit-outcome-report-source-plan \
  --plan-csv staging/outcome_report_sources/outcome_report_source_plan.csv \
  --report staging/outcome_report_sources/outcome_report_source_audit.json

python3 scripts/build_package.py build-outcome-report-source-review-batch \
  --plan-csv staging/outcome_report_sources/outcome_report_source_plan.csv \
  --output-dir staging/outcome_report_sources/batch_001

python3 scripts/build_package.py merge-outcome-report-source-review-batch \
  --plan-csv staging/outcome_report_sources/outcome_report_source_plan.csv \
  --batch-csv staging/outcome_report_sources/batch_001/outcome_report_source_review_batch.csv \
  --output staging/outcome_report_sources/outcome_report_source_plan.reviewed.csv \
  --report staging/outcome_report_sources/outcome_report_source_merge.json

python3 scripts/build_package.py audit-outcome-report-source-seeds \
  --report staging/outcome_report_sources/outcome_report_source_seed_audit.json

python3 scripts/build_package.py apply-outcome-report-source-seeds \
  --plan-csv staging/outcome_report_sources/outcome_report_source_plan.csv \
  --output staging/outcome_report_sources/outcome_report_source_plan.seeded.csv \
  --report staging/outcome_report_sources/outcome_report_source_seed_merge.json

python3 scripts/build_package.py build-outcome-report-intake-plan \
  --report-source-csv staging/outcome_report_sources/outcome_report_source_plan.seeded.csv \
  --output-dir staging/outcome_report_intake

python3 scripts/build_package.py merge-outcome-report-intake-results \
  --report-source-csv staging/outcome_report_sources/outcome_report_source_plan.seeded.csv \
  --intake-csv staging/outcome_report_intake/outcome_report_intake_plan.reviewed.csv \
  --output staging/outcome_report_sources/outcome_report_source_plan.with_paths.csv \
  --report staging/outcome_report_intake/outcome_report_intake_merge.json

python3 scripts/build_package.py build-outcome-report-extraction-plan \
  --report-source-csv staging/outcome_report_sources/outcome_report_source_plan.with_paths.csv \
  --output-dir staging/outcome_report_candidates

python3 scripts/build_package.py run-outcome-report-extraction-plan \
  --plan-csv staging/outcome_report_candidates/outcome_report_extraction_plan.csv \
  --report staging/outcome_report_candidates/outcome_report_extraction_report.json
```

`config/outcome_report_sources.json` 保存已经确认的学校/专业报告来源种子，例如辽宁大学 2022 届毕业生就业质量报告，以及辽宁大学、吉林大学、辽宁工程技术大学、东北财经大学、沈阳工业大学、大连交通大学 2023-2024 学年本科教学质量报告。先用 `audit-outcome-report-source-seeds` 检查种子 ID、必填字段、URL 和状态是否符合配置，再用 `apply-outcome-report-source-seeds` 合并到 report-source plan，状态变成 `candidate_found`。随后用 `build-outcome-report-intake-plan` 生成受控下载/本地登记清单；人工或脚本下载报告后，把 `local_report_path` 和 `intake_status=downloaded` 回填到 intake CSV，再用 `merge-outcome-report-intake-results` 写回 report-source plan。只有本地报告路径真实存在的行会被推进到 `ready`，`build-outcome-report-extraction-plan` 才会进入 ready；PDF 下载、受控 intake、本地文件路径、候选提取、人工核对和 outcome 数据包生成仍然是彼此独立的门禁。

采集计划 CSV 预留 `metric_value/source_url/evidence_quote/metric_scope` 等证据列，人工或后续采集器补齐后，可先跑审计报告确认指标、状态和证据完整度：

采集执行时不要直接多人编辑总计划。先按配置中的 `review_batch.limit_per_domain`、`selection_statuses` 和 `editable_columns` 拆出本地批次；人工、浏览器自动化或后续采集器只编辑批次中的证据列，再受控合并回总计划：

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

```bash
python3 scripts/build_package.py audit-outcome-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --report staging/outcome_collection/outcome_collection_audit.json
```

学校或专业报告 PDF 可以先进入候选提取，不直接写回采集计划。`extract-outcome-report-candidates` 按 `config/outcome_metrics.json` 里的指标标签、aliases 和 `extraction.max_context_lines` 从 PDF 文本中提取百分比/分值；PDF 把指标名和数值拆到相邻行时，候选提取会拼接同页向后上下文。输出仍是 `needs_review` 候选 CSV，候选值必须人工核对原文上下文后，才能复制到 outcome collection batch 的证据列：

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

真实 smoke：辽宁大学 2022 届毕业生就业质量年度报告 PDF 可提取 4 条体制内去向比例候选；沈阳工业大学 2023-2024 本科教学质量报告 PDF 可提取 1 条毕业去向落实率候选；辽宁大学 2023-2024 本科教学质量报告 PDF 可通过相邻行上下文提取毕业去向落实率、升学人数比例和推荐免试候选。输出均为本地 ignored staging CSV，且 `review_status=needs_review`，不会生成 outcome data package。

候选经过人工核对后，只把 `review_status=approved` 的行合并回完整采集计划。合并状态、目标状态和可回写列维护在 `config/outcome_collection.json` 的 `candidate_merge`，命令按 `domain, entity_code, metric_key, metric_year` 定位任务，不允许候选 CSV 篡改实体名称或优先级：

```bash
python3 scripts/build_package.py merge-outcome-report-candidates \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --candidate-csv staging/outcome_report_candidates/lnu_2022_candidates_reviewed.csv \
  --output staging/outcome_collection/outcome_collection_plan_with_report_candidates.csv \
  --report staging/outcome_collection/outcome_report_candidate_merge.json
```

真实 smoke：4 条辽宁大学报告候选中仅 1 条被手动标记为 `approved`，合并后只更新 1 行采集计划，状态变为 `verified`；随后 `audit-outcome-collection-plan` 返回 `errors=[]`、`completion_rate=1.0`。未批准候选保持隔离，不会进入打包链路。

采集任务经过人工核对并标记为 `verified/ready/collected` 后，再从采集表生成标准 outcome 数据包。该入口会先运行采集审计，再复用 `build-local` 的 schema、主键、metric key、单位和值域校验：

```bash
python3 scripts/build_package.py build-outcome-from-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output-root exports \
  --package-id 2026_outcome_collection
```

真实 smoke：上述辽宁大学单条 approved 候选合并后的采集计划已生成 `lnu_2022_outcome_candidate_merge_smoke_school` 标准包，`fa_fact_school_outcome` 1 行，quality report 无错误；manifest 已写入 `source_lineage`，包含采集计划路径、来源 URL、报告标题、指标和状态统计；`validate` 通过，core importer `--dry-run` 通过，未写入实际 core DB。

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
