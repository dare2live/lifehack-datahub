# Data Pipeline Operational Review

> Date: 2026-05-14
> Scope: Data acquisition, cleaning, transformation, packaging, model inputs, and core import.

## Current Conclusion

Data acquisition and cleaning are now the project's highest-leverage bottleneck. The recommendation UI, reports, and scoring services can only be trusted if DataHub provides stable, reviewable, repeatable evidence. Future work should treat DataHub as a governed data production system, not a collection of scripts.

The target architecture is:

```text
source registry
  -> update/readiness plan
  -> modular tool adapters
  -> raw snapshot + manifest
  -> parser/extractor output
  -> audit + review batch
  -> verified package
  -> core dry-run
  -> core import
  -> model/report input evidence packet
```

Tools can be modular. Scheduling, state, error handling, lineage, evidence gates, and publish decisions must be unified.

## Work Completed So Far

### Operational Coverage Gates

- `audit-operational-coverage` now audits the Liaoning admission-school universe from the core DB in read-only mode and emits P0 blockers when identity, profile, outcome, location, campus, or school-city-industry coverage is below the configured operational threshold.
- Missing-school queues now include `priority_rank`, `priority_score`, `plan_row_count`, `major_count`, `batches`, and `subject_cats`. This makes the next data-completion pass executable by admissions importance instead of a flat alphabetical missing list.
- Current real audit on the local core DB finds 1,590 Liaoning admission schools. Identity/profile cover 1,518 and miss 72; school outcome evidence covers 12 and misses 1,578; location, campus living, and school-city-industry fit tables are still absent from the core DB.
- The top identity/profile gaps by admissions priority are 国防科技大学, 陆军兵种大学, 华北电力大学(北京), 陆军工程大学, and 华北电力大学(保定). The top outcome gaps are 沈阳音乐学院, 星海音乐学院, 沈阳师范大学, 辽宁生态工程职业学院, and 浙江音乐学院.
- `build-school-identity-review-plan` can now consume `identity_missing_schools.csv` from the operational audit through `--priority-missing-csv`. The real local review plan now aligns to the 72-code operational identity gap, carries plan-row/major/batch/subject priority fields, and currently has 20 suggested MOE-profile candidates.
- `audit-school-identity-review-plan` is the read-only gate before rebuilding `fa_bridge_school_identity` from a review plan. It reports approved/blocking rows, duplicate local codes, approved rows without reviewed national codes, and returns non-zero until every row is approved and package-ready.
- `build-school-identity-review-batch` and `merge-school-identity-review-batch` now provide the controlled manual-review loop for the 72 identity/profile gaps. Reviewers work on priority-ordered batch CSVs; only review fields can be merged back into the full plan; the existing audit gate remains the final blocker before any identity package rebuild.
- `audit-school-identity-review-seeds` and `apply-school-identity-review-seeds` now let approved identity decisions move from ignored local batches into a git-tracked seed file. Seeds are audited for duplicate local school codes, legal review statuses, dates, and approved rows without reviewed national school codes before they can update a plan.

### CLI Coupling Reduction

- Codegraph identified `datahub/cli.py` as the largest remaining orchestration hotspot after the update and operational command split.
- Outcome evidence commands are now isolated in `datahub/commands/outcome.py`. The split moved command registration and dispatch only; builders, parsers, connectors, package contracts, and output semantics remain unchanged.
- Career evidence commands are now isolated in `datahub/commands/career.py`, covering career source plans, review batches, shortage pages, SCS resource/workbook parsing, career signal packages, career score packages, and civil-service-derived major outcome packages.
- Liaoning score-history and score-distribution commands are now isolated in `datahub/commands/score.py`, covering projection parsing, application workbook parsing, score distribution OCR/review workspaces, score-history packages, reconciliation, and source coverage audits.
- This establishes the repeatable boundary for future CLI reductions: split one command domain at a time, preserve existing command names and arguments, and validate with command help plus the full DataHub test suite.

### Data Contracts And Import

- Standard data packages now carry `manifest.json`, `quality_report.json`, table files, source lineage, hashes, row counts, and schema checks.
- Core importer validates manifests, hashes, schema registry, package metadata, dry-run, and reviewed reconciliation gates before writing `university.db`.
- Core and DataHub boundaries are clear: DataHub parses and packages; core imports packages and serves deterministic decision APIs.

### Source Governance

