# Roadmap

## Phase 0: 最小可运行项目骨架

目标：建立 FastAPI + Jinja2 最小可运行骨架，包括应用入口、首页、健康检查、基础 settings、基础日志、pytest 和项目元数据。

涉及模块：core, routers, templates, static, tests, documentation。

测试：app import 测试；`GET /health` 返回 200 和 `{"status": "ok"}`；`GET /` 返回 200。

验收标准：`pytest` 通过；目录骨架存在；不包含业务功能、数据库连接、外部 API 调用或旧项目源码。

禁止事项：禁止实现业务功能；禁止接数据库；禁止调用外部 API；禁止复制旧项目源码。

## Phase 1: 领域模型设计

目标：定义项目、论文、引用材料、证据、分类、复核和任务等核心概念。

涉及模块：models, schemas, documentation。

测试：模型约束测试；状态枚举测试；schema 校验测试。

验收标准：核心实体能表达第三方引用评价、证据位置、分类和复核状态。

禁止事项：禁止在模型层处理 HTTP；禁止加入外部 API 调用。

## Phase 2: 基础数据访问和项目管理

目标：实现项目、论文和引用材料的基础创建、读取、更新和列表能力。

涉及模块：repositories, services, routers, templates, SQLite。

测试：repository CRUD 测试；service 编排测试；router 表单/API 测试。

验收标准：用户能建立项目并登记目标论文和引用材料元数据。

禁止事项：禁止 router 直接写数据库；禁止 template 访问数据库。

## Phase 3: 普通论文分析 Session 创建和详情页

目标：用户可以从首页进入创建页面，输入目标论文 query，创建 `PaperAnalysisSession`，并进入详情页查看 query 和初始状态。

涉及模块：routers, services, repositories, schemas, templates, SQLite。

测试：创建页面 200 测试；POST 创建后 303 重定向测试；数据库存在 `PaperAnalysisSession` 测试；详情页显示 query 和 status 测试。

验收标准：`GET /paper-sessions/new` 返回表单；`POST /paper-sessions` 创建状态为 `created` 的 session；`GET /paper-sessions/{session_id}` 显示详情。

禁止事项：禁止 discover；禁止访问外部 API；禁止上传 PDF；禁止 LLM 分析；禁止 router 直接访问数据库。

## Phase 4: 本地任务系统 MVP

目标：任务进入数据库，`TaskRunner` 可以 claim 一个 pending 任务并执行；`discover_paper` handler 使用 `FakeCitationProvider` 写入 citing papers；页面可以创建 discover 任务并查看最近任务。

涉及模块：tasks, services, repositories, routers, providers, models, templates。

测试：enqueue task；`run_once` 成功后状态为 succeeded；handler 失败后状态为 failed；`discover_paper` 写入 citing papers；同一 session 不允许同时运行两个 discover_paper；任务状态 API 测试。

验收标准：`POST /paper-sessions/{session_id}/discover` 只创建任务不执行长任务；`GET /api/v1/tasks/{task_id}` 返回状态；runner 执行 fake discover 后写入 5 条 citing papers。

禁止事项：禁止 Redis/Celery/RQ；禁止真实网络；禁止 FastAPI 请求直接执行长任务；禁止接 LLM。

## Phase 5: PDF 上传、存储和文本抽取

目标：用户可以给某个 citing paper 上传 PDF，系统验证文件、保存 `PdfAsset` 元数据和本地文件，抽取文本到本地路径，并在 citing paper 页面显示 PDF 状态。

涉及模块：pdf, filesystem, services, repositories, routers, templates, SQLite。

测试：合法 PDF 上传；拒绝空文件；拒绝非 PDF；拒绝超大文件；抽取文本成功；抽取失败时 `extract_status=failed`；citing paper 页面显示 PDF 状态。

验收标准：PDF 存入 `var/pdf_assets/`；抽取文本存入 `var/extracted_text/`；SQLite 只保存 `PdfAsset` 元数据和路径；上传文件名不作为实际存储路径。

禁止事项：禁止自动下载 PDF；禁止把 PDF 二进制存进数据库；禁止使用用户上传文件名作为实际存储路径；禁止 router 直接访问数据库。

