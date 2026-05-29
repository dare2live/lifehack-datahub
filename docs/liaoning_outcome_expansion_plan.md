# 辽宁学校/专业 outcome 扩面作战计划

更新时间：2026-05-17

## 1. 成功标准

本计划面向辽宁正常运营，不以“能抓到多少页面”为目标，而以家庭决策可用的学校出口和专业出口证据覆盖为目标。每个进入 core 的 outcome 指标必须回答：

- 学校出口是否可验证：毕业去向落实率、深造率、保研率、体制内/国企等去向口径是否来自学校官方报告或学校官方新闻。
- 专业出口是否可解释：专业就业率、专业深造率、考公适配分、考研友好度是否有来源、口径和可复核证据。
- 风险是否前置：不能只补录取分数，还要补“毕业后是否有可进入的真实机会”的证据链。

运营上以四个门禁定义完成：

- source gate：报告来源已进入 `outcome_report_source_plan`，状态为 `candidate_found`、`verified` 或 `ready`，并有标题、URL、来源日期和可用日期。
- intake gate：报告已下载或人工放入 `raw/outcome_report/`，失败项已分类并给出下一步。
- extraction gate：候选提取已产出候选行，或人工确认报告无对应指标并登记原因。
- review gate：人工复核后的指标值、摘录、口径、来源、日期完整，合并后 `audit-outcome-collection-plan` 无 errors 且 `publication_ready=true`，没有未消化的 source/semantic policy hints。

## 2. 当前基线

已读现有产物后，当前可用于扩面的基线如下：

| 产物 | 当前状态 | 运营含义 |
| --- | --- | --- |
| `staging/outcome_collection_2024_next/outcome_collection_plan.json` | 学校 800 行，覆盖 200 所学校 x 4 个指标 | 已有全量学校任务队列，但大部分仍是 `todo` |
| `staging/outcome_collection_school_2024_v12/outcome_collection_seeded_audit.json` | 23 行 verified，777 行 todo，完成率 2.88% | 最新学校 seed 已覆盖 11 个就业率、10 个深造率、2 个体制内/国企口径，保研率为 0 |
| `config/outcome_report_sources.json` | 已登记 16 个报告来源 seed | 这些是 P0 扩面的优先 source seed 池 |
| `staging/outcome_report_sources_2024_next/outcome_report_source_plan_seeded_with_syau_audit.json` | 42 行 source plan，14 行 candidate_found，28 行 todo，可进入 intake | P0 可从 14 个已确认来源开始，P1 再扩 28 个待找来源 |
| `staging/outcome_2024_report_intake/outcome_report_intake_plan.downloaded.json` | 8 行 intake 中 4 成功、4 失败 | 自动下载必须增加失败分类，失败不等于来源不可用 |
| `staging/outcome_2024_report_candidates/outcome_report_extraction_report.json` | 8 行中 3 ready、4 条候选 | 自动抽取只能作为候选，仍需要人工 review gate |
| `staging/outcome_collection_batch_smoke/outcome_collection_audit.json` | school 20 行、major 20 行 smoke 均为 todo | 专业 outcome 还处于 smoke 阶段，需先小批量验证口径 |

## 3. 优先级

### P0：已确认报告来源的辽宁重点学校

目标：把已登记 source seed 转化为可发布的学校 outcome 指标。

范围：

- 以 `config/outcome_report_sources.json` 中 2024 年辽宁学校本科教学质量报告为主。
- 优先学校包括：辽宁大学、沈阳工业大学、辽宁工程技术大学、沈阳农业大学、沈阳大学、沈阳师范大学、东北财经大学、大连交通大学、大连外国语大学、辽宁师范大学、渤海大学、大连大学、大连工业大学、大连民族大学。
- 吉林大学、长春工业大学可保留为跨省高频参照样本，但不计入辽宁正常运营覆盖率。

指标顺序：

1. `employment_rate`：最优先，直接影响“出口底盘”。
2. `postgrad_rate`：第二优先，直接影响升学路径解释。
3. `civil_service_rate`：第三优先，只在报告明确党政机关、事业单位、国有企业或单位性质比例时入库，必须在 `metric_scope` 写明是否为国企近似。
4. `keep_research_rate`：第四优先，只在报告明确推免/保研比例或分子分母时入库；普通“升学人数”不得代替保研。

P0 覆盖目标：

- source 覆盖：辽宁已确认来源学校 14 所中，至少 12 所完成 intake gate。
- 指标覆盖：每所至少完成 `employment_rate` 和 `postgrad_rate` 中 1 个，重点学校至少 2 个。
- 质量目标：所有 verified 行都有 `metric_value`、`source_url`、`evidence_quote`、`metric_scope`、`source_date`、`availability_date`。
- 阻断条件：source seed audit、collection audit 出现 errors；或来源不是学校官方报告/新闻；或指标口径无法区分本科/总体。