- `sources.json`, `source_schemas.json`, `data_update_policy.json`, and source-specific configs now define ownership, update mode, target tables, source status, parser expectations, and promotion gates.
- Remote files, manual files, Web API calls, page images, official attachments, OCR, outcome reports, career sources, city signals, and score history reconciliation all use controlled source plans or manifests.
- API keys are environment-only. Manifest records `key_env`, not secret values.

### Review And Reconciliation

- Historical score/admission reconciliation now uses full plans, review batches, readiness audits, delete plans, and core dry-runs.
- Outcome and career sources use collection plans, source batches, review seeds, audits, and standard packages.
- Verified seeds are reproducible from Git config; ignored raw/staging files are not the only source of truth.

### Evidence Layer

- School outcome, major outcome, career signal, career score, school-city-industry fit, campus living, city development, and policy signals are treated as distinct evidence packets.
- Recent source tier policies prevent recruitment fair/news/platform data from being misused as school graduation outcomes.

## Hardest And Slowest Links

### 1. Official Source Discovery

Why it is hard:

- Official pages move, attachment URLs are unstable, and page structures differ by school or city.
- Some school report attachments require CAPTCHA or use embedded image/PDF viewers.
- Search results often surface mirrors or third-party copies before the official source.

Current mitigation:

- `outcome_report_sources.json`, report-source plans, candidate-found statuses, manual intake, and report-intake merge gates.

Better solution:

- Add a generic web intake plan and static page extraction adapter.
- Keep official URL discovery and source evidence as separate tasks from metric extraction.
- Use Trafilatura-like extraction for public pages; use Firecrawl only as optional managed fallback; use Playwright when human session or CAPTCHA entry is required.

### 2. OCR And Image Tables

Why it is hard:

- Official score distribution pages may be image tables, not machine-readable tables.
- OCR errors often look plausible but shift ranks or counts.
- A cumulative count can be internally consistent but still wrong if rows were missed.

Current mitigation:

- Image download manifests, macOS Vision OCR, grid table parser, review workspace, strict readiness audit, cleaned CSV quality gates.

Better solution:

- Add per-source OCR profiles with expected row ranges and benchmark fixtures.
- Store OCR confidence and cell bounding boxes as first-class candidate evidence.
- Prefer official machine-readable files whenever a valid URL can be verified.

### 3. Legacy Core Reconciliation

Why it is hard:

- Local historic data and official package rows use different major codes and may have old zero placeholders.
- Score/rank value drift can come from source differences,同分累计口径, workbook errors, or stale local data.
- A successful package dry-run does not prove old data can be overwritten safely.

Current mitigation:

- Reconciliation plans, value drift diagnostics, per-year/subject/school filters, delete plans, and reviewed package readiness.

Better solution:

- Treat reconciliation as a reusable engine with strategy rules:
  exact key match, name-reference match, official-reference confirmation, placeholder cleanup, and manual review.
- Aggregate recurring issue types into dashboards so manual review starts with the highest-risk school/year/subject clusters.

### 4. Outcome Metrics

Why it is hard:

- Reports mix本科/研究生/全校口径、初次/年终口径、升学/深造/第二学士口径, and employment categories.
- Some reports state numerator/denominator but not the exact metric label.
- Recruitment news provides opportunity signals, not outcome rates.

Current mitigation:

- `outcome_metrics.json` aliases, blocked context rules, report candidates, review seeds, metric scopes, and source evidence tiers.

Better solution:

- Build a source-specific metric extraction test set from already verified reports.
- Require metric scope templates for common cases:
  initial employment, year-end employment, domestic postgraduate, overseas study, second bachelor, public sector, SOE, local employment.
- Use LLM only to propose candidate evidence quotes from raw report text, never to mark metrics verified.

### 5. Career And Recruitment Signals

Why it is hard:

- Job postings may be duplicated, stale, fake, or biased by platform audience.
- Platform reports are aggregated and sometimes promotional.
- Commercial APIs and terminals require authorization and cannot be assumed open.

Current mitigation:

- `career_data_sources.json`, source review seeds, platform source tiers, government market reports, civil-service positions, salary survey seeds, and minimum signal counts.

Better solution:

- Separate职业目录、岗位需求、薪资、紧缺度、工作强度、公共部门适配 into independent signal families.
- Require cross-source confirmation for high-weight signals.
- Keep platform-specific bias notes in `metric_scope` and `signal_contribution_json`.

## Tooling Lessons

### What To Borrow

