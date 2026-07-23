# Feature Workflow

## 标准顺序

新增功能必须按以下顺序推进：

1. 需求说明
2. 数据模型
3. schema
4. repository
5. service
6. task
7. router/API
8. template/export
9. tests
10. docs

这个顺序的目的不是制造流程负担，而是让每个功能从“为什么做”走到“如何存储、如何输入输出、如何编排、如何展示、如何验证”。如功能不需要某一层，必须在 feature spec 中明确说明原因。

## 阶段要求

| 阶段 | 输出 | 检查点 |
| --- | --- | --- |
| 需求说明 | 用户目标、使用场景、P0/P1/P2 范围 | 是否能映射到需求追踪矩阵 |
| 数据模型 | 领域实体、状态、关系、约束 | 是否表达复核、证据和来源 |
| schema | 请求、响应、表单和服务输入输出 | 是否避免泄漏数据库细节 |
| repository | 查询、写入、事务和数据映射 | 是否只负责数据库 |
| service | 业务编排和失败处理 | 是否没有直接联网或 SQL |
| task | 后台执行和任务状态 | 是否有可测试状态流转 |
| router/API | HTTP 行为和错误响应 | 是否只调用 service |
| template/export | 页面、报告和文件导出展示 | 是否没有复杂业务逻辑；是否避免泄漏本地路径或 secrets |
| tests | 单元、集成、fixture 和 mock | 是否禁止真实联网 |
| docs | 产品、架构、追踪矩阵或路线图更新 | 是否说明新增边界和验收标准 |

## PDF Readiness 功能约束

涉及全文分析入口的功能必须明确 PDF readiness 流程：

- `need_pdf` 表示没有可用 PDF，不能运行全文分析。
- `manual_pdf` 表示用户上传的 PDF，优先级高于本地库匹配。
- `local_library_pdf` 表示来自配置的本地 PDF library/index。
- 分析前必须存在 `PdfAsset` 和可用 extracted text，避免生成没有原文证据的 `StrongEvidence`。
- 页面和导出只能显示 filename/source type，不得显示本地绝对路径或内部 storage path。

## Feature Spec 模板

```markdown
# Feature Spec: <功能名称>

## 背景

<说明用户问题、业务场景和为什么现在要做。>

## 目标

- <目标 1>
- <目标 2>

## 非目标

- <明确不做的内容 1>
- <明确不做的内容 2>

## 优先级

P0/P1/P2: <选择一个优先级，并说明原因。>

## 用户流程

1. <用户动作 1>
2. <系统响应 1>
3. <用户动作 2>
4. <系统响应 2>

## 数据模型

- <实体或字段 1>: <含义、约束、状态>
- <实体或字段 2>: <含义、约束、状态>

## Schema

- Request: <字段、类型、校验>
- Response: <字段、类型、错误>
- Service input/output: <内部数据结构>

## Repository

- <查询或写入方法 1>: <用途和事务要求>
- <查询或写入方法 2>: <用途和事务要求>

## Service

- <服务方法 1>: <编排步骤和失败行为>
- <服务方法 2>: <编排步骤和失败行为>

## Task

- 是否需要后台任务: <是/否>
- 任务状态: <pending/running/succeeded/failed 等>
- 失败处理: <重试、记录、用户提示>

## Router/API

- Route: `<HTTP 方法> <路径>`
- Input: <参数或表单>
- Output: <页面、JSON 或重定向>
- Error behavior: <错误码或提示>

## Template

- 页面入口: <页面名称>
- 展示内容: <字段、状态、操作>
- 禁止逻辑: <不得放入模板的业务判断>
- PDF readiness: <need_pdf 如何变为 manual_pdf/local_library_pdf；无 PDF 时如何提示用户>

## Export

- 是否生成文件: <是/否>
- 格式: <Markdown/JSON/其他>
- 字段: <导出字段清单>
- 空态: <无数据、无 evidence、缺 PDF 等如何展示>
- 安全边界: <不得包含本地绝对路径、API key、provider raw secret、数据库内部路径字段>
- 副作用: <是否只读现有结果，是否禁止重新调用 LLM/PDF 分析/外部 API>

## Tests

- Unit: <analysis/pdf/schema/service 等测试>
- Repository: <数据库访问测试>
- Router/API: <HTTP 行为测试>
- Export/golden: <关键内容、UTF-8、JSON 可解析、空态、404、敏感字段负向断言>
- Fixtures/mocks: <PDF、provider mock、外部响应 fixture>

## Docs

- 更新 `docs/product_requirements.md`: <是/否，说明>
- 更新 `docs/architecture.md`: <是/否，说明>
- 更新 `docs/requirements_traceability.md`: <是/否，说明>
- 更新 `docs/tasks/roadmap.md`: <是/否，说明>
- 更新 `docs/api/*.md`: <是/否，说明新增或变更 API>
```
