# IEEE 论文下载工具交接说明

> 当前项目目录：`/data1/ds/projects/ieee_paper_service`  
> 当前 Conda 环境：`academic-impact-web`  
> 下载网页：服务器 `127.0.0.1:8092`  
> 图形登录入口：Xpra `127.0.0.1:6080`，虚拟显示器 `DISPLAY=:99`

## 1. 项目用途与当前能力

该工具用于在用户本人或所在机构已获授权访问 IEEE Xplore 的前提下，根据以下任一种输入下载论文 PDF：

- IEEE article number，例如 `10229085`
- IEEE document URL，例如 `https://ieeexplore.ieee.org/document/10229085`
- 完整英文论文标题

当前已实现：

1. Playwright 持久化浏览器会话；
2. 南京大学 Institutional Sign In 人工登录；
3. 自动恢复认证 Cookie；
4. 标题搜索与 article number 匹配；
5. 自动打开详情页并点击 PDF；
6. 捕获 `application/pdf` 响应；
7. 首次响应不完整时，用同一浏览器会话重新获取；
8. 校验 `%PDF-` 后保存；
9. FastAPI 网页提交任务；
10. SQLite 串行任务队列；
11. 网页显示状态、日志和 PDF 下载链接；
12. Xpra HTML5 页面用于服务器端人工完成机构登录。

## 2. 系统架构

```text
用户浏览器
  │  VS Code/SSH 端口转发
  ▼
FastAPI 网页服务（127.0.0.1:8092）
  ├─ HTTP Basic Auth
  ├─ SQLite 任务队列
  ├─ 单线程 Worker
  └─ 调用 ieee-download 子进程
         │
         ▼
Playwright Chromium（DISPLAY=:99）
  ├─ ieee_profile/ 持久化浏览器数据
  ├─ ieee_auth.json 保存 Cookie
  └─ Xpra 6080 提供人工登录界面
         │
         ▼
IEEE Xplore → downloads/*.pdf
```

### 为什么必须串行

所有任务共享同一个浏览器 Profile 和认证状态，因此：

- FastAPI 必须 `--workers 1`；
- Worker 必须单线程；
- 不要同时手动运行多份 `ieee-download`；
- 不要让多个项目直接并发操作同一 `ieee_profile/`。

## 3. 目录结构

```text
/data1/ds/projects/ieee_paper_service/
├── ieee_title_downloader/
│   ├── ieee-download
│   ├── ieee_download.py
│   ├── requirements.txt
│   ├── ieee_profile/          # 浏览器 Profile，敏感
│   ├── ieee_auth.json         # Cookie，敏感
│   └── downloads/             # 下载结果
├── ieee_web_portal/
│   ├── web_app.py
│   ├── start_web.sh
│   └── requirements.txt
├── web_data/
│   ├── jobs.sqlite3
│   └── login.log
├── logs/
│   ├── xpra.log
│   ├── ieee-web.log
│   └── ieee-web.pid
└── server.env                 # 服务配置与网页密码，敏感
```

## 4. 下载流程原理

### 4.1 机构登录

1. 网页点击“启动登录浏览器”；
2. 服务执行 `ieee-download --login`；
3. Playwright 在 `DISPLAY=:99` 启动 Chromium；
4. 用户通过 6080 的 Xpra 页面进入服务器浏览器；
5. 手动完成 Institutional Sign In；
6. 确认出现：

```text
Access provided by:
Nanjing University
```

7. 手动打开任意有权限的 PDF，确认正文可见；
8. 回到网页点击“我已完成登录，保存状态”；
9. 服务向登录子进程标准输入写入回车；
10. Playwright 保存 `ieee_profile/` 和 `ieee_auth.json`。

恢复了 Cookie 不代表 IEEE 一定仍认可机构会话。若重新显示 `Institutional Sign In`，应重新登录。

### 4.2 标题解析

输入为标题时：

1. 打开 IEEE 搜索页；
2. 提取 `/document/<article_number>` 链接；
3. 归一化标题；
4. 计算字符串相似度；
5. 排序候选；
6. CLI 可人工选择，网页模式使用 `-y` 自动选择最高匹配。

输入为 article number 或 document URL 时，直接解析编号，稳定性最高。

### 4.3 PDF 获取

1. 打开 `/document/<article_number>`；
2. 检查机构认证；
3. 查找 PDF 按钮或链接；
4. 自动点击；
5. 在 BrowserContext 监听网络响应；
6. 仅接受 HTTP 200 且 `Content-Type: application/pdf` 的响应；
7. 读取响应体；
8. 若首次响应不完整，调用 `context.request.get()` 以同一认证会话重新获取；
9. 检查文件头 `%PDF-`；
10. 根据 `Content-Disposition` 生成文件名并保存。

浏览器偶尔显示 `Failed to load PDF document`，但脚本仍可能下载成功。最终以终端 `[成功]`、`file` 显示 PDF、文件头 `%PDF-` 为准。

## 5. 主要代码说明

