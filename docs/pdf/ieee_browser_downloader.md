# IEEE browser downloader integration

The scholar queue can invoke the supplied `ieee-download` Playwright tool for
IEEE Xplore papers. The helper keeps its persistent Chromium profile in its own
tool directory. The academic impact application receives only the resulting PDF
and does not receive the IEEE or institutional username and password.

Configure the application after installing the tool from
`docs/ieee_title_downloader.zip`:

```env
ACADEMIC_IMPACT_IEEE_DOWNLOADER_COMMAND=/data/ieee_title_downloader/ieee-download
ACADEMIC_IMPACT_IEEE_DOWNLOADER_WORK_DIR=/data/ieee_title_downloader
ACADEMIC_IMPACT_IEEE_DOWNLOADER_DOWNLOAD_DIR=/data/ieee_title_downloader/downloads
ACADEMIC_IMPACT_IEEE_DOWNLOADER_TIMEOUT_SECONDS=900
ACADEMIC_IMPACT_IEEE_DOWNLOADER_PORTAL_URL=http://127.0.0.1:8090/
ACADEMIC_IMPACT_IEEE_PROFILE_DIR=/data/ieee_title_downloader/ieee_profile
ACADEMIC_IMPACT_IEEE_RUNTIME_DIR=/var/lib/academic-impact/ieee-runtime
ACADEMIC_IMPACT_IEEE_MIN_REQUEST_INTERVAL_SECONDS=8
```

`ACADEMIC_IMPACT_IEEE_RUNTIME_DIR` must be on a Linux filesystem because it
contains a Unix FIFO used only to keep the user-operated login process open.
If omitted, it defaults to `<project>/var/run/ieee`; it is not tied to a
specific username or checkout path. Do not place it under `/mnt/c` or `/mnt/d`.

The profile setting is optional; it defaults to `ieee_profile` below the
configured work directory. It contains browser authentication data and must
remain outside Git.

For batch downloads, start the task from the queue page. The task processes
existing and open-access PDFs first, then performs one IEEE authentication
preflight. If authentication is missing it enters `waiting_for_login`, opens
one dedicated login browser, and preserves the pending IEEE item IDs.

Complete personal or institutional login in that dedicated browser. In the
queue task panel, click **检测登录状态**, then **继续 IEEE 下载**. The resumed
task uses one persistent browser context for the remaining IEEE papers and
waits at least the configured interval between documents.

After that, use **通过 IEEE 浏览器助手自动下载** on an IEEE queue item. The
worker runs the helper serially, validates that its output is a complete PDF,
creates or reuses a `pdf_assets` record, extracts text, links the asset to the
citing publication, and marks the queue item PDF-ready.

If the session expires, the task returns to `waiting_for_login` at the current
checkpoint. Challenge/CAPTCHA/403/429 pages enter `challenge_blocked` and stop
further IEEE navigation. The application does not attempt to bypass the
challenge and does not log passwords, cookies, or session tokens.
