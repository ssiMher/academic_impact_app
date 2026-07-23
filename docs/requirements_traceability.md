# Requirements Traceability

| 需求 | 优先级 | 对应模块 | 对应 Phase | 对应测试 |
| --- | --- | --- | --- | --- |
| 最小可运行 Web 骨架、首页和健康检查 | P0 | routers, templates, core | Phase 0 | app import 测试；`/health` 200 测试；`/` 200 测试 |
| 普通论文分析 session 创建和详情页 | P0 | routers, services, repositories, schemas, templates, SQLite | Phase 3 | 创建页 200 测试；POST 重定向测试；数据库落库测试；详情页展示测试 |
| 本地任务系统 MVP 和 fake discover 任务 | P0 | tasks, services, repositories, routers, providers, models | Phase 4 | enqueue 测试；runner 成功/失败测试；fake discover 写入 citing papers 测试；任务状态 API 测试；重复 discover 阻止测试 |
| PDF 上传、存储和文本抽取 | P0 | pdf, filesystem, services, repositories, routers, templates, SQLite | Phase 5 | 合法 PDF 上传测试；空文件/非 PDF/超大文件拒绝测试；文本抽取成功测试；抽取失败状态测试；页面 PDF 状态测试 |
| Citation analysis schema、候选引用段定位和 Fake LLM 分析 | P0 | analysis, schemas, providers, tasks, repositories, templates | Phase 6 | candidate span 测试；LLM parser 测试；grouped citation 弱评分测试；strong evidence scoring 测试；关键词高亮测试；handler 生成 evidence 测试 |
| 普通论文分析闭环验收与加固 | P0 | routers, services, repositories, tasks, analysis, pdf, templates | Phase 6.5 | 完整闭环 integration test；missing PDF/缺 extracted text 测试；invalid fake LLM JSON failed 测试；无 citation_text 不生成 evidence 测试 |
| OpenAI-compatible LLM Provider 接入 | P0 | providers, services, core, schemas, tasks, routers | Phase 7 | provider 成功 JSON 测试；fenced JSON 测试；无效 JSON schema error 测试；timeout/401/429 映射测试；fake provider 默认可用测试；`/health.json` API key 脱敏测试 |
| 外部引用列表导入 | P1 | models, services, routers, templates | 外部引用增强 | CSV 导入创建 citation edges 测试；DOI/title 去重测试；OpenAlex edge 匹配测试；import batch/row diagnostics 测试；导入引用进入深度分析队列测试；页面区分 OpenAlex 与外部导入数量测试 |
| 开放 PDF 自动发现与合法下载 | P1 | models, services, tasks, templates, pdf | PDF 获取增强 | arXiv/OA PDF 候选测试；HTML 登录页拒绝测试；合法 PDF 下载和抽取测试；ACM/IEEE requires_login 测试；queue item 绑定下载 PDF 测试；PDF discovery task summary 测试 |
| 受限 PDF 下载助手与本地 inbox | P1 | models, services, tasks, routers, templates, pdf | PDF 获取增强 | requires_login 下载助手测试；inbox 创建 PdfAsset 测试；hash 去重测试；DOI/title 匹配测试；低置信人工确认测试；绑定更新 queue PDF 状态测试；缺 PDF 下载清单导出测试；无 password/cookie 字段测试 |
| 建立项目、论文和引用材料基础管理 | P0 | models, schemas, repositories, services, routers, templates | Phase 1, Phase 2 | repository 单元测试；service 流程测试；router 表单/API 测试 |
| PDF 安全检查、存储和文本抽取 | P0 | pdf, filesystem, services, tasks | Phase 3 | PDF 安全策略测试；文本抽取 fixture 测试；异常文件测试 |
| 引用上下文定位 | P0 | analysis, pdf, services, repositories | Phase 4 | 关键词命中测试；上下文窗口测试；页码映射测试 |
| 关键词高亮 | P0 | analysis, schemas, templates | Phase 5 | 高亮纯函数测试；HTML 转义测试；页面渲染测试 |
| 模板化引用分类 | P0 | models, schemas, analysis, repositories, services | Phase 6 | 分类模板测试；分类建议测试；持久化测试 |
| 人工复核闭环 | P0 | services, repositories, templates, routers | Phase 8 后 | 复核状态流转测试；修改记录测试；权限边界测试 |
| 基础报告导出 | P0 | services, repositories, routers, filesystem | Phase 8 | `report.md` golden 关键内容测试；`structured.json` 可解析测试；无 evidence 空报告测试；下载路由测试 |
| 旧项目纯函数能力 adapter 迁移 | P1 | legacy/adapters, analysis, pdf, schemas | Phase 9 | LLM JSON parser adapter 测试；candidate span adapter 测试；PDF extract adapter 测试；DBLP normalize、本地 PDF 匹配、evidence normalize adapter 测试；legacy fixture 回归测试；禁止 service 直接 import 旧 core 测试 |
| 学者分析 MVP | P1 | models, providers, repositories, services, tasks, routers, templates | Phase 10 | scholar session 创建测试；fake publications 保存测试；expand citations task 测试；citation edges 保存测试；详情页测试；无真实联网测试 |
| 学者一键扩展引用并构建队列 | P1 | services, tasks, routers, templates | Phase 10 后增强 | expand_and_build 生成 citation edges 和 queue items 测试；无引用时明确提示测试；详情页一键按钮测试；高级按钮保留测试；空队列页面引导测试；组合任务阶段消息测试 |
| 学者分析 MVP 验收与边界加固 | P1 | models, providers, repositories, services, tasks, routers, templates | Phase 10.5 | scholar 完整闭环 integration test；publication/edge 幂等测试；空 publications 测试；空选择和缺失 session 错误测试；task failed error_message 测试；无真实联网边界测试 |
| 本地 PDF library/index | P1 | core, pdf, models, repositories, services, tasks, routers, templates | Phase 11 | disabled 状态测试；fixture rebuild index 测试；DOI/arXiv/title 匹配测试；手动上传不覆盖测试；请求线程不扫描测试；路径脱敏测试；paper/scholar session 匹配测试 |
| PDF library/index 验收与匹配质量回归 | P1 | pdf, services, repositories, tasks, routers, templates, exports | Phase 11.5 | 重复 rebuild 幂等测试；DOI/arXiv 优先级测试；低于 threshold 不匹配测试；PdfAsset sha256 复用测试；页面/JSON 脱敏测试；配置目录边界测试；不删除本地 PDF 测试；PDF 二进制不入库测试 |
| Scholar deep analysis queue | P1 | models, analysis, repositories, services, tasks, routers, templates | Phase 12 | queue build 测试；幂等测试；保留人工 review 测试；第三方/自引评分测试；manual/local/need_pdf readiness 测试；ready/third_party 筛选测试；select/skip/review 测试；禁止 build_queue 扫描 PDF 目录测试 |
| Scholar queue 验收与筛选质量回归 | P1 | models, analysis, repositories, services, routers, templates | Phase 12.5 | citation edge 与 queue item 计数测试；manual 优先 local PDF 测试；need_pdf/exclude_self/selected/skipped/important 筛选测试；important/rejected priority 测试；页面绝对路径脱敏测试；rebuild 保留 review/note/status 测试 |
| Scholar fulltext analysis + StrongEvidence | P1 | models, analysis, providers, services, tasks, routers, templates | Phase 13 | selected ready queue item 分析测试；need_pdf 跳过测试；FulltextAnalysisResult/StrongEvidence 生成测试；无 citation_text 不生成 evidence 测试；grouped citation 弱证据测试；关键词高亮测试；重复分析保留 review 测试；批量部分失败测试；evidence 页面筛选与 review 更新测试 |
| StrongEvidence 质量回归与人工复核闭环 | P1 | analysis, models, services, routers, templates, tests/golden | Phase 13.5 | golden evidence regression tests；must-not-miss 正向评价/first claim/detailed comparison 测试；weak/grouped 不晋升测试；self-citation 降权测试；third-party evidence 筛选测试；corrected_label/review 保留测试；quality summary 统计测试；important/accepted/false_positive/high_strength 页面筛选测试 |
| Highlight cards 与 Scholar report | P1 | models, analysis, repositories, services, routers, templates, filesystem | Phase 14 | accepted/important evidence 生成 card 测试；rejected/false_positive 不生成 card 测试；important 排序优先测试；card 必须链接 StrongEvidence 测试；用户编辑不覆盖测试；CSV/Markdown cards 导出测试；report.md/structured.json 导出测试；本地路径/API key 不泄漏测试 |
| Highlight cards 与 Scholar report 验收加固 | P1 | models, repositories, services, routers, templates, filesystem | Phase 14.5 | card requires StrongEvidence 测试；原文 quote 追踪测试；空原文不生成 card 测试；rejected/false_positive 排除测试；用户编辑与 sort_order 保留测试；report quote/citing paper/evidence reason 测试；structured JSON cards/evidence/export metadata 测试；导出路径/API key 脱敏测试；important/accepted/high_strength 排序测试；draft card 标记测试 |
| 模板系统增强 | P1 | models, repositories, services, analysis, routers, templates, reports | Phase 15 | builtin template 列表测试；启用/停用测试；custom template 持久化测试；模板影响 queue score 测试；priority reason 记录测试；prompt fragment 注入测试；evidence template matching 测试；disabled template 不生效测试；HighlightCard 按模板分组测试；evidence 页面显示匹配词测试 |
| 模板系统验收与端到端质量回归 | P1 | models, repositories, services, analysis, tasks, routers, templates, reports | Phase 15.5 | 模板端到端 integration test；fake scholar session 到 report 闭环测试；template_match priority reason 测试；disabled template 不进入 queue score 测试；disabled template 不进入 LLM prompt 测试；citation_text/prompt safety 断言；TemplateMatch/evidence 页面展示断言；HighlightCard 与 report 按模板分组测试；rebuild 保留 review/note 和手动 PDF 测试 |
| 真实 Provider 接入增强 | P1 | providers, core, services, tasks, routers, health, schemas | Phase 16 | DBLP pid normalize 测试；DBLP publication schema 映射测试；OpenAlex citing papers schema 映射测试；OpenAlex rate limit/timeout 测试；OpenAI-compatible success/embedded/invalid JSON/401 测试；provider health API key 脱敏测试；fake provider 默认测试；测试无真实联网扫描 |
| 任务状态与后台执行增强 | P1 | tasks, services, repositories, routers, templates | Phase 9 后 | 任务状态机测试；失败重试测试；任务列表测试 |
| 外部学术检索或元数据 provider | P1 | providers, services, schemas | Phase 10 后 | provider mock 测试；超时测试；无真实联网测试 |
| 引用证据去重与聚合 | P1 | analysis, services, repositories | Phase 11 后 | 去重规则测试；多来源聚合测试；人工覆盖测试 |
| 分类模板和报告模板管理 | P1 | templates, models, repositories, services, routers | Phase 12 | 模板 CRUD 测试；渲染测试；非法模板测试 |
| 复核历史和审计 | P1 | models, repositories, services, templates | Phase 12 | 历史记录测试；差异展示测试；回溯测试 |
| 基础质量评分 | P1 | analysis, services, schemas | Phase 13 | scoring 规则测试；grouped citation 弱证据测试；score rationale 入库和页面展示测试 |
| 多语言材料分析 | P2 | analysis, providers, schemas | Phase 13 后 | 多语言 fixture 测试；分词和匹配测试 |
| 作者消歧辅助 | P2 | providers, analysis, services, templates | Phase 13 后 | 候选线索测试；人工确认测试 |
| 高级可视化 | P2 | services, templates, schemas | Phase 13 后 | 数据聚合测试；页面快照测试 |
| 协作复核 | P2 | models, repositories, services, routers, templates | Phase 13 后 | 多用户状态测试；冲突处理测试 |
| 多格式导出 | P2 | services, templates, filesystem | Phase 13 后 | Word/PDF/表格导出测试；格式完整性测试 |
