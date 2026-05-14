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

python3 scripts/build_package.py build-civil-service-signal-plan \
  --positions-csv cleaned/career_civil_service_posts/2026_scs_positions.csv \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-dir staging/career_source_plan/civil_service \
  --metric-year 2026

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

`career_civil_service_posts` 已登记国家公务员局下载资源 API。`download-scs-resources` 只下载配置筛选出的官方资源和 API 响应到 ignored `raw/career_civil_service_posts/{source_date}/`，manifest 记录 resource id、来源页、API URL、下载 URL、文件大小和 SHA-256。`parse-scs-position-workbook` 读取同一官方 ZIP 内 `.xls`，按 `config/career_data_sources.json.position_parser` 的列映射输出职位明细 CSV；`build-local` 可将该明细发布为 `fa_fact_civil_service_position` 数据包。`build-civil-service-signal-plan` 会把官方职位明细与职业目录做配置化关键词匹配，输出可复核的 `career_source_plan` 行，默认状态为 `in_progress`；人工确认后再用 `build-career-signal-from-source-plan` 生成 `fa_fact_career_signal`。该链路不会直接把职位匹配结果写入 core。真实 smoke：API 返回 8 个资源，配置筛出 1 个“中央机关及其直属机构2026年度考试录用公务员招考简章.zip”，下载 1,860,532 字节，SHA-256 为 `0055e7eb78906e2dcefb8e31963e2fd74baf980aa98893eebb54fd9d7f9176cb`；职位表解析出 20,714 条职位、招考人数合计 38,119；`2026_scs_civil_service_positions` 包 quality report 无错误、manifest 校验通过，core importer `--dry-run` 通过。职业信号匹配已把“数据/环境/农业/设计/电子/海洋”等宽词列入 `keyword_stopwords`，并改用更具体短语；当前用本地 core 73 条职业目录生成 44 条候选复核行，审计 `errors=[]`，top10 复核批次按 `review_batch.sort` 优先抽取公考岗位数最高候选。证据摘录会优先展示命中关键词更多、更具体的职位，并在摘录中标注 `命中：...`；如果关键词来自职位简介或备注，摘录会同步带出对应片段，避免人工复核只看到专业字段却看不到命中来源。真实 run 已小批复核 25 条高置信职业信号，生成 `2026_career_signal_civil_service_verified_v2` 和 `2026_career_score_civil_service_verified_v2` 标准包，两个包 manifest 校验、core importer dry-run 和本地实导均通过；19 条宽词或重复细分候选保持 `in_progress`。

上述 25 条复核结论已沉淀为 `config/career_source_review_seeds.json`，只记录职业、指标、年份、城市、状态和复核理由，不提交原始职位明细。薪酬调查和招聘快照类种子必须携带 `config/career_data_sources.json.audit.required_seed_copy_fields_by_source` 配置指定的 `metric_value/source_title/source_url/evidence_quote/metric_scope/source_date/availability_date`，用于从受控报告直接重放完整职业信号；国考职位表类种子继续由重新生成的职位匹配计划提供证据。`audit-career-source-review-seeds` 会按指标注册和来源策略校验年份整数、日期格式、`source_date <= availability_date <= reviewed_at`、HTTP(S) 来源 URL 和 `metric_value` 上下限，`apply-career-source-review-seeds` 可把通过审计的种子重放到重新生成的 `career_source_plan`；当前种子共 42 条，其中 25 条来自国考职位表、15 条来自宁波 2024 年薪酬调查、2 条来自广州 2025 年第四季度人力资源市场供求分析。

招聘平台报告有参考价值，但只进入职业和城市机会证据层。`config/career_data_sources.json.platform_source_policy` 把来源拆成公开研究报告、授权 API/终端导出、政府市场报告、受控页面快照和社区爬虫五档：智联 CIER/薪酬报告、BOSS 直聘研究报告、猎聘人才报告、脉脉人才迁徙报告等公开报告可作为 `fa_fact_career_signal` 候选；Wind/Choice 或平台企业级服务导出必须有授权、指标定义和文件 hash；非官方爬虫、未授权接口和反爬绕过实现不能进入标准包。平台样本偏差必须写入口径，且不能从招聘平台报告直接推导学校就业率或专业毕业去向。

薪酬调查第一批真实 run：以本地 core 的 73 条职业目录生成宁波 2024 年 `career_salary_survey` 采集计划 219 行，重放 15 条已核种子，覆盖计算机软件、计算机网络、信息安全、自动控制、通信 5 个职业的 `salary_p25/salary_median/salary_p75`。`audit-career-source-plan` 返回 `errors=[]`，生成 `2024_ningbo_salary_career_signal_v1`（`fa_fact_career_signal` 15 行）和 `2024_ningbo_salary_career_score_v1`（`fa_mart_career_score` 5 行），manifest 校验、core importer dry-run 和本地实导均通过。主项目已把 career signal/score 的导入模式调整为 `upsert_or_replace_package`，后续小批薪资、招聘或强度包不会覆盖已有国考信号。

