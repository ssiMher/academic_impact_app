# 组内服务器部署指南

本文适用于一台 Linux 组内服务器上的单实例部署。推荐通过 GitHub 分支或已合并的 `master` 同步代码，不要复制整个本地项目目录，因为本地目录包含数据库、PDF、缓存和登录状态。

## 1. 推荐发布流程

本地开发机：

```bash
git status
git switch -c codex/deploy-and-user-guide

# 明确暂存源码、测试和文档，不要使用未经检查的 git add .
git add app scripts tests pyproject.toml .env.example README.md docs
git diff --cached --stat
git diff --cached
python3 -m pytest -q
git commit
git push -u origin codex/deploy-and-user-guide
```

在 GitHub 创建 Pull Request，审查并合并到 `master`。然后在服务器拉取：

```bash
cd /srv/academic_impact_app
git fetch origin
git switch master
git pull --ff-only origin master
```

如果暂时不走 PR，也可以让服务器检出明确的部署分支，但不要在服务器上直接开发或产生未提交的源码改动：

```bash
git fetch origin
git switch --track origin/codex/deploy-and-user-guide
```

## 2. 首次安装

以下示例假设部署目录为 `/srv/academic_impact_app`，运行用户为 `academic-impact`。请按服务器实际账号调整。

```bash
sudo mkdir -p /srv/academic_impact_app
sudo chown academic-impact:academic-impact /srv/academic_impact_app
sudo -u academic-impact git clone git@github.com:ssiMher/academic_impact_app.git /srv/academic_impact_app
cd /srv/academic_impact_app

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "."
cp .env.example .env
mkdir -p var/pdf_assets var/extracted_text var/exports var/pdf_inbox var/run/ieee
chmod 700 .env var
```

服务器需要能够访问 GitHub、DBLP、OpenAlex、Unpaywall、arXiv，以及配置的 LLM 服务。若服务器使用代理，应在 systemd 服务环境中配置代理，而不只是在交互 Shell 中配置。

## 3. 配置 `.env`

`.env` 只保存在服务器，不提交 Git。最低建议配置如下：

```env
ACADEMIC_IMPACT_APP_NAME=Academic Impact App
ACADEMIC_IMPACT_APP_ENV=production
ACADEMIC_IMPACT_LOG_LEVEL=INFO

ACADEMIC_IMPACT_DATABASE_URL=sqlite:////srv/academic_impact_app/var/academic_impact_app.db
ACADEMIC_IMPACT_PDF_ASSET_DIR=/srv/academic_impact_app/var/pdf_assets
ACADEMIC_IMPACT_EXTRACTED_TEXT_DIR=/srv/academic_impact_app/var/extracted_text
ACADEMIC_IMPACT_EXPORT_DIR=/srv/academic_impact_app/var/exports
ACADEMIC_IMPACT_PDF_INBOX_DIR=/srv/academic_impact_app/var/pdf_inbox

ACADEMIC_IMPACT_AUTHOR_PROVIDER=dblp
ACADEMIC_IMPACT_CITATION_PROVIDER=openalex
ACADEMIC_IMPACT_METADATA_PROVIDER=openalex
ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS=30
ACADEMIC_IMPACT_UNPAYWALL_EMAIL=your-group-contact@example.edu
ACADEMIC_IMPACT_UNPAYWALL_TIMEOUT_SECONDS=15

ACADEMIC_IMPACT_LLM_PROVIDER=openai_compatible
ACADEMIC_IMPACT_LLM_BASE_URL=https://your-provider.example/v1
ACADEMIC_IMPACT_LLM_API_KEY=replace-with-server-secret
ACADEMIC_IMPACT_LLM_MODEL=replace-with-model-name
```

注意：SQLite 四斜杠 URL 表示绝对路径。启动时应用会创建缺失表，并运行项目内置的幂等 SQLite schema upgrade。升级前仍应备份数据库。

## 4. 先手工验证

```bash
cd /srv/academic_impact_app
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health.json
cd /srv/academic_impact_app
.venv/bin/python scripts/run_worker_once.py
```

`/health` 应返回 `{"status":"ok"}`。`/health.json` 会显示 provider 是否完成配置，但不会泄露 API 密钥。

## 5. 使用 systemd 常驻运行

