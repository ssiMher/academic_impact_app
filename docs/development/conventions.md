# Development Conventions

## 开发边界

Academic Impact App 采用模块化单体。所有代码必须遵守层级边界，让业务逻辑可测试、可替换、可审计。

## 模块职责

| 模块 | 必须负责 | 禁止负责 |
| --- | --- | --- |
| routers | HTTP 请求、参数解析、响应、重定向、调用 service | 直接写数据库；直接调用 provider；写复杂业务逻辑 |
| services | 业务编排、事务边界协调、调用 repository/provider/analysis/pdf/tasks | 直接 `requests.get`；直接拼 SQL；渲染 HTML |
| repositories | 数据库查询、写入、事务和实体映射 | 处理 HTTP；访问网络；执行业务编排 |
| providers | 外部 API 访问、认证、重试、响应适配 | 直接写数据库；直接返回未清洗外部响应给 template |
| analysis | 关键词匹配、证据定位、分类建议、评价倾向和质量评分等纯分析逻辑 | 读写数据库；真实联网；依赖 Web 框架 |
| pdf | PDF 安全、存储、文本抽取、页码映射和位置匹配 | 决定复核结论；渲染页面；直接处理 HTTP |
| legacy/adapters | 迁移旧项目中稳定、可测试、无 Web 依赖的纯函数能力，并输出新项目 schema/dataclass | import 旧 Web/service/task 大流程；读写数据库；真实联网；操作 Web response |
| tasks | 任务状态、后台执行、失败记录、重试调度 | 承载复杂分析算法；直接解析表单；绕过 service 改数据 |
| schemas | 请求、响应、表单、服务输入输出的数据结构 | 访问数据库；调用 provider；隐藏业务副作用 |
| models | 持久化实体和领域对象 | 处理 HTTP；启动任务；访问外部 API |
| templates | 展示页面、报告预览和简单条件渲染 | 写复杂业务逻辑；访问数据库；执行分析 |

## 强制禁止事项

- 禁止 router 直接写数据库。
- 禁止 router 直接创建数据库连接。
- 禁止 service 直接 `requests.get` 或调用其他真实联网客户端。
- 禁止 analysis 访问数据库、文件系统或网络。
- 禁止 repository 调用 provider。
- 禁止 provider 写数据库。
- 禁止新 service 直接 import 旧项目 `impact_core.py`、`scholar_core.py`、`run_pipeline.py` 或旧 Web/service/task 大流程。
- 禁止 adapter 读写数据库、发真实网络请求或直接操作 Web response。
- 禁止测试真实联网。
- 禁止模板里写复杂业务逻辑。
- 禁止把 PDF 二进制内容存入 SQLite。
- 禁止绕过 service 直接从 template 触发业务变更。

## 测试约定

- provider 测试必须使用 mock、stub 或 fixture，不允许访问真实外部 API。
- analysis 测试应优先使用纯函数输入输出。
- pdf 测试应使用小型 fixture，并覆盖异常文件、安全拒绝和页码映射。
- repository 测试应覆盖事务、约束和典型查询。
- service 测试应验证模块编排和失败路径。
- router 测试只验证 HTTP 行为、参数校验和响应结果，不重复测试深层业务规则。

## 文档约定

- 新增 P0/P1/P2 需求时，必须更新 `docs/product_requirements.md`。
- 新增或调整模块边界时，必须更新 `docs/architecture.md` 和本文件。
- 新增功能时，必须更新 `docs/requirements_traceability.md`。
- 新增开发任务或阶段目标时，必须更新 `docs/tasks/roadmap.md`。
- 新增或调整 legacy adapter 迁移时，必须更新 `docs/migration/legacy_adapters.md`。