招聘紧缺第一批真实 run：以本地 core 的 73 条职业目录生成广州 2025 年 `career_recruitment_snapshot` 采集计划 365 行，重放广州市人社局 2025 年第四季度公开供求分析中的 2 条已核种子，覆盖计算机网络、计算机软件 2 个职业的 `shortage_rank`。`audit-career-source-plan` 返回 `errors=[]`，生成 `2025_guangzhou_shortage_career_signal_v1`（`fa_fact_career_signal` 2 行）和 `2025_guangzhou_shortage_career_score_v1`（`fa_mart_career_score` 2 行），manifest 校验、core importer dry-run 和本地实导均通过。该批只有单一紧缺排行信号，职业评分保留 `below_minimum_signal_count`，表示它是增长侧证据，不是完整职业画像。

公开供求分析页不再只能手填种子。`apply-career-shortage-page` 会读取已 intake 到 ignored `raw/` 的 HTML，根据“排行前 N 个紧缺职业分别为...”句式提取职业排行，再回填到完整 `career_source_plan` 的 `shortage_rank` 候选行；默认状态为 `in_progress`，仍需复核种子或人工批次晋级后才能出包。真实广州页面解析出 30 个排行项，其中 2 个与当前 core 职业目录精确匹配；重放种子后审计为 `verified=2/todo=363/errors=[]`。

国考职位表还可派生专业 outcome，而不是只停留在职业信号。`build-major-outcome-from-civil-service` 会读取官方职位明细和 core 招生计划里的标准本科专业代码，按 `config/major_outcome_derivation.json` 的代码、专业类前缀和专业名规则聚合为 `fa_fact_major_outcome.civil_service_fit_score`。该分数是“方向适配信号”，口径明确包含本科专业、专业类和相近研究生专业要求，不等同于本科毕业即可直接报考。真实 run：用 20,714 条 2026 国考职位明细和当前 core 专业清单生成 `2026_major_civil_service_fit` 标准包 797 行，quality report 和 manifest 均无错误，core importer `--dry-run` 和本地实导均通过。

```bash
python3 scripts/build_package.py build-major-outcome-from-civil-service \
  --positions-csv exports/2026_scs_civil_service_positions/fa_fact_civil_service_position.csv \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --output-root exports \
  --package-id 2026_major_civil_service_fit \
  --metric-year 2026
```

`build-career-source-plan` 可选读取标准职业清单（`occupation_code/occupation_name/tdx_l2/tdx_l2_name`），把来源配置展开成“职业 × 指标 × 城市”的采集任务；`audit-career-source-plan` 检查状态、指标注册、证据 URL、摘录、来源日期和值域。采集执行时先用 `build-career-source-review-batch` 从总计划拆出小批 CSV，只补 `config/career_data_sources.json.review_batch.editable_columns` 允许的证据列，再用 `merge-career-source-review-batch` 回写总计划；职业、指标、城市、来源和目标表字段不会被批次覆盖。批次选择顺序同样由 `review_batch.sort` 配置，默认在同一来源内优先抽取 `metric_value` 更高、影响更大的待复核行，避免人工先处理低影响候选。`build-career-signal-from-source-plan` 只读取完整状态的职业信号行，并复用标准数据包质量门禁生成 `fa_fact_career_signal`。采集源、指标口径、评分权重维护在 `config/career_data_sources.json`；目标表契约维护在 `config/source_schemas.json`。招聘平台数据只允许通过公开授权 API、官方附件、人工导出或可复核快照进入 raw，不在本项目写反爬绕过逻辑。

当 core 已导入 `fa_dim_career_occupation` 时，`build-career-source-plan --core-db ...` 可只读读取职业目录生成采集任务，避免另存一份职业 CSV。真实 smoke 用本地 core DB 和 3 个职业目录行生成 12 条招聘快照任务；输出仍在 ignored staging/tmp，不是 data package。

真实 smoke：招聘快照来源生成 4 条职业信号采集任务，按 `limit_per_source=2` 拆出 2 条批次，原样合并 `updated_rows=0`，随后审计 `errors=[]`。输出均在 ignored `staging/`，不是 data package，也不会写 core。

`audit-career-source-coverage` 只审计配置覆盖，不采集数据。当前 8 个职业信号指标都已被至少一个来源承接：公考/编制指标来自官方职位表入口，招聘数量、紧缺排行、薪资和工作强度来自受控招聘快照或薪酬调查。该报告会标出哪些来源是官方入口、哪些仍需人工快照，避免后续把无证据口径直接写入 `fa_fact_career_signal`。

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

