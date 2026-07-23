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
```

Run the tool's login mode once and complete the IEEE or institutional login in
the dedicated browser:

```bash
/data/ieee_title_downloader/ieee-download --login
```

After that, use **通过 IEEE 浏览器助手自动下载** on an IEEE queue item. The
worker runs the helper serially, validates that its output is a complete PDF,
creates or reuses a `pdf_assets` record, extracts text, links the asset to the
citing publication, and marks the queue item PDF-ready.

If the browser session expires, the task reports `requires_login`; open the
configured portal/login browser, renew the session, and submit the task again.
