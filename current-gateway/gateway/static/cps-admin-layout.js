"use strict";
(() => {
  // Layout only. Existing event listeners and authorization remain unchanged.
  const panel = document.querySelector(".system-presentation-control");
  if (!panel || panel.dataset.cpsAdminLayout === "rc3") return;

  const controls = panel.querySelector(".admin-display-state-controls");
  const preview = panel.querySelector(".admin-display-preview");
  if (!controls || !preview || !controls.contains(controls.querySelector('[data-display-state]'))) return;

  const trackButtons = Array.from(
    controls.querySelectorAll('button[data-display-state^="TRACK_"]')
  );

  // Move the original button nodes, never clone or replace them: their handlers
  // were installed by admin_display.js before this deferred script runs.
  if (trackButtons.length > 0) {
    const picker = document.createElement("details");
    picker.className = "cps-admin-track-picker";
    const summary = document.createElement("summary");
    const list = document.createElement("div");
    list.className = "cps-admin-track-list";
    list.setAttribute("role", "group");
    list.setAttribute("aria-label", "Tracks");
    picker.append(summary, list);
    controls.appendChild(picker);
    trackButtons.forEach(button => list.appendChild(button));

    const updateLabel = () => {
      const selected = trackButtons.find(button => button.getAttribute("aria-pressed") === "true");
      summary.textContent = selected
        ? "Tracks · " + selected.textContent.trim().replace(/\s+/g, " ")
        : "Tracks (" + trackButtons.length + ")";
    };
    const observer = new MutationObserver(updateLabel);
    trackButtons.forEach(button => observer.observe(button, {
      attributes: true, attributeFilter: ["aria-pressed"]
    }));
    window.addEventListener("pagehide", () => observer.disconnect(), { once: true });
    updateLabel();
  }

  const previewWrap = document.createElement("div");
  previewWrap.className = "cps-admin-preview-wrap";
  preview.parentNode.insertBefore(previewWrap, preview);
  previewWrap.appendChild(preview);

  const openDisplay = document.createElement("a");
  openDisplay.className = "cps-admin-preview-open";
  openDisplay.href = "/display?kiosk=0";
  openDisplay.target = "_blank";
  openDisplay.rel = "noopener";
  openDisplay.textContent = "Open Lab Display";
  previewWrap.appendChild(openDisplay);

  panel.dataset.cpsAdminLayout = "rc3";
})();