采集计划不是 data package，不能导入 core。只有证据列完整并通过审计的行，才允许由 `build-city-context-from-collection-plan` 转成 `fa_fact_city_economic_indicator`、`fa_fact_city_public_resource` 或 `fa_fact_city_ranking_signal` 标准包。审计会检查 metric 注册、单位和值域、`metric_year` 整数、HTTP(S) 来源 URL、`source_date/availability_date/reviewed_at` 日期格式以及 `source_date <= availability_date <= reviewed_at`，避免城市 GDP、医疗教育资源和城市榜单的坏证据进入评分层。排名信号的源选择和维度维护在 `config/city_context_collection.json`，当前只纳入连续发布、方法论可解释且维度交叉较少的来源：第一财经新一线城市商业魅力、智联招聘/泽平宏观人才吸引力、国家创新型城市创新能力、Nature Index 科研城市和 GaWC 世界城市网络连接度。

校区生活便利与成本评分不在 core 里直接计算。先由 DataHub 采集并复核校区定位、周边 POI、租售价格快照和城市/区县生活成本指标，再统一生成 `fa_mart_campus_living_score`：

```bash
python3 scripts/build_package.py build-campus-living-score \
  --location-input cleaned/school_location.csv \
  --poi-input cleaned/campus_surrounding_poi.csv \
  --housing-input cleaned/campus_housing_market.csv \
  --region-cost-input cleaned/region_living_cost.csv \
  --output-root exports \
  --package-id 2026_campus_living_score
```

通勤、商业便利、租房成本、医疗可达性和绿地环境的评分范围、POI 分组、租售指标和值域维护在 `config/campus_living_score.json`。构建 mart 前会先审计输入：校区 geocode 置信度和经纬度必须合法，POI `category_group` 必须注册，租售 `housing_metric_key/listing_type` 必须注册，区域生活成本 `metric_key` 和年份必须合法，指标值、来源 URL 和来源日期必须符合统一元数据门禁。租售价格只能作为带 `snapshot_date/source_date/sample_count` 的快照信号，不作为静态事实。

学校城市产业连接评分同样不在 core 里计算。先由 DataHub 复核学校招聘活动、科研产业连接、本地就业去向、城市产业园区和校区坐标，再统一生成 `fa_mart_school_city_industry_fit`：

```bash
python3 scripts/build_package.py build-school-city-industry-fit \
  --recruitment-input cleaned/school_recruitment_event.csv \
  --research-input cleaned/school_research_industry_link.csv \
  --employment-input cleaned/school_local_employment.csv \
  --zone-input cleaned/city_industry_zone.csv \
  --location-input cleaned/school_location.csv \
  --output-root exports \
  --package-id 2026_school_city_industry_fit
```

校园招聘、科研平台、本地就业、实习机会、产业园区距离和就业韧性的评分权重维护在 `config/school_city_industry_fit.json`。构建 mart 前会先审计输入：招聘 `event_type`、本地就业 `metric_key`、产业代码、metric 年份和值、园区经纬度、来源 URL 和日期顺序必须符合配置与元数据门禁。该 mart 用来表达学校是否已经接入所在城市的真实产业网络，不替代录取概率。

城市发展底盘评分不在 core 里直接计算。先由 DataHub 采集并复核 `fa_fact_city_economic_indicator`、`fa_fact_city_public_resource` 和 `fa_fact_city_listed_company_signal`，再统一生成 `fa_mart_city_development_score`：

```bash
python3 scripts/build_package.py build-city-development-score \
  --economic-input cleaned/city_economic_indicator.csv \
  --public-resource-input cleaned/city_public_resource.csv \
  --listed-company-input cleaned/city_listed_company_signal.csv \
  --output-root exports \
  --package-id 2026_city_development_score
```

GDP、人均指标、医疗资源、教育资源、轨道交通、公共服务和上市公司产业厚度的评分范围与权重维护在 `config/city_development_score.json`。构建 mart 前会先审计输入：`metric_key` 必须在配置中注册，`metric_year` 必须是整数，指标值必须可数值化，来源 URL 和来源日期必须符合统一元数据门禁。该 mart 只解释城市长期承载能力和机会密度，不直接决定录取分档。

专业到城市就业机会的评分不直接写在 core。先用 `fa_bridge_major_employment_role` 表达专业可进入的直接岗位、通用职能岗位、公共部门/升学路径，再用 `fa_fact_company_role_demand_signal` 表达企业和上市公司岗位需求，最后生成 `fa_mart_major_city_employment_fit`：

