# Academic Impact App

Academic Impact App 是一个面向学术影响力分析的 FastAPI Web 系统。它以学者或目标论文为入口，扩展引用关系、管理引用论文 PDF、从全文中提取引用证据，并支持人工复核和报告导出。

## 主要功能

- 通过学者姓名或 DBLP PID 创建学者分析会话，同名作者必须人工选择。
- 使用 DBLP 获取作者论文，使用 OpenAlex 扩展引用关系。
- 构建深度分析队列，自动复用本地 PDF，并发现 arXiv、Unpaywall 等开放版本。
- 可选使用持久浏览器会话下载已获机构授权的 IEEE PDF。
- 对选定引用论文运行全文证据分析，支持模板、人工复核和调试信息。
- 导出 Markdown、JSON、CSV 和 PowerPoint 报告。

## 快速开始

项目要求 Python 3.8 或更高版本。建议使用虚拟环境：

```bash
git clone git@github.com:ssiMher/academic_impact_app.git
cd academic_impact_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

开发环境需要同时运行 Web 和任务 worker：

```bash
# 终端 1
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2
source .venv/bin/activate
python3 scripts/run_worker.py
```

打开 <http://127.0.0.1:8000>，健康检查地址为 <http://127.0.0.1:8000/health>。

运行测试：

```bash
python3 -m pytest -q
```

## 文档入口

- [网站使用手册](docs/user_guide.md)
- [组内服务器部署指南](docs/deployment.md)
- [配置说明](docs/ops/configuration.md)
- [健康检查](docs/ops/health_check.md)
- [架构设计](docs/architecture.md)
- [DBLP provider](docs/providers/dblp.md)
- [OpenAlex provider](docs/providers/openalex.md)
- [开放 PDF 发现](docs/pdf/pdf_discovery.md)
- [IEEE 浏览器下载器](docs/pdf/ieee_browser_downloader.md)

## 数据与凭据安全

以下内容属于部署实例，不应提交到 GitHub：

- `.env` 和 LLM/API 密钥；
- `var/*.db`、SQLite WAL/SHM 文件；
- `var/pdf_assets`、`var/extracted_text`、`var/exports`；
- IEEE 浏览器 Profile、Cookie 和登录状态；
- LLM 调试 prompt、原始响应及其他运行日志。

`.gitignore` 已覆盖主要运行目录，但提交前仍应检查 `git status` 和 `git diff --cached`。

## 当前部署约束

- 默认数据库为 SQLite。组内单机部署请只运行一个 Uvicorn worker 和一个任务 worker。
- Web 进程只负责页面和任务入队；未启动 `scripts/run_worker.py` 时，后台任务会一直等待。
- IEEE 登录依赖可交互的 Playwright 浏览器和持久 Profile。纯 SSH、无桌面的服务器通常无法完成该流程。
- `.env` 不随 Git 同步。每台服务器必须单独配置路径、API 密钥和联系邮箱。
