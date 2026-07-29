document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.matches("[data-copy-text]")) {
    const text = target.getAttribute("data-copy-text") || "";
    if (navigator.clipboard && text) {
      navigator.clipboard.writeText(text);
    }
    return;
  }
  if (!target.matches("[data-toggle-target]")) return;
  const selector = target.getAttribute("data-toggle-target");
  if (!selector) return;
  const panel = document.querySelector(selector);
  if (panel) panel.toggleAttribute("hidden");
});

function initializeTaskProgressPolling(panel) {
  if (!(panel instanceof HTMLElement) || panel.dataset.active !== "true") return;
  const statusUrl = panel.dataset.statusUrl;
  const taskId = panel.dataset.taskId;
  const taskType = panel.dataset.taskType || "task";
  const activeStatuses = new Set(
    (panel.dataset.activeStatuses || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  const terminalReload = panel.dataset.terminalReload !== "false";
  if (!statusUrl || !taskId) return;

  let timerId = null;
  let stopped = false;
  let consecutiveErrors = 0;
  const terminalReloadKey = `task-terminal-refreshed:${taskType}:${taskId}`;

  const statusBadge = panel.querySelector('[data-task-role="status-badge"]');
  const progress = panel.querySelector('[data-task-role="progress"]');
  const progressText = panel.querySelector('[data-task-role="progress-text"]');
  const progressPercent = panel.querySelector('[data-task-role="progress-percent"]');
  const message = panel.querySelector('[data-task-role="message"]');
  const stage = panel.querySelector('[data-task-role="stage"]');
  const error = panel.querySelector('[data-task-role="error"]');
  const pendingHelp = panel.querySelector('[data-task-role="pending-help"]');
  const ieeeSessionSummary = panel.querySelector('[data-task-role="ieee-session-summary"]');
  const ieeeSessionBadge = panel.querySelector('[data-task-role="ieee-session-badge"]');
  const ieeeSessionMessage = panel.querySelector('[data-task-role="ieee-session-message"]');
  const ieeeTaskStatus = panel.querySelector('[data-task-role="ieee-task-status"]');
  const ieeeSessionState = panel.querySelector('[data-task-role="ieee-session-state"]');
  const ieeeSessionUpdated = panel.querySelector('[data-task-role="ieee-session-updated"]');
  const ieeeSessionCounters = panel.querySelector('[data-task-role="ieee-session-counters"]');
  const ieeeProfileExists = panel.querySelector('[data-task-role="ieee-profile-exists"]');
  const ieeeProfileLocked = panel.querySelector('[data-task-role="ieee-profile-locked"]');
  const ieeeLoginWindow = panel.querySelector('[data-task-role="ieee-login-window"]');
  const ieeePersonalLogin = panel.querySelector('[data-task-role="ieee-personal-login"]');
  const ieeeInstitutionAccess = panel.querySelector('[data-task-role="ieee-institution-access"]');
  const pauseButton = panel.querySelector('[data-task-control="pause"]');
  const resumeButton = panel.querySelector('[data-task-control="resume"]');
  const disableTarget = panel.dataset.disableTarget;
  const defaultPendingHelp = pendingHelp?.textContent?.trim() || "";
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);
  const resumableStatuses = new Set(["waiting_for_login", "challenge_blocked", "paused"]);
  const pausableStatuses = new Set(["pending", "running", "waiting_for_login", "challenge_blocked"]);

  const badgeClass = (status) => {
    if (status === "succeeded") return "badge badge-success";
    if (status === "failed" || status === "cancelled" || status === "challenge_blocked") {
      return "badge badge-danger";
    }
    if (
      status === "pending"
      || status === "running"
      || status === "waiting_for_login"
      || status === "session_expired"
      || status === "unauthenticated"
      || status === "paused"
    ) {
      return "badge badge-warning";
    }
    return "badge badge-muted";
  };

  const humanizeToken = (value) => String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

  const counterLabel = (key) => {
    const labels = {
      attempted: "已尝试",
      checked: "已检查",
      downloaded: "已下载",
      waiting_for_login: "待登录",
      challenge_blocked: "验证阻塞",
      resumed: "已恢复",
      paused: "已暂停",
      failed: "失败",
    };
    return labels[key] || humanizeToken(key);
  };

  const pollDelay = (status) => {
    if (status === "waiting_for_login" || status === "challenge_blocked") return 4000;
    if (status === "paused") return 8000;
    return 1500;
  };

  const safeSessionStatus = (task) => {
    const sessionStatus = task?.ieee_session_status;
    if (!sessionStatus || typeof sessionStatus !== "object" || Array.isArray(sessionStatus)) {
      return null;
    }
    const counters = sessionStatus.result_counters && typeof sessionStatus.result_counters === "object"
      ? sessionStatus.result_counters
      : sessionStatus.counters && typeof sessionStatus.counters === "object"
        ? sessionStatus.counters
        : null;
    return {
      label: String(
        sessionStatus.label
        || sessionStatus.state
        || sessionStatus.status
        || sessionStatus.session_state
        || "not_checked",
      ),
      message: String(
        sessionStatus.message
        || sessionStatus.hint
        || sessionStatus.status_message
        || "",
      ),
      updatedAt: String(
        sessionStatus.updated_at
        || sessionStatus.checked_at
        || sessionStatus.last_checked_at
        || sessionStatus.last_updated_at
        || "",
      ),
      profileExists: Boolean(sessionStatus.profile_exists),
      profileLocked: Boolean(sessionStatus.profile_locked),
      loginWindowOpen: Boolean(sessionStatus.login_window_open),
      personalLogin: Boolean(sessionStatus.personal_login),
      institutionAccess: Boolean(sessionStatus.institution_access),
      institutionName: String(sessionStatus.institution_name || ""),
      counters,
    };
  };

  const taskHint = (status) => {
    if (status === "waiting_for_login") {
      return "任务正在等待 IEEE 登录。请打开 IEEE 会话完成登录，然后检查或恢复任务。";
    }
    if (status === "challenge_blocked") {
      return "任务被 IEEE challenge 阻塞。请先在专用浏览器中完成验证，再检查或恢复任务。";
    }
    if (status === "paused") {
      return "任务已暂停。处理完 IEEE 会话后可恢复继续。";
    }
    if (status === "pause_requested") {
      return "正在等待当前论文处理结束，随后会在安全边界暂停。";
    }
    return activeStatuses.has(status) ? defaultPendingHelp : "";
  };

  const renderCounters = (container, counters) => {
    if (!(container instanceof HTMLElement)) return;
    container.replaceChildren();
    const entries = counters && typeof counters === "object"
      ? Object.entries(counters).filter(([, value]) => value !== null && value !== undefined && value !== "")
      : [];
    if (!entries.length) {
      container.hidden = true;
      return;
    }
    entries.forEach(([key, value]) => {
      const card = document.createElement("article");
      card.className = "stat-card";

      const count = document.createElement("div");
      count.className = "stat-value";
      count.textContent = String(value);

      const label = document.createElement("div");
      label.className = "stat-label";
      label.textContent = counterLabel(key);

      card.append(count, label);
      container.append(card);
    });
    container.hidden = false;
  };

  const renderSummary = (summary) => {
    if (!summary) return;
    panel.querySelectorAll("[data-task-summary-key]").forEach((node) => {
      const key = node.getAttribute("data-task-summary-key");
      if (
        key
        && Object.prototype.hasOwnProperty.call(summary, key)
      ) {
        node.textContent = String(summary[key]);
      }
    });
  };

  const renderIeeeSession = (task) => {
    const sessionStatus = safeSessionStatus(task);
    const sessionLabel = sessionStatus?.label || "not_checked";
    const sessionMessageText = sessionStatus?.message
      || "主系统不会接收或保存 IEEE 凭据，只显示安全会话状态。";

    if (ieeeSessionSummary) {
      ieeeSessionSummary.textContent = taskHint(task.status)
        || "如遇 IEEE 登录或验证，可在这里打开、检查、重置或关闭专用会话。";
    }
    if (ieeeSessionBadge) {
      const badge = document.createElement("span");
      badge.className = badgeClass(sessionLabel);
      badge.textContent = sessionLabel;
      ieeeSessionBadge.replaceChildren(badge);
    }
    if (ieeeSessionMessage) {
      ieeeSessionMessage.textContent = sessionMessageText;
    }
    if (ieeeTaskStatus) {
      ieeeTaskStatus.textContent = task.status || "unknown";
    }
    if (ieeeSessionState) {
      ieeeSessionState.textContent = sessionLabel;
    }
    if (ieeeSessionUpdated) {
      ieeeSessionUpdated.textContent = sessionStatus?.updatedAt || "未检查";
    }
    if (ieeeProfileExists) {
      ieeeProfileExists.textContent = sessionStatus?.profileExists ? "已存在" : "未检测到";
    }
    if (ieeeProfileLocked) {
      ieeeProfileLocked.textContent = sessionStatus?.profileLocked ? "使用中" : "空闲";
    }
    if (ieeeLoginWindow) {
      ieeeLoginWindow.textContent = sessionStatus?.loginWindowOpen ? "已打开" : "未打开";
    }
    if (ieeePersonalLogin) {
      ieeePersonalLogin.textContent = sessionStatus?.personalLogin ? "已登录" : "未确认";
    }
    if (ieeeInstitutionAccess) {
      if (sessionStatus?.institutionAccess) {
        ieeeInstitutionAccess.textContent = sessionStatus.institutionName
          ? `已生效 · ${sessionStatus.institutionName}`
          : "已生效";
      } else {
        ieeeInstitutionAccess.textContent = "未确认";
      }
    }
    renderCounters(ieeeSessionCounters, sessionStatus?.counters || null);

    if (pauseButton instanceof HTMLButtonElement) {
      pauseButton.disabled = task.is_terminal || !pausableStatuses.has(task.status);
      pauseButton.setAttribute("aria-disabled", String(pauseButton.disabled));
    }
    if (resumeButton instanceof HTMLButtonElement) {
      resumeButton.disabled = !resumableStatuses.has(task.status);
      resumeButton.setAttribute("aria-disabled", String(resumeButton.disabled));
    }
  };

  const updatePanel = (task) => {
    panel.dataset.taskStatus = task.status;
    panel.dataset.active = activeStatuses.has(task.status) ? "true" : "false";
    if (statusBadge) {
      const badge = document.createElement("span");
      badge.className = badgeClass(task.status);
      badge.textContent = task.status;
      statusBadge.replaceChildren(badge);
    }
    if (progress instanceof HTMLProgressElement) {
      progress.value = task.progress_current || 0;
      if (task.progress_total > 0) {
        progress.max = task.progress_total;
      } else {
        progress.removeAttribute("max");
      }
    }
    if (progressText) {
      progressText.textContent = task.progress_total > 0
        ? `${task.progress_current}/${task.progress_total}`
        : "等待 worker";
    }
    if (progressPercent) {
      progressPercent.textContent = task.progress_percent == null
        ? ""
        : `${task.progress_percent}%`;
    }
    if (message) message.textContent = task.stage_message || "任务正在等待 worker。";
    if (stage) stage.textContent = `当前阶段：${task.stage || "queued"}`;
    if (error) {
      error.textContent = task.error_message || "";
      error.hidden = !task.error_message;
    }
    if (pendingHelp) {
      const hint = taskHint(task.status);
      pendingHelp.textContent = hint;
      pendingHelp.hidden = !hint;
    }
    renderSummary(task.result_summary || task.progress_summary);
    renderIeeeSession(task);
    if (disableTarget) {
      document.querySelectorAll(disableTarget).forEach((control) => {
        if (
          control instanceof HTMLButtonElement
          || control instanceof HTMLInputElement
        ) {
          control.disabled = !task.is_terminal;
        }
      });
    }
  };

  const stopPolling = () => {
    stopped = true;
    if (timerId !== null) window.clearTimeout(timerId);
  };

  const schedule = (delay = 1500) => {
    if (!stopped) timerId = window.setTimeout(pollTask, delay);
  };

  async function pollTask() {
    try {
      const response = await fetch(statusUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Task status request failed: ${response.status}`);
      const task = await response.json();
      consecutiveErrors = 0;
      updatePanel(task);
      if (task.is_terminal) {
        stopPolling();
        if (terminalReload && window.sessionStorage.getItem(terminalReloadKey) !== "1") {
          window.sessionStorage.setItem(terminalReloadKey, "1");
          window.location.reload();
        }
        return;
      }
      if (!activeStatuses.has(task.status) || terminalStatuses.has(task.status)) {
        stopPolling();
        return;
      }
      schedule(pollDelay(task.status));
    } catch (_pollError) {
      consecutiveErrors += 1;
      if (message) {
        message.textContent = "任务状态暂时无法读取，正在重试。";
      }
      schedule(consecutiveErrors <= 5 ? 1500 : 5000);
    }
  }

  window.addEventListener("pagehide", stopPolling, { once: true });
  pollTask();
}

document
  .querySelectorAll(".js-task-progress")
  .forEach(initializeTaskProgressPolling);