```bash
python3 scripts/build_package.py build-major-city-employment-fit \
  --role-input cleaned/major_employment_role.csv \
  --demand-input cleaned/company_role_demand_signal.csv \
  --output-root exports \
  --package-id 2026_major_city_employment_fit
```

评分档案、组件权重、岗位需求指标、上市公司计分和主角色选择权重维护在 `config/major_city_employment_fit.json`。构建 mart 前会先审计输入：角色适配分必须在 0-100，岗位需求 `metric_key` 必须在配置中注册，`metric_year` 必须是整数，需求值必须可数值化，来源 URL 和来源日期必须符合统一元数据门禁。这样会计、人力资源、法律等通用岗位不会被强行塞进单一行业结论，而是通过就业角色、城市岗位需求和上市公司适配进入同一张 mart。

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

当前配置下，2025 为官方远程文件可派生；2024 投档最低分是辽宁官网附件、一分一段仍用镜像 PDF 加官方图片页留痕；2023 投档最低分已升级为辽宁官网附件，一分一段仍用镜像 PDF 加官方图片页留痕；2022 投档最低分已补辽宁招生考试之窗官方附件直链，历史类 `2022ptlbk0720w01.xlsx`、物理类 `2022ptlbk0720l01.xlsx` 已核验 HTTP 200、文件类型和 SHA-256，`parse-ln-projection-score` 可解析 14,203 行。2022 一分一段官方图片源已在 `page_image_sources` 标记 `parse_mode=grid_image_table`，覆盖审计识别为 `official_image_derivable`；导入 core 前仍必须走 raw manifest、quality report 和 importer dry-run。覆盖审计的 summary 会把 2023/2024 归入 `blocked_or_review_years`，即使它们可用镜像派生，也不能被调度层误判为发布就绪。

已探测但不可晋级来源：辽宁日报传媒集团/辽沈晚报电子报 2023-06-25 与 2024-06-25 版面附件可访问，正确 PDF 路径为 `/lswbepaper/pc/att/...`，但 2024 A01-A08 未发现可文本解析的一分一段表；2023 A03/A05 虽有“成绩统计表”标题，PDF 文本不是完整逐分三列表，`parse-ln-score-distribution` 行数为 0。2023 A03/A05 的精确内容页与原图已登记为 `media_epaper_content_image` / `media_epaper_image` 候选，物理原图 sha256=`35e52fe2de11856db2f607edcbb598ffa16c860f41e580eb9929b2fddab6e5ee`，历史原图 sha256=`9424e1a2a93d6bf9bb30082f5e6f23c301ce4dc069c5e3ea204db044b55d3f6b`；这些图片只能进入 OCR/人工复核链路，不能直接晋级 `remote_files`。该来源保留在 `research_candidates`，避免后续重复探测或误晋级。

学信网 2023/2024 直接页面已登记为候选入口，但普通 HTTP 下载返回 JS 挑战或 HTTP 412，不能作为 `remote_files` 使用；后续只有在浏览器会话、稳定附件镜像或受控人工 intake 能提供可校验原始文件时，才允许进入解析和打包链路。

`probe-source-candidates` 支持按 `sources.json` 的 `probe.blocked_content_markers` 和 `probe.blocked_http_statuses` 识别反爬挑战页或挑战状态码；命中后状态为 `blocked_by_antibot`，不会被计入可访问来源。当前 `ln_score_distribution` 已把学信网直连返回的 HTTP 412 配为反爬阻断，真实探测结果为 19 个候选中 12 个可访问、7 个 `blocked_by_antibot`、0 个普通不可访问。

真实 smoke：2022 辽宁招生考试之窗官方投档最低分附件 + 2022 官方图片表格一分一段，已生成 `2022_ln_score_history_derived_official_projection_grid` 包，`fa_fact_ln_score_history` 14,203 行，quality report 无错误，manifest 校验通过，core importer `--dry-run` 通过。只读对账显示与当前 core 2022 本科批普通类存在代码体系和旧值差异，`safe_to_import_without_reconciliation=false`：package 14,203 行、core scoped 14,195 行、matched 6,363 行、package-only 7,840 行、core-only 7,832 行、different 3,712 行，另有 3,055 个同分同位次但专业代码不同的候选对。已生成 `staging/score_history_reconciliation_2022_official_projection_grid` 复核计划 16,963 行；自动规则、官方参考包和专业名参考已把 15,821 行推进到 reviewed，剩余 1,142 行仍需复核，并已生成 120 行小批；未完整复核前构建可导入包和 delete plan 均会被拒绝。

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
默认解析配置会同时纳入 `物理类`、`历史类`、`物理类特殊`、`历史类特殊` 四个 sheet；特殊 sheet 中的地方专项、预科、八省区协作等计划属于本科批同一对账范围，不能在 reconciliation 中误判为 core-only 待删除。

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
readiness 审计会校验复核结论和数据侧是否一致：`use_package_row` 必须有 package 侧数据，`keep_core_row` 必须有 core 侧数据，`exclude_row` 至少要能定位 package 或 core 侧主键，避免错误结论通过门禁。

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