## Phase 6: Citation Analysis Schema、候选引用段定位和 Fake LLM 分析

目标：对已上传并抽取文本的 citing paper，定位 candidate spans，构造 citation anchor，使用 fake LLM 生成结构化 `CitationAnalysisResult`，校验输出并写入 `FulltextAnalysisResult` 和 `StrongEvidence`。

涉及模块：analysis, schemas, providers, tasks, repositories, templates。

测试：candidate span 定位；fake LLM 输出解析；grouped citation 不被标成强证据；strong evidence scoring；关键词高亮；analyze handler 生成结果和 evidence。

验收标准：`analyze_citation` task 能从 `extracted_text_path` 读取文本，生成结构化 analysis result；只有包含原文 `citation_text` 且通过本地评分阈值的 finding 会生成 `StrongEvidence`；详情页展示 citation_text、标签、stance、关键词和判断依据。

禁止事项：禁止接真实 LLM；禁止让 LLM 直接决定最终排序；没有原文 `citation_text` 的 finding 不得生成 `StrongEvidence`。

## Phase 6.5: 普通论文分析闭环验收与加固

目标：确认从创建 paper session 到生成 `StrongEvidence` 的最小闭环稳定可用，并补强 UI 状态、错误处理和集成测试。

涉及模块：routers, services, repositories, tasks, analysis, pdf, templates。

测试：完整闭环 integration test；无 PDF 显示 `need_pdf` 并拒绝 analyze；缺少 extracted text 时任务 failed；Fake LLM invalid JSON 时任务 failed；无 `citation_text` finding 不生成 `StrongEvidence`。

验收标准：用户可通过页面创建 session、discover fake citing papers、进入 citing paper、上传 PDF、enqueue analyze task，并在 runner 执行后看到 citation_text、aspect、stance、mention_type、highlight keywords、reason 和 score。

禁止事项：禁止接真实 LLM；禁止真实 OpenAlex/DBLP/Scopus；禁止学者分析；禁止自动 PDF 下载；禁止 Redis/Celery。

## Phase 7: 真实 LLM Provider 接入

目标：在不破坏 fake LLM 闭环的前提下，新增 OpenAI-compatible LLM provider，使 `analyze_citation` 可以通过配置选择 fake 或 real LLM。

涉及模块：providers, services, core, schemas, tasks, routers。

测试：成功 JSON；fenced JSON；无效 JSON 映射 `provider_schema_error`；timeout；401/403；429；fake provider 默认可用；`/health.json` 不显示 API key。

验收标准：默认配置仍使用 `FakeLlmProvider`；配置 `ACADEMIC_IMPACT_LLM_PROVIDER=openai_compatible` 后，可手动使用真实 OpenAI-compatible chat/completions 服务；provider 输出必须通过 `CitationAnalysisResponse` 校验；API key 不入库、不进日志、不出现在页面或 health 响应中。

禁止事项：禁止修改 evidence scoring 规则；禁止修改 candidate span 算法；禁止开发 scholar analysis；禁止测试访问真实 LLM 服务；禁止在 service 中直接发 HTTP 请求。

## Phase 8: 基础报告导出

目标：基于已有 `PaperAnalysisSession`、`CitingPaper`、`FulltextAnalysisResult` 和 `StrongEvidence` 生成可下载的 `report.md` 与 `structured.json`。

涉及模块：services, repositories, routers, filesystem。

测试：Markdown report golden 关键内容测试；`structured.json` 可被 `json.loads` 解析测试；无 evidence 时空报告测试；下载路由测试。

验收标准：用户能下载 Markdown 报告和结构化 JSON；报告包含目标 query、citing papers 数量、已分析数量、strong evidence 列表，以及每条 evidence 的 citing paper title、aspect、stance、evidence_strength、score、citation_text、highlight keywords 和 reason。

禁止事项：禁止重新调用 LLM；禁止重新分析 PDF；禁止访问真实网络；禁止把本地绝对路径暴露到报告或 structured export。

## Phase 9: 旧项目纯函数能力 Adapter 迁移