### P1：辽宁 top school 正常运营覆盖

目标：从“已确认来源样本”扩到辽宁本科批高频决策学校。

范围：

- 以 `outcome_report_sources_2024_next` 的 42 行学校 source plan 为第一批扩展池。
- 先覆盖辽宁本科批在招生计划中频繁出现、家长决策中高频比较的学校。
- 不按网络可抓取难易排序，而按“学校在辽宁志愿决策中的出现频率 + 出口解释价值 + 来源可信度”排序。

建议批次：

| 批次 | 范围 | 覆盖目标 | 退出条件 |
| --- | --- | --- | --- |
| P1-A | 42 行 source plan 中已有 `candidate_found` 的辽宁学校 | source ready 率不低于 80%，每校至少 1 个学校 outcome verified | 未分类下载失败清零，collection audit 无 errors |
| P1-B | 42 行 source plan 中仍为 `todo` 的辽宁学校 | 至少补齐 20 个 report source seed，进入 candidate_found | 每个 todo 都有“未找到/需人工/已找到”状态，不保留空白 |
| P1-C | 已有学校 outcome 但缺关键指标的学校 | `employment_rate` 覆盖率不低于 60%，`postgrad_rate` 覆盖率不低于 40% | 保研、体制内指标不强行补，缺失需登记原因 |

P1 验收指标：

- 学校覆盖率：`verified_school_count / target_school_count`。
- 核心指标覆盖率：`verified employment_rate or postgrad_rate / target_school_count`。
- 双指标覆盖率：`employment_rate and postgrad_rate both verified / target_school_count`。
- 来源有效率：`ready intake rows / candidate_found source rows`。
- 自动下载失败已分类率：`classified_failed_downloads / failed_downloads` 必须为 100%。

### P2：专业 outcome 小批量扩面

目标：先建立专业出口的可复核样板，再扩面到 top major，不把学校级数据误写成专业级数据。

范围：

- 从 `outcome_collection_batch_smoke` 的 major 20 行 smoke 开始，不直接全量铺开。
- 优先专业选择：辽宁招生中高频、就业解释风险高、家庭容易误判的专业。
- 第一组建议覆盖：计算机类、电子信息类、机械类、自动化类、临床医学、口腔医学、会计学、法学、汉语言文学、师范类相关专业。

专业指标顺序：

1. `civil_service_fit_score`：可由职位表/专业目录映射产生确定性评分，但必须保留映射规则和年份。
2. `exam_friendly_score`：可由考研延续性、研究生招生适配、跨考难度等配置化规则产生。
3. `employment_rate`：只接受专业/学院/专业类明确统计口径。
4. `postgrad_rate`：只接受专业/学院/专业类明确统计口径。

P2 覆盖目标：

- 第一批只做 10 个专业 x 2 个确定性指标，不超过 20 行 verified。
- 第二批再加入学校报告中明确给出专业分布的 `employment_rate` 或 `postgrad_rate`。
- 每个专业必须区分直接专业岗位、通用职能岗位、公共部门/升学路径，不能用单一行业映射解释全部就业。

## 4. 人工复核门禁

人工复核必须在候选合并前完成，复核人只把可被家庭解释的事实写入 seed 或 candidate review。

必填字段：

- `status`：只能在明确证据后置为 `approved`、`verified` 或 `ready`。
- `metric_value`：比例统一写 0 到 1 的小数；分数指标写 0 到 100。
- `source_title`：使用官方页面或报告标题。
- `source_url`：使用报告发布页优先；直链 PDF/OFD 可作为补充。
- `evidence_quote`：摘录必须包含指标名称、数值或分子分母，避免只摘标题。
- `metric_scope`：必须写清毕业届别、学历层次、统计时点和是否含出国/国企/事业单位等。
- `source_date`：报告或页面发布日期。
- `availability_date`：公开可获取日期；若只能使用 HTTP Last-Modified，需要在 notes 说明。
- `notes`：记录特殊口径、下载验证码、OFD、人工路径或不适用原因。

阻断规则：

- 招聘会、岗位数、人才市场活动、媒体报道不能直接发布为学校/专业 outcome。
- 学校总体毕业生数据不能直接当成本科数据，除非报告明确本科口径。
- 学院数据不能直接当成专业数据，除非 `metric_scope` 写明学院/专业类口径，且下游能接受该粒度。
- `civil_service_rate` 如果实际是国企签约比例，必须在 `metric_scope` 明确“不含党政机关和事业单位”。
- `keep_research_rate` 不能用升学率、考研率或研究生录取率替代。
- 自动抽取候选不得绕过人工复核直接进入 package。