审计之后可生成可复核任务表。任务状态、优先级、建议动作、匹配置信度和 0 分/0 位次占位识别由同一份 schema 配置维护，输出只是本地 review plan，不能导入 core。core-only 且 `min_score/min_rank` 均为 0 的旧占位记录会标成 `core_only_zero_placeholder`，便于确认后进入 delete plan；它仍不会自动删除 core 数据：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-plan \
  --core-db ../lifehack/backend/data/university.db \
  --package-dir exports/2023_ln_score_history_derived_pdf_mirror \
  --package-dir exports/2024_ln_score_history_derived_pdf_mirror \
  --output-dir staging/score_history_reconciliation_2023_2024
```

复核推进过程中先跑 readiness audit，确认还有多少任务未处理、哪些 review decision 不合规、复核结论是否和 package/core 数据侧一致、是否可以进入后续可导入包构建：

```bash
python3 scripts/build_package.py audit-score-history-reconciliation-plan \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --report staging/score_history_reconciliation_2023_2024/readiness_report.json
```

readiness audit 会阻断用错侧的复核结论：`use_package_row` 必须有 package 侧数据，`keep_core_row` 和 `covered_by_mapped_package_row` 必须有 core 侧数据，`map_package_to_core_major_code*` 必须同时具备 package/core 两侧数据，`exclude_row` 至少要能定位一侧主键。readiness report 同时输出 `pending_diagnostics`，按 issue type 汇总未完成任务的首选科目、core 候选数量和高频学校代码。这个字段用于决定下一批复核顺序，例如先处理单校集中缺口或多候选专业代码漂移，不需要另写一次性分析脚本。

对严格配置可判定的低风险任务，可以先应用 `config/source_schemas.json.audit.reconciliation.review.auto_decision_rules`，把匹配规则的任务标为 reviewed，但后续仍必须跑 readiness audit、package/delete plan 和 core dry-run。当前规则覆盖零占位删除候选、被官方参考包精确佐证的单侧行和值差异，以及官方 package 行精确匹配且只有一个 core 候选的专业代码漂移；多候选专业代码漂移仍必须人工复核：

```bash
python3 scripts/build_package.py apply-score-history-reconciliation-auto-decisions \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --output staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan_auto.csv \
  --report staging/score_history_reconciliation_2023_2024/auto_decision_report.json
```

如果官方投档最低分 cleaned CSV 保留了 `major_full`，还可以用当前 core 招生计划候选专业名做第二层参考。该步骤只处理 `major_code_drift_candidate`，且只在官方专业名与某一个 core 候选专业名规范化后完全一致时，把多候选收敛为单候选；包含匹配、多个命中或无命中的任务仍保持 pending：

```bash
python3 scripts/build_package.py apply-score-history-major-name-reference-decisions \
  --plan-csv staging/score_history_reconciliation_2022/score_history_reconciliation_plan_auto_reference.csv \
  --projection-csv cleaned/ln_projection_score_2022_official.csv \
  --core-db ../lifehack/backend/data/university.db \
  --core-plan-year 2026 \
  --output staging/score_history_reconciliation_2022/score_history_reconciliation_plan_auto_reference_name.csv \
  --report staging/score_history_reconciliation_2022/name_reference_decision_report.json
```

core-only 行如果与某个 package-only 行存在唯一精确专业名配对，应走成对决策，而不是把 core-only 简单放进 delete plan。`apply-score-history-pair-name-reference-decisions` 会把 package 行改为 `map_package_to_core_major_code`，把对应 core-only 行标为 `covered_by_mapped_package_row`；后者只表示会被映射 package 行 upsert 覆盖，不会进入删除迁移。若同名 package 侧已经是已复核 value drift，命令会使用 `map_package_to_core_major_code_delete_original_core`，让数据包写入目标 core 专业代码，同时由 delete plan 记录原 core 主键：

```bash
python3 scripts/build_package.py apply-score-history-pair-name-reference-decisions \
  --plan-csv staging/score_history_reconciliation_2022/score_history_reconciliation_plan_auto_reference_name.csv \
  --projection-csv cleaned/ln_projection_score_2022_official.csv \
  --core-db ../lifehack/backend/data/university.db \
  --core-plan-year 2026 \
  --output staging/score_history_reconciliation_2022/score_history_reconciliation_plan_auto_reference_name_pair.csv \
  --report staging/score_history_reconciliation_2022/pair_name_reference_decision_report.json