目标：在不破坏新项目架构的前提下，迁移旧项目中稳定、可测试、无 Web 依赖的纯函数能力，并统一包进 `app/legacy/adapters/`。

涉及模块：legacy/adapters, analysis, pdf, schemas, tests。

测试：每个 adapter 的 unit test；至少一个 `tests/fixtures/legacy/` 回归 fixture；禁止新 service 直接 import 旧项目 service/core/pipeline 的边界测试；Phase 8 完整闭环测试保持通过。

验收标准：迁移 PDF 文本抽取、candidate span 定位、LLM JSON/fenced/embedded JSON parser、DBLP ID 规范化、本地 PDF title/DOI/arXiv 匹配、evidence label/highlight keyword 规范化；adapter 对外输出新项目 schema/dataclass，不暴露旧项目 dict 结构。

禁止事项：禁止复制旧 `app/main.py`、`impact_core.py`、`scholar_core.py`、`run_pipeline.py` 大流程；禁止重新引入 `session.json` 作为主状态；禁止 adapter 发真实网络请求、读写数据库或直接操作 Web response。

## Phase 10: 学者分析 MVP

目标：在现有 paper analysis、task system、provider abstraction 和 legacy adapters 基础上，实现最小可用的 `ScholarAnalysisSession` 流程。本阶段只保存学者元数据、fake publications 和 citation edges，不做 scholar fulltext evidence dashboard。

涉及模块：models, providers, repositories, services, tasks, routers, templates, schemas, SQLite。

测试：创建 scholar session；fake publications 落库；`expand_scholar_citations` task；citation edges 落库；详情页展示；无真实联网边界测试。

验收标准：用户可以创建 scholar session；页面展示 fake publications；可以选择 publications 启动 citation expansion task；runner 完成后页面可看到 citation edge count；所有流程不访问真实网络。

禁止事项：禁止真实 DBLP/OpenAlex/Scopus；禁止完整 deep_analysis_queue；禁止 scholar fulltext analysis；禁止 person_candidates；禁止 highlight cards；禁止自动 PDF 下载；禁止复杂作者重名处理；禁止复制旧 scholar 大流程。

## Phase 11: 本地 PDF Library/Index

目标：为普通论文分析和学者分析提供统一的本地 PDF 匹配能力。系统从配置的本地论文库中扫描 `.pdf` 文件，建立索引，并按 DOI、arXiv id 或规范化标题匹配到 session 内的论文。

涉及模块：core, pdf, models, repositories, services, tasks, routers, templates, SQLite。

测试：local library disabled；fixture 目录 rebuild index；DOI/arXiv filename 提取；normalized title match；publication DOI/title 匹配；手动上传不被覆盖；页面请求不扫描；路径脱敏；paper/scholar session 匹配任务。

验收标准：未配置目录时系统正常运行并显示 `local library disabled`；配置 fixture PDF 目录后可通过 task 重建索引；paper session 和 scholar session 都能匹配本地 PDF；页面不暴露完整本地绝对路径。

禁止事项：禁止自动 PDF 下载；禁止接机构账号；禁止浏览器自动化；禁止扫描未配置路径；禁止 PDF 二进制入库；禁止覆盖手动上传 PDF；禁止 scholar deep analysis queue；禁止 strong evidence dashboard。

## Phase 11.5: PDF Library/Index 验收与匹配质量回归

目标：确认本地 PDF library/index 稳定、安全、可重复运行，并且不会影响手动上传 PDF。

涉及模块：pdf, services, repositories, tasks, routers, templates, exports, documentation。

测试：未配置目录正常运行；fixture rebuild；重复 rebuild 不累积重复 `PdfLibraryEntry`；DOI/arXiv 精确匹配优先于 title fuzzy；低于 threshold 不自动匹配；手动上传不覆盖；paper/scholar session 匹配；router 不直接扫描；页面和 JSON API 路径脱敏；report/export 不暴露本地路径；不扫描配置目录外文件；不删除本地 PDF；PDF 二进制不入库。