### 5.1 `ieee_title_downloader/ieee_download.py`

主要函数：

- `create_context()`：创建 persistent Playwright context，加载 Profile 和 Cookie；
- `login_mode()`：人工登录并保存状态；
- `normalize_title()` / `similarity()`：标题归一化和相似度；
- `search_title()`：搜索 IEEE 并选择 article number；
- `capture_pdf_response()`：打开详情页、检查登录、点击 PDF、捕获 PDF 响应；
- `download_article()`：下载、重取完整响应、校验、命名、保存；
- `resolve_query()`：识别标题、article number 或 document URL；
- `main()`：命令行入口。

### 5.2 `ieee_title_downloader/ieee-download`

Shell 启动器，使用项目 `.venv/bin/python` 调用 `ieee_download.py`。当前 `.venv` 是指向 Conda 环境的软链接。

### 5.3 `ieee_web_portal/web_app.py`

主要职责：

- FastAPI 页面；
- HTTP Basic Auth；
- SQLite 任务数据库；
- 单线程后台 Worker；
- 调用 `ieee-download -y <query>`；
- 解析命令行输出中的 PDF 路径；
- 登录浏览器进程控制；
- PDF 文件返回。

任务表字段：

```text
id, query, status, created_at, started_at,
finished_at, output, file_path
```

状态：

```text
queued, running, success, needs_login, failed
```

## 6. 当前网页接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 首页和任务列表 |
| POST | `/jobs` | HTML 表单提交任务 |
| GET | `/jobs/{id}/download` | 下载 PDF |
| POST | `/login/start` | 启动登录浏览器 |
| POST | `/login/finish` | 保存登录状态 |
| POST | `/login/cancel` | 取消登录进程 |
| GET | `/login/log` | 查看登录日志 |

当前主要是网页接口。要让其他项目调用，建议增加 JSON API。

## 7. 推荐的 JSON API

建议增加：

```text
POST /api/v1/jobs
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/file
```

### 提交任务

```http
POST /api/v1/jobs
Content-Type: application/json
Authorization: Basic ...

{"query":"10229085"}
```

响应：

```json
{"id":12,"query":"10229085","status":"queued"}
```

### 查询状态

```http
GET /api/v1/jobs/12
```

成功响应示例：

```json
{
  "id": 12,
  "query": "10229085",
  "status": "success",
  "download_url": "/api/v1/jobs/12/file",
  "output": "..."
}
```

### 可加入 `web_app.py` 的示例

```python
from pydantic import BaseModel

class ApiJobRequest(BaseModel):
    query: str

@app.post("/api/v1/jobs")
def api_create_job(
    request: ApiJobRequest,
    _: str = Depends(require_user),
):
    query = request.query.strip()
    if not query or len(query) > 1000:
        raise HTTPException(status_code=400, detail="query 无效")

    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs(query, status, created_at)
            VALUES (?, 'queued', ?)
            """,
            (query, now_iso()),
        )
        job_id = cursor.lastrowid

    return {"id": job_id, "query": query, "status": "queued"}

@app.get("/api/v1/jobs/{job_id}")
def api_get_job(job_id: int, _: str = Depends(require_user)):
    with connect_db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()

    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = dict(job)
    if job["status"] == "success":
        result["download_url"] = f"/api/v1/jobs/{job_id}/file"
    return result

@app.get("/api/v1/jobs/{job_id}/file")
def api_download_job(job_id: int, _: str = Depends(require_user)):
    with connect_db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()

    if not job or job["status"] != "success" or not job["file_path"]:
        raise HTTPException(status_code=404, detail="PDF 尚不可用")

    path = Path(job["file_path"]).resolve()
    path.relative_to(DOWNLOAD_DIR)
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=path.name,
    )
```

## 8. 其他项目调用示例

```python
from pathlib import Path
import time
import requests

class IeeeDownloadClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)

    def submit(self, query: str) -> int:
        r = requests.post(
            f"{self.base_url}/api/v1/jobs",
            auth=self.auth,
            json={"query": query},
            timeout=30,
        )
        r.raise_for_status()
        return int(r.json()["id"])

    def wait(self, job_id: int, timeout_seconds: int = 900) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            r = requests.get(
                f"{self.base_url}/api/v1/jobs/{job_id}",
                auth=self.auth,
                timeout=30,
            )
            r.raise_for_status()
            job = r.json()
            if job["status"] == "success":
                return job
            if job["status"] in {"failed", "needs_login"}:
                raise RuntimeError(f"下载失败：{job['status']}\n{job.get('output','')}")
            time.sleep(3)
        raise TimeoutError("等待下载超时")

    def download(self, job_id: int, output_path: Path) -> Path:
        r = requests.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/file",
            auth=self.auth,
            timeout=300,
        )
        r.raise_for_status()
        if not r.content.startswith(b"%PDF-"):
            raise RuntimeError("返回内容不是 PDF")
        output_path.write_bytes(r.content)
        return output_path
```

使用：

