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
