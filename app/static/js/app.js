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
  const disableTarget = panel.dataset.disableTarget;

  const badgeClass = (status) => {
    if (status === "succeeded") return "badge badge-success";
    if (status === "failed" || status === "cancelled") return "badge badge-danger";
    return "badge badge-warning";
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

  const updatePanel = (task) => {
    panel.dataset.taskStatus = task.status;
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
    renderSummary(task.result_summary || task.progress_summary);
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
        if (window.sessionStorage.getItem(terminalReloadKey) !== "1") {
          window.sessionStorage.setItem(terminalReloadKey, "1");
          window.location.reload();
        }
        return;
      }
      schedule();
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