```

真实 smoke：对本地报考工作簿历史分数 reconciliation plan 应用 `core_zero_placeholder_to_delete_plan`，10,461 条任务中 10,184 条 `core_only_zero_placeholder` 被标为 `reviewed/exclude_row`，仍有 277 条非占位差异保持 `todo`，readiness audit 为 `package_ready=false`，说明自动规则只降低复核量，不越过剩余复核和写库门禁。随后用 2025 辽宁官网投档最低分 + 官方一分一段派生包作为 `--reference-package-dir`，277 条剩余差异全部被官方参考包确认：276 条 `core_only_unmatched` 标为 `keep_core_row`，1 条 `package_only_unmatched` 标为 `use_package_row`，readiness 变为 `package_ready=true`。

同一个 reviewed plan 会拆成两个产物：`build-score-history-from-reconciliation-plan --allow-core-exclude-rows` 只导出非删除记录，真实包 `2025_ln_score_history_workbook_reconciled_official_reference` 含 277 行，core importer `--dry-run` 通过后已实际导入；`build-score-history-delete-plan` 只导出 10,184 条 0 占位删除候选，core `apply_delete_plan.py` dry-run 显示 `matched_keys=10184/missing_keys=0`，随后以 migration id `2025-score-history-workbook-reconciled-official-reference-zero-placeholders` 执行并删除 10,184 行。删除前本地 core DB 已备份为 ignored 文件，最终主项目 Phase0 使用清洗后行数质量门槛全 PASS。

人工复核启动时可先抽一个小批次；默认每类数量由配置维护，也可用参数覆盖：

```bash
python3 scripts/build_package.py build-score-history-reconciliation-review-batch \
  --plan-csv staging/score_history_reconciliation_2023_2024/score_history_reconciliation_plan.csv \
  --output-dir staging/score_history_reconciliation_2023_2024/review_batch_initial \
  --limit-per-issue 20
```

对专业代码漂移和 core-only 批次，可以追加 `--projection-csv --core-db --core-plan-year` 输出只读参考列：官方专业名、官方候选专业名、core 候选专业名、匹配提示和建议候选代码。除 exact/contains 外，复核上下文还会按 `config/source_schemas.json` 的 `reference_context.token_overlap` 参数生成 `token_overlap` 提示，用共享专业名 token、最低相似分和最少共享 token 辅助识别“经济学类(含双学士…)”与“经济学类(经济学、…)”这类同专业族表达。manifest 也会输出按 issue type 细分的 `issue_hint_counts`、`issue_package_hint_counts`、`hint_combo_counts` 和 token-overlap 参数摘要，用于安排复核顺序和判断是否还有可配置化降噪空间。附加列和统计只服务复核判断，合并回完整 plan 时仍只写配置允许的复核列，不会自动修改 reconciliation 决策。

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

2023/2024 官方图片页已在 `config/sources.json` 配置普通类分组：1-4 张为历史类，5-8 张为物理类，后续体育/艺术图片不参与普通投档位次派生。分组只解决“哪些图属于哪张表”，不能替代质量审计；grid OCR 输出必须先和镜像 PDF、人工复核结果或其他基准 CSV 对账：

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

该审计只读 CSV，不写 core。若 `decision.reconciliation_required=true`，说明存在缺行、候选独有行、基准独有行或 `score_count/cumulative_rank` 差异，不能把候选来源晋级为标准包。

当前 grid OCR 解析器已把人数列多数字取值策略、累计人数突跳修复阈值放入 `config/sources.json`，用于处理官方图片中“本分人数/累计人数”被 OCR 粘连的行。真实复跑后，2024 官方图片候选从 1,020 行提升到 1,051 行，和 1,086 行镜像基准相比仍缺 35 行且 219 行数值不同；2023 官方图片候选从 946 行提升到 951 行，和 1,076 行镜像基准相比仍缺 125 行且 423 行数值不同。两年仍保持 `reconciliation_required=true`，不能晋级为标准包或替换镜像链路。

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

python3 scripts/build_package.py download-outcome-report-intake-assets \
  --intake-csv staging/outcome_report_intake/outcome_report_intake_plan.csv \
  --output staging/outcome_report_intake/outcome_report_intake_plan.downloaded.csv \
  --allow-failures

python3 scripts/build_package.py merge-outcome-report-intake-results \
  --report-source-csv staging/outcome_report_sources/outcome_report_source_plan.seeded.csv \
  --intake-csv staging/outcome_report_intake/outcome_report_intake_plan.downloaded.csv \
  --output staging/outcome_report_sources/outcome_report_source_plan.with_paths.csv \
  --report staging/outcome_report_intake/outcome_report_intake_merge.json

python3 scripts/build_package.py build-outcome-report-extraction-plan \
  --report-source-csv staging/outcome_report_sources/outcome_report_source_plan.with_paths.csv \
  --output-dir staging/outcome_report_candidates

python3 scripts/build_package.py run-outcome-report-extraction-plan \
  --plan-csv staging/outcome_report_candidates/outcome_report_extraction_plan.csv \
  --report staging/outcome_report_candidates/outcome_report_extraction_report.json
```