- Great Expectations: checkpoint, validation result, data docs, and validation actions. We should borrow the pattern, not necessarily the full dependency immediately.
- Pandera: dataframe schema and grouped error reports. Useful for parser outputs and cleaned CSV validation.
- Dagster: asset graph, lineage, observability, and testability. Useful if source-key based CLI scheduling grows into many recurring assets.
- Prefect: Pythonic tasks, retries, result persistence, and cache keys. Useful for light orchestration before adopting a heavier asset framework.
- Trafilatura: local clean text extraction from HTML. Best first external candidate for public news and report pages.
- Firecrawl: optional managed Markdown/HTML/screenshot adapter, useful when local extraction costs more than the API call.
- Scrapy/Crawlee/Crawl4AI: use later only when a source becomes repeated, stable, and worth a crawler layer.

### What Not To Borrow

- Anti-bot bypass, CAPTCHA solving, login circumvention, reverse-engineered APIs, or community scrapers as production inputs.
- Any tool that writes directly to core tables.
- Any workflow where a model invents values, marks review status, or replaces official evidence.

## Unified Modular Scheduling Design

### Tool Adapter Interface

Every tool should behave like a small adapter:

```text
input plan + config + source_key
  -> output artifacts
  -> manifest
  -> status/error code
```

Required outputs:

- `raw_snapshot` for downloaded files, HTML, API JSON, images, OCR observations, or manual files.
- `candidate_csv` for extracted but unverified rows.
- `audit_report` for checks, counts, missing fields, status distribution, and blocking reasons.
- `data_package` only after readiness and review gates pass.

Forbidden outputs:

- direct core writes
- plain API keys
- verified metrics without evidence
- unreviewed deletes

### Unified Scheduler

The scheduler should read:

- `config/sources.json`
- `config/data_update_policy.json`
- `config/source_schemas.json`
- `config/pipeline_error_policy.json`

It should write:

- `fa_meta_update_run`
- `fa_meta_update_run_step`
- `fa_meta_source_health`
- `fa_meta_source_snapshot`
- local run JSON/CSV reports in ignored `staging/update_runs/`

Initial implementation can remain a CLI wrapper. A Dagster/Prefect-style orchestrator is only needed after the CLI wrapper becomes hard to operate.

### Error Policy

`config/pipeline_error_policy.json` now defines the first machine-readable policy:

- adapter layers
- unified scheduler contract
- severity levels
- error classes
- automatic actions
- manual actions
- LLM escalation policy
- external tool patterns to borrow

The important rule is deterministic first:

- Retry URL/network failures by config.
- Pause API groups on quota/key errors.
- Mark CAPTCHA/login as manual intake.
- Keep hash changes as new snapshots, not silent overwrites.
- Block package builds on schema drift, empty parse, missing evidence, invalid metrics, or pending reconciliation.
- Block core execute if dry-run fails.
- Stop immediately on secret leak risk.

## LLM Escalation Boundary

Allowed:

- generate source research queries
- summarize raw HTML/PDF context
- draft parser/config patches
- suggest schema mappings
- prioritize review batches
- update docs

Forbidden:

- bypass CAPTCHA/login
- invent metric values
- mark rows verified without source evidence
- execute core import
- write API keys to config/manifest
- delete core data without delete plan

When a task escalates to LLM, the handoff bundle must include:

- artifact paths
- error code
- source URL or manifest
- expected schema or metric key
- current audit/readiness report

## LLM Command Center

The user's proposal is feasible, but the right name is broader than 数据埋点.

Useful terms:

- 数据埋点: event instrumentation. It records what happened, such as a step start, failure, row count, or blocked status.
- 数据可观测性: metrics, logs, traces, quality results, freshness, volume changes, schema drift, and anomaly reports.
- 数据血缘: where each value came from, which source and parser produced it, which package imported it, and which downstream evidence packet uses it.
- 元数据驱动: source definitions, schemas, metrics, thresholds, aliases, rules, runbooks, and promotion gates live in config rather than hidden code.
- 控制平面: one layer reads metadata, schedules tools, records state, blocks unsafe actions, and routes incidents.
- Runbook-as-code: known problems and repair steps are stored as structured policy, not operator memory.
- AgentOps / LLM command center: an LLM can inspect artifacts during incidents and propose repairs, but cannot bypass deterministic gates.

For LifeHack, the best label is:

```text
metadata-driven data control plane with LLM-assisted incident response
```