验收标准：`pytest` 通过；重复 rebuild 不产生脏数据；匹配统计与数据库记录一致；页面和 JSON API 不暴露完整本地路径。

禁止事项：禁止 Scholar deep analysis queue；禁止 strong evidence 新开发；禁止自动 PDF 下载；禁止真实机构账号；禁止浏览器自动化；禁止向用户暴露本地绝对路径。

## Phase 12: Scholar Deep Analysis Queue

目标：基于 `ScholarAnalysisSession` 中已有的 `CitationEdge`、`Publication`、`PdfAsset` 和本地 PDF 匹配结果，生成可排序、可筛选、可人工选择的 `DeepAnalysisQueue`。本阶段只生成和管理队列，不做全文 LLM 分析，不生成 `StrongEvidence`。

涉及模块：models, analysis, repositories, services, tasks, routers, templates, pdf。

测试：从 citation edges 构建 queue；重复 build 幂等；rebuild 保留用户 review；第三方引用优先级高于自引；manual/local/need_pdf readiness；ready/third_party 筛选；select/skip/review；build_queue 不扫描 PDF 目录。

验收标准：用户可以从 scholar session 构建 queue；重复 build 不产生重复 item；queue 页面可筛选 ready、need_pdf、third_party、selected；用户可 select、skip、mark important；`priority_score` 和 `priority_reasons_json` 可解释。

禁止事项：禁止运行 LLM 分析；禁止生成 `StrongEvidence`；禁止 highlight cards；禁止自动 PDF 下载；禁止真实 Scopus/Elsevier；禁止复杂作者重名处理；禁止 queue build 扫描 PDF 目录；禁止覆盖用户人工 review 状态。

## Phase 12.5: Scholar Queue 验收与筛选质量回归

目标：确认 `DeepAnalysisQueue` 稳定、可重复构建、可筛选、不会覆盖人工 review 状态，并能作为 Phase 13 全文分析的可靠输入。

涉及模块：models, analysis, repositories, services, routers, templates, pdf。

测试：同一 `CitationEdge` 最多一个 queue item；重复 build/rebuild 不重复且保留 `queue_status`、`user_review_status`、`user_note`；manual PDF 优先 local library PDF；ready、need_pdf、third_party、exclude_self、selected、skipped、important 筛选；important/rejected priority 变化；页面不暴露本地绝对路径；build_queue 不扫描 PDF library。

验收标准：`pytest` 通过；queue 可重复构建且不产生重复数据；queue 页面能筛选 ready、need_pdf、third_party、selected、important；`priority_score` 有清楚的 `priority_reasons_json`。

禁止事项：禁止运行 LLM；禁止生成 `StrongEvidence`；禁止 highlight cards；禁止自动 PDF 下载；禁止真实 Scopus/Elsevier；禁止覆盖用户 review 状态。

## Phase 13: Scholar Fulltext Analysis + StrongEvidence

目标：对 scholar deep analysis queue 中 selected 且 PDF ready 的 queue item 执行全文引用语义分析，生成 `FulltextAnalysisResult` 和 `StrongEvidence`，并提供 evidence 列表与人工 review 操作。

涉及模块：models, analysis, providers, services, tasks, routers, templates。

测试：selected ready queue item 分析测试；need_pdf 跳过测试；生成 `FulltextAnalysisResult` 和 `StrongEvidence` 测试；无 citation_text 不生成 evidence 测试；grouped citation 不被默认提升测试；关键词高亮测试；重复分析保留 review 测试；批量部分失败测试；evidence 页面筛选与 review 更新测试。

验收标准：`pytest` 通过；可以从 scholar queue 选择 ready items 执行 analyze；分析后能看到 evidence 列表、原文证据和关键词高亮；用户可以 accept、reject、mark important；need_pdf item 不导致任务崩溃。

禁止事项：禁止生成 highlight cards；禁止开发最终 scholar report；禁止自动下载 PDF；禁止真实 Scopus/Elsevier；禁止复杂作者重名处理；禁止让 LLM 直接决定 score；没有原文 `citation_text` 的结论不得保存为 `StrongEvidence`；禁止覆盖用户 evidence review 状态。