Web 服务 `/etc/systemd/system/academic-impact-web.service`：

```ini
[Unit]
Description=Academic Impact App Web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=academic-impact
Group=academic-impact
WorkingDirectory=/srv/academic_impact_app
EnvironmentFile=/srv/academic_impact_app/.env
ExecStart=/srv/academic_impact_app/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
```

任务 worker `/etc/systemd/system/academic-impact-worker.service`：

```ini
[Unit]
Description=Academic Impact App Task Worker
After=network-online.target academic-impact-web.service
Wants=network-online.target

[Service]
Type=simple
User=academic-impact
Group=academic-impact
WorkingDirectory=/srv/academic_impact_app
EnvironmentFile=/srv/academic_impact_app/.env
ExecStart=/srv/academic_impact_app/.venv/bin/python scripts/run_worker.py
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now academic-impact-web academic-impact-worker
sudo systemctl status academic-impact-web academic-impact-worker
journalctl -u academic-impact-web -u academic-impact-worker -f
```

SQLite 模式下不要把 `--workers 1` 改成多 worker，也不要启动多个任务 worker。多进程写 SQLite 会显著增加 `database is locked` 风险。需要横向扩展时，应先迁移到正式的多用户数据库和任务队列。

## 6. 可选 Nginx 反向代理

建议只在组内网络开放，并由 Nginx 终止 HTTPS。最小配置示例：

```nginx
server {
    listen 80;
    server_name academic-impact.example.edu;
    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

当前应用没有内置用户登录和权限隔离，不应直接暴露到公网。至少应使用校园网/VPN、Nginx Basic Auth 或上游统一认证保护。

## 7. IEEE 下载器的服务器限制

IEEE 自动下载使用 Playwright 持久浏览器 Profile，需要人工完成个人或机构登录。

- 有桌面环境或远程桌面：可按 [IEEE 浏览器下载器](pdf/ieee_browser_downloader.md) 配置。
- 纯 SSH、无图形桌面：不要配置 IEEE downloader；使用开放 PDF、本地 PDF 库或手动下载后上传。
- IEEE Profile、Cookie、认证 JSON 和运行 FIFO 必须留在服务器本地且不可提交 Git。
- Web 和 worker 必须看到同一个 Profile、下载目录和 Linux runtime 目录。

## 8. 日常更新

更新前先备份数据库和文件资产：

```bash
sudo systemctl stop academic-impact-worker academic-impact-web
cd /srv/academic_impact_app
cp var/academic_impact_app.db /srv/backups/academic_impact_app-$(date +%F-%H%M%S).db
git fetch origin
git pull --ff-only origin master
.venv/bin/python -m pip install -e "."
.venv/bin/python -m pytest -q
sudo systemctl start academic-impact-web academic-impact-worker
curl http://127.0.0.1:8000/health
```

生产备份还应包含 `var/pdf_assets`、`var/extracted_text`、`var/exports` 和 `.env` 的安全副本。不要只备份 SQLite 文件而遗漏 PDF 资产。

## 9. 回滚

不要对包含本地数据的目录执行 `git reset --hard`。代码回滚使用已验证的 Git commit，同时保留数据库备份：

```bash
sudo systemctl stop academic-impact-worker academic-impact-web
git fetch origin
git switch --detach <verified-commit-sha>
.venv/bin/python -m pip install -e "."
sudo systemctl start academic-impact-web academic-impact-worker
```

如果新版本已经修改数据库结构，代码回滚不等于数据库回滚；需要同时恢复升级前备份。

## 10. 常见问题

- 页面能打开但任务不动：检查 `academic-impact-worker` 是否运行。
- `database is locked`：确认只有一个 Web worker 和一个任务 worker，且数据库位于本地磁盘而不是 NFS。
- DBLP/OpenAlex/Unpaywall/arXiv 超时：从服务器直接检查 DNS、HTTPS、代理和防火墙。
- LLM 分析失败：查看 `/health.json` 中配置状态及 worker 日志。
- PDF 没有自动下载：不代表不存在论文；可能只有付费落地页、没有直接 PDF URL，或网络请求超时。
- IEEE 显示等待登录：需要在持久浏览器中登录；无桌面服务器应改用手工上传。