Chinese working name:

```text
元数据驱动的数据控制平面 + 大模型应急指挥中心
```

The command center should know every source, parser, schema, metric, pitfall, and runbook as small "knowledge cells":

- source card: source owner, official channel, update cadence, failure modes, manual intake steps
- adapter card: tool input, output, side effects, retry behavior
- schema card: table primary key, required columns, load mode, validation rules
- metric card: unit, value range,口径模板, blocked contexts
- pitfall card: symptom, root cause, detection rule, remediation
- runbook card: error code, severity, first response, verification command, handoff requirements

The LLM command center may:

- diagnose failures from manifests and audit reports
- rank repair options
- draft parser/config patches
- propose review batch priorities
- write operator runbooks
- summarize lineage and residual risk

It may not:

- mark rows verified
- invent metric values
- publish packages
- execute core imports
- execute delete plans
- bypass CAPTCHA/login
- store secrets

This design keeps deterministic data production as the default and uses the model only when the system has enough structured context for a bounded intervention.

## Near-Term Build Plan

1. Build `web_intake_plan` and static HTML snapshot adapter.
2. Add optional Trafilatura extraction behind a feature flag or optional dependency.
3. Aggregate readiness reports into a single update-run report.
4. Add a source-health writer for failed/skipped/blocked steps.
5. Add a small run wrapper that executes modular tools from `data_update_policy` and `pipeline_error_policy`.
6. Add LLM handoff bundle generation for blocked rows that are eligible for model help.

## Operating Standard

No data should reach recommendation inputs unless it has:

- source registry entry
- raw or controlled source manifest
- parser/audit output
- schema and metric registration
- review or readiness status
- quality report
- package manifest
- core dry-run evidence
- lineage in the final fact or mart table

This is stricter than ordinary scraping, but it is necessary because the product is making education and career decisions for families.

## 辽宁运营覆盖审计

`audit-operational-coverage` 是只读审计命令，用 core 本地主库里的 `fa_dim_ln_admission_plan` 去重学校作为辽宁招生学校全集，检查以下运营证据表是否覆盖这些学校：

- `identity`: `fa_bridge_school_identity`
- `profile`: `fa_dim_school_profile`
- `outcome`: `fa_fact_school_outcome`
- `location`: `fa_dim_school_location`
- `campus`: `fa_mart_campus_living_score`
- `city_industry`: `fa_mart_school_city_industry_fit`

示例：

```bash
python3 -m datahub.cli audit-operational-coverage \
  --core-db /Users/dp/Documents/M/lifehack/backend/data/university.db \
  --report staging/audits/ln_operational_coverage.json \
  --missing-dir staging/audits/ln_operational_missing
```

命令使用 DuckDB `read_only=True` 连接 core DB，不采集来源、不构建包、不导入 core、不修改 staging/exports 大产物。报告输出每个覆盖域的覆盖学校数、缺口学校样例、覆盖率和 P0 blockers；存在 P0 blockers 时 CLI 返回非零状态。

传入 `--missing-dir` 时，会为每个覆盖域输出一个 `*_missing_schools.csv`，字段为 `school_code, school_name, coverage_area, review_status, notes`。这些 CSV 是后续人工分派、source seed 扩面、DataHub 批处理和 core 缺口解释的输入，不是 data package，不能直接导入 core。

## 运营数据组合评估

`assess-operational-data-portfolio` 用 `config/operational_data_portfolio.json` 定义的数据域清单，结合覆盖审计结果，把数据分成五类：

- `required_available`：正常运营必需，且通过覆盖/readiness 后可正式使用。
- `required_unavailable`：正常运营必需，但当前缺表、覆盖不足、复核未清或短期无法获取。
- `easy_but_underused`：相对容易获取或已存在，但当前产品使用深度不足。
- `optional_enhancement`：增强体验或差异化，不阻断上线。
- `not_for_formal_recommendation`：只能做候选、smoke 或审计，不得进入正式推荐。

示例：

```bash
python3 -m datahub.cli assess-operational-data-portfolio \
  --coverage-report staging/audits/ln_operational_coverage.json \
  --report staging/audits/ln_operational_data_portfolio.json
```

该评估用于回答“哪些数据必须使用、哪些必须但暂时无法获取、哪些易获取但使用不足、哪些不能进正式推荐”。它不采集、不导入、不改变 core；如果 P0 必需数据仍不可用，CLI 返回非零状态。