## 5. 自动下载失败分类

自动下载失败需要分类登记，避免把“下载失败”误判成“来源无效”。

| 分类 | 判定 | 下一步 | 是否阻断 source |
| --- | --- | --- | --- |
| `captcha_required` | 下载页或附件需要验证码 | 保留 source seed，转 manual intake | 否 |
| `anti_hotlink_or_security_challenge` | 站点 security challenge、referer 校验或防盗链 | 使用发布页人工下载并登记 local path | 否 |
| `attachment_hidden_in_page` | 页面有效但附件链接需从 HTML/JS 中人工确认 | 人工补附件文件名和 local path | 否 |
| `ofd_or_unsupported_render` | OFD 或解析器暂不稳定 | 保留原文件，人工摘录或后续接入 OFD parser | 否 |
| `timeout_or_transient_network` | 超时、连接重置、偶发 5xx | 同批最多重试一次；仍失败转 manual intake | 否 |
| `not_report_content` | URL 打开后不是目标报告 | 回到 source gate 重新确认 | 是 |
| `missing_or_removed` | 官方页面或附件已删除且无可信替代 | 标记 `not_found`，记录查询路径 | 是 |
| `scope_mismatch` | 报告存在但不是目标年份、学历或学校 | 标记 `blocked` 或保留为非本批候选 | 是 |

每批下载报告必须输出：

- 总 source 行数。
- downloaded 行数。
- failed 行数。
- 每类失败数量。
- manual intake 待办清单。
- 被阻断 source 清单及原因。

## 6. 每批验收标准

### 批前 readiness

- 已有当前批次清单，且每行有 domain、entity、metric_year、report_scope 或 metric_key。
- 当前批次不与其他操作者编辑同一 review batch、同一 seed 文件或同一 staging 产物。
- 跑过 source seed audit 或 collection seed audit，且 errors 为空。
- 明确本批是否只做 source、intake、extraction、review 或 package，不跨门禁混做。

### 批中处理

- source 批：只登记来源，不下载、不提取、不发布。
- intake 批：只处理下载和 local path，不修改指标值。
- extraction 批：只产出候选，不把候选直接当 verified。
- review 批：只合并人工确认指标，所有口径写入 `metric_scope`。
- package 批：只消费已通过 audit 的 verified/ready 行。

### 批后验收

每批必须保留以下结果：

- source/intake/extraction/review 对应 report JSON。
- collection audit 或 source audit 无 errors。
- 新增 verified 行数、涉及学校/专业数、指标分布。
- 下载失败分类表，未分类失败为 0。
- 人工复核抽样记录：每 10 行至少抽 2 行回看原文；少于 10 行则至少抽 1 行。
- 残留风险：未覆盖学校、缺失指标、人工下载、OFD、口径不一致、需 core dry-run 的事项。

最低通过线：

| 批次类型 | 最低通过线 | 不通过处理 |
| --- | --- | --- |
| source 批 | errors 为 0，`candidate_found` 或明确终态比例 100% | 不进入 intake |
| intake 批 | 失败 100% 分类，阻断 source 单独列出 | 不进入 extraction |
| extraction 批 | ready 文件全部有提取结果或无候选原因 | 不进入 review |
| review 批 | verified 行 evidence 三件套完整率 100% | 不进入 package |
| package 批 | manifest、quality report、dry-run 另行通过 | 不导入 core |

## 7. 推荐执行节奏

第一周先做 P0，不扩大搜索范围：

- 处理 14 个辽宁已确认报告来源的 intake 失败分类。
- 对已 ready 的报告完成 `employment_rate`、`postgrad_rate` 人工复核。
- 将 v12 的学校 verified 从 23 行提升到 35 到 45 行。

第二周做 P1-A/P1-B：

- 对 42 行 source plan 清零空白状态。
- 对 `todo` 来源补 source seed 或标记 `not_found`/`blocked`。
- 建立每所学校的来源健康状态，不因为下载失败删除 source。

第三周做 P2 smoke：

- 只做 10 个 top major 的确定性指标样板。
- 优先把 `civil_service_fit_score` 和 `exam_friendly_score` 的规则、来源、lineage 固化。
- 不把学校级报告数值降粒度写成专业级 outcome。

## 8. 后续配置化建议

本次先形成作战计划，不修改现有采集命令。下一步可以新增 `config/outcome_operational_targets.json`，把以下内容配置化：

- 辽宁 target school 分层。
- top major 分层。
- 每批最小覆盖率。
- 自动下载失败分类枚举。
- 人工复核必填字段。
- 阻断规则和验收阈值。

配置化后，helper/test 可只读检查 staging report 是否满足运营门槛，不需要改 `release_bundle.py` 或 operational coverage audit 命令文件。