`config/outcome_report_sources.json` 保存已经确认的学校/专业报告来源种子，例如辽宁大学 2022 届毕业生就业质量报告，以及辽宁大学、吉林大学、辽宁工程技术大学、东北财经大学、沈阳工业大学、大连交通大学、沈阳师范大学、大连外国语大学、辽宁师范大学、渤海大学、大连大学、大连工业大学、大连民族大学 2023-2024 学年本科教学质量报告。先用 `audit-outcome-report-source-seeds` 检查种子 ID、必填字段、domain/report_scope 注册、年份整数、日期格式、`candidate_source_date <= availability_date`、HTTP(S) URL 和状态是否符合配置，再用 `apply-outcome-report-source-seeds` 合并到 report-source plan，状态变成 `candidate_found`。随后用 `build-outcome-report-intake-plan` 生成受控下载/本地登记清单；`download-outcome-report-intake-assets` 可读取该清单，从官方 HTML 页面中匹配报告附件、Chaoxing/engine2 云盘 zip 附件或直接下载文件，写入 ignored raw 路径并输出带 `local_report_path/intake_status=downloaded` 的 CSV；也可以人工补同样字段。报告下载常见部分成功、部分验证码或 manual intake，批处理可显式加 `--allow-failures` 继续后续 merge/extraction，但失败行仍保留 `download_status=failed` 和 `download_error`，不会被推进到 ready。再用 `merge-outcome-report-intake-results` 写回 report-source plan。只有本地报告路径真实存在且文件签名通过的行会被推进到 `ready`，`build-outcome-report-extraction-plan` 才会进入 ready；当前自动候选提取支持 PDF 和 OFD，验证码下载页、HTML 伪装 PDF 或只提供 `vsb_pdf_image_data` 图片页的报告会保持 blocked/manual intake，不进入候选提取。报告下载、受控 intake、本地文件路径、候选提取、人工核对和 outcome 数据包生成仍然是彼此独立的门禁。

真实 2024 学校 outcome smoke：以当前 core 前 200 所本科批学校生成 800 条学校指标任务和 42 条报告源任务；`report_source_plan.include_seeded_entities_beyond_limit=true` 会保留已配置的报告来源种子，即使默认 40 行上限会截掉对应学校。14 个配置种子中 13 个匹配当前 2024 计划，唯一未匹配的是辽宁大学 2022 就业质量报告；自动 intake 当前下载 7 份报告，6 份保留为验证码或图片页/manual intake，merge 后 7 行进入 `ready`，其中 6 份 PDF 和 1 份 OFD 进入候选提取。候选提取共生成 13 条 `needs_review` 候选：辽宁大学就业率/升学率、渤海大学就业率/升学率、大连交通大学就业率/升学率/国企去向比例、大连工业大学就业率/升学率/党政机关事业单位等去向比例、大连民族大学就业率、东北财经大学就业率。所有输出仍在 ignored `raw/`、`staging/`，未人工核对前不生成 outcome 数据包。

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

已经人工核对的 outcome 结论可以沉淀到 `config/outcome_collection_review_seeds.json`，再重放到重新生成的采集计划。种子只保存指标值、来源 URL、摘录、口径和复核说明，不提交 PDF 原文或 ignored staging 文件；`audit-outcome-collection-review-seeds` 会按 `config/outcome_metrics.json` 的 metric 注册检查指标合法性、完成状态、重复主键、metric_year 整数、HTTP(S) 来源 URL、日期格式、时间顺序、数值类型和值域上下限，避免 120%、负数、`2024.0` 年份、本地路径来源、非 `YYYY-MM-DD` 日期或复核早于来源可用日期这类错误进入后续计划：

```bash
python3 scripts/build_package.py audit-outcome-collection-review-seeds \
  --report staging/outcome_collection/outcome_review_seed_audit.json

python3 scripts/build_package.py apply-outcome-collection-review-seeds \
  --plan-csv staging/outcome_collection/outcome_collection_plan.csv \
  --output staging/outcome_collection/outcome_collection_plan.seeded.csv \
  --report staging/outcome_collection/outcome_review_seed_apply.json

python3 scripts/build_package.py audit-outcome-collection-plan \
  --plan-csv staging/outcome_collection/outcome_collection_plan.seeded.csv \
  --report staging/outcome_collection/outcome_collection_seeded_audit.json
```

