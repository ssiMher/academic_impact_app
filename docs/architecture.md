# Architecture

## 架构概览

Academic Impact App 采用模块化单体架构。早期系统保持单一部署单元，避免过早拆分微服务；内部通过清晰模块边界隔离 HTTP、业务编排、数据访问、外部 provider、PDF 处理、分析逻辑、任务执行和页面模板。

模块化单体的目标是让系统易于本地开发、易于测试、易于替换局部实现。SQLite 作为早期持久化方案，适合单机部署和小团队验证；后续如需迁移到其他数据库，应通过 repository 层隔离影响。

## 分层职责

| 层/模块 | 职责 | 不负责 |
| --- | --- | --- |
| Web routers | 处理 HTTP 请求、参数解析、鉴权入口、响应格式和页面跳转 | 不直接写数据库，不包含复杂业务规则 |
| services | 编排业务流程，调用 repositories、providers、analysis、pdf、tasks 等模块 | 不直接调用外部 HTTP API，不直接拼接 SQL |
| repositories | 封装 SQLite 数据访问，负责查询、写入、事务和数据映射 | 不处理 HTTP，不调用外部 API，不放业务编排 |
| schemas | 定义请求、响应、表单和服务输入输出的数据形状 | 不执行业务逻辑，不访问数据库 |
| models | 定义持久化实体和领域对象，表达项目、论文、引用证据、复核状态等核心概念 | 不处理路由，不执行任务 |
| providers | 封装外部学术检索、元数据、OCR 或其他 API 调用 | 不绕过 service 写数据库，不把外部数据直接暴露给页面 |
| tasks | 管理任务状态、任务队列、后台执行和失败重试策略 | 不承载核心分析算法，不直接处理 HTTP 表单 |
| analysis | 执行纯分析逻辑，例如关键词命中、引用类型判断、评价倾向识别和证据质量提示 | 不读写数据库，不访问网络，不依赖 Web 框架 |
| pdf | 负责 PDF 安全检查、存储、文本抽取、页码映射和证据位置匹配 | 不决定业务复核状态，不直接生成页面 |
| legacy/adapters | 承接旧项目中已验证的纯函数能力，并转换为新项目自己的 schema/dataclass | 不复制旧 Web/service/task 结构，不读写数据库，不联网，不暴露旧项目 dict 结构 |
| templates | 渲染 HTML 页面和报告预览 | 不写复杂业务逻辑，不直接访问数据库 |
| filesystem | 管理上传文件、抽取文本、导出报告和临时文件路径 | 不决定业务语义，不绕过 pdf 或 service 层 |
| SQLite | 早期持久化存储，保存项目、论文、证据、任务、模板和复核数据 | 不作为跨模块共享状态的替代品 |

## 数据流

典型分析流程如下：

1. Web router 接收用户请求，例如创建项目、上传 PDF 或启动分析任务。
2. router 将参数转换为 schema，并调用 service。
3. service 编排 repository、pdf、analysis 和 tasks。
4. pdf 模块完成文件安全检查、存储和文本抽取。
5. analysis 模块基于抽取文本执行关键词匹配、证据定位和分类建议。
6. repository 将项目、文件、证据、分类建议和任务状态保存到 SQLite。
7. templates 通过 router 提供的数据渲染页面。
8. 用户在页面中复核证据，复核结果再次经 service 和 repository 持久化。

## 模块边界原则

- 所有 HTTP 入口必须经过 Web routers。
- 所有数据库读写必须经过 repositories。
- 所有外部 API 调用必须经过 providers。
- 所有可纯函数化的分析逻辑必须放在 analysis。
- 所有 PDF 安全、存储、抽取和位置匹配必须放在 pdf。
- 旧项目能力只能通过 `app/legacy/adapters/` 的纯函数 adapter 进入新项目。
- 所有任务状态和后台执行必须放在 tasks。
- templates 只负责展示，不承担复杂业务判断。

## SQLite 使用原则

SQLite 是早期系统的默认本地数据库选择。它用于保存结构化业务数据，而不是保存大型 PDF 二进制内容。PDF 和导出文件由 filesystem 管理，数据库只保存路径、状态、摘要和元数据。

SQLite 的访问必须被 repository 层封装。service 不应知道 SQL 细节，router 和 template 不应知道数据库连接存在。