```python
client = IeeeDownloadClient(
    "http://127.0.0.1:8092",
    "paper",
    "网页密码",
)
job_id = client.submit("10229085")
client.wait(job_id)
client.download(job_id, Path("paper.pdf"))
```

## 9. 迁移到其他项目的三种方式

### A. 独立 HTTP 服务（推荐）

其他项目只调用 API。优点：

- 认证 Profile 集中管理；
- 依赖隔离；
- 自动串行；
- 统一日志、权限、失败处理；
- 多个业务系统可以复用。

### B. 子进程调用 CLI

```python
subprocess.run([
    "/path/to/ieee-download",
    "-y",
    "10229085",
])
```

适合单一内部脚本，不适合多个项目并发使用。

### C. 重构为 Python 库

可抽成 `IeeeDownloader` 类供其他项目导入，但仍需实现单实例锁、Profile 互斥和统一认证。除非系统只有一个 Python 进程，否则不如独立服务稳定。

## 10. 当前运行方式

### Xpra

```bash
xpra start :99 \
  --bind-tcp=127.0.0.1:6080,auth=none \
  --html=on \
  --daemon=yes \
  --mdns=no \
  --pulseaudio=no \
  --notifications=no \
  --printing=no \
  --webcam=no \
  --log-file="$PWD/logs/xpra.log"
```

检查：

```bash
xpra list
ss -lnt | grep 6080
tail -50 logs/xpra.log
```

停止：

```bash
xpra stop :99
```

### FastAPI

```bash
cd /data1/ds/projects/ieee_paper_service
source server.env
nohup ./ieee_web_portal/start_web.sh \
  > logs/ieee-web.log 2>&1 &
echo $! > logs/ieee-web.pid
```

停止：

```bash
kill "$(cat logs/ieee-web.pid)"
```

## 11. 端口与访问

```text
127.0.0.1:6080  Xpra HTML5 登录桌面
127.0.0.1:8092  下载网页/API
```

通过 VS Code Remote-SSH 的 PORTS 面板转发 6080 和 8092。两者保持 Private，不要把 6080 直接暴露到公网。

## 12. 环境与依赖

当前使用 Conda 环境：

```text
academic-impact-web
```

关键依赖：

```text
playwright
fastapi
uvicorn
python-multipart
xpra
xorg-xvfb-server
```

检查：

```bash
python -m playwright --version
python -m py_compile \
  ieee_title_downloader/ieee_download.py \
  ieee_web_portal/web_app.py
```

## 13. 常见故障

### `needs_login`

机构认证已失效。通过网页启动登录浏览器，在 Xpra 中完成认证并保存，然后重新提交任务。

### 浏览器显示 PDF Error，但任务 success

通常是 Chrome 首次流式响应不完整；脚本已用同一认证会话重取完整 PDF。以文件校验为准。

### 403 / 429 / Request Rejected

停止任务，不要连续重试。检查机构登录、网络出口、访问频率和验证页面。

### 标题匹配错误

优先传 article number 或 document URL；标题模式依赖 IEEE 搜索页面结构。

### 多任务冲突

确认只有一个 Uvicorn worker、一个后台 Worker，并且没有其他进程使用同一 `ieee_profile/`。

## 14. 安全与合规

敏感内容：

```text
ieee_profile/
ieee_auth.json
server.env
web_data/jobs.sqlite3
```

要求：

- 不提交 Git；
- 不分享给他人；
- 不复制到不可信服务器；
- 不公开 6080；
- 公网开放 8092 时必须加 HTTPS、强认证、访问控制和速率限制；
- 只下载本人或机构依法有权访问且实际需要的论文；
- 不高并发、不遍历编号、不绕过验证码；
- 遇到 403、429、验证码或机构告警立即停止。

建议权限：

```bash
chmod 600 server.env ieee_title_downloader/ieee_auth.json
chmod 700 ieee_title_downloader/ieee_profile
```

## 15. 交接检查清单

```text
[ ] Conda 环境可激活
[ ] Playwright Chromium 可启动
[ ] ieee-download --help 正常
[ ] Xpra :99 为 LIVE
[ ] 6080 返回 HTTP 200
[ ] 8092 网页可访问
[ ] Basic Auth 可登录
[ ] Xpra 能看到 Chromium
[ ] 南京大学机构登录成功
[ ] article number 下载成功
[ ] 网页可下载真实 PDF
[ ] 文件头为 %PDF-
[ ] 敏感文件未提交 Git
```

## 16. 后续改进建议

1. 增加正式 JSON API；
2. 将 Basic Auth 改为 API Token 或接入现有系统认证；
3. 增加任务取消与手动重试；
4. 增加 DOI、article number 和文件哈希去重；
5. 增加任务提交者、来源项目字段；
6. 增加 `/health` 和 `/ready`；
7. 增加每日上限和串行请求间隔；
8. 使用用户级 systemd、Supervisor 或现有进程管理器自动拉起服务；
9. 结构化日志和告警；
10. 将 IEEE 下载服务作为独立内部服务长期维护。