学校或专业报告 PDF/OFD 可以先进入候选提取，不直接写回采集计划。`extract-outcome-report-candidates` 按 `config/outcome_metrics.json` 里的指标标签、aliases 和 `extraction.max_context_lines` 从报告文本中提取百分比/分值；报告把指标名和数值拆到相邻行时，候选提取会拼接同页向后上下文。输出仍是 `needs_review` 候选 CSV，候选值必须人工核对原文上下文后，才能复制到 outcome collection batch 的证据列：

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

真实 smoke：辽宁大学 2022 届毕业生就业质量年度报告 PDF 可提取 4 条体制内去向比例候选，其中本科毕业生国有企业去向比例 28.92% 已按 `civil_service_rate` 近似指标复核晋级，口径明确不含党政机关和事业单位；辽宁大学 2023-2024 本科教学质量报告 PDF 可通过相邻行上下文提取毕业去向落实率和升学人数比例候选；渤海大学 2023-2024 本科教学质量报告 PDF 可提取总体就业率和“升学 X 人，占 Y%”深造比例候选；大连交通大学 2023-2024 本科教学质量报告 PDF 可提取总体就业率、升学比例和国有企业签约比例候选；大连工业大学 2023～2024 本科教学质量报告 PDF 可提取就业率、考取研究生比例和党政机关/事业单位/部队/国家项目去向比例；大连民族大学 2023-2024 本科教学质量报告 PDF 可提取初次毕业去向落实率；东北财经大学 2023-2024 本科教学质量报告 OFD 可提取初次毕业去向落实率；大连大学 2023-2024 学年本科教学质量报告官方 PDF 可提取 2023 届本科毕业生年终毕业去向落实率。保研率、就业率、体制内去向比例和宽泛“升学”候选均需上下文门禁，避免把“推荐免试人数占攻读研究生人数比例”、“其中推免生但百分比属于考研总占比”、“师范生/非师范生分组落实率”、“省内就业比例”、“不含升学的就业地域比例”或“岗位晋升比例”误当成目标指标。输出均为本地 ignored staging CSV，且 `review_status=needs_review`，不会生成 outcome data package。

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

真实 smoke：上述辽宁大学单条 approved 候选合并后的采集计划已生成 `lnu_2022_outcome_candidate_merge_smoke_school` 标准包，`fa_fact_school_outcome` 1 行，quality report 无错误；manifest 已写入 `source_lineage`，包含采集计划路径、来源 URL、报告标题、指标和状态统计；`validate` 通过，core importer `--dry-run` 通过。学校 outcome 复核种子当前共 21 条已核指标：2024 学校 outcome 覆盖辽宁大学就业率/升学率、沈阳工业大学就业率、辽宁工程技术大学就业率/升学率、吉林大学就业率/深造率、辽宁师范大学就业率/深造率、渤海大学就业率/升学率、大连交通大学就业率/升学率/国企签约比例、大连工业大学就业率/考研比例/党政机关事业单位等去向比例、大连民族大学就业率、东北财经大学就业率 19 条；大连大学 2023 届就业落实率独立按 `metric_year=2023` 维护，不混入 2024 届口径；辽宁大学 2022 届国有企业就业比例独立按 `metric_year=2022` 维护。种子审计已前置校验来源 URL、年份、日期顺序和 metric 值域，当前 21 条 verified 种子 `errors=[]/warnings=[]`；2024 种子真实重放命中 19 条、更新 19 条、未命中为非 2024 年种子，重放后的 1200 行采集计划审计 `errors=[]/warnings=[]`；从该计划生成的 `ln_outcome_school_2024_seeded_v9_school` 包含 `fa_fact_school_outcome` 19 行，manifest 校验、core importer `--dry-run` 和本地 core 实导均通过，本地 core `fa_fact_school_outcome` 当前为 21 行。大连大学 2023 届种子已生成 `2023_dlu_school_outcome_seeded_v1_school` 包；辽宁大学 2022 届国企就业种子已生成 `2022_lnu_school_outcome_soe_seeded_v1_school` 包；两个包均为 `fa_fact_school_outcome` 1 行，manifest 校验、core importer `--dry-run` 和本地 core 实导均通过。

开源参考只作为设计和校验素材，不直接成为核心依赖：职业知识图谱可借鉴 `datawhalechina/team-learning-nlp` 的实体关系抽取流程，但本项目优先发布 DuckDB/Parquet 关系表；志愿预测可参考 `stonelf/China-college-application` 与 `Zeqing-Wang/Reco-PMW` 的历史波动和回测思路，但外部数据集必须先通过 license/source audit；招聘薪酬项目只吸收薪酬区间解析、岗位去重、分位数截尾和异常样本剔除等清洗规则，采集结果仍按 DataHub 候选、复核、标准包发布。

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
