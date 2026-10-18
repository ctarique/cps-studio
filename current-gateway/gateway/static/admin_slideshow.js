"use strict";
(() => {
  const current = document.getElementById("cps-season-current");
  const status = document.getElementById("cps-season-status");
  const buttons = Array.from(document.querySelectorAll("[data-cps-season]"));
  const allowed = new Set(["fall", "spring", "winter"]);
  if (!current || !status || buttons.length !== 3) return;
  let ended = false;
  let saving = false;
  let selected = null;
  const title = season => season[0].toUpperCase() + season.slice(1);

  function render(season) {
    if (!allowed.has(season)) throw new Error("Invalid slideshow response");
    selected = season;
    current.textContent = title(season);
    buttons.forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.cpsSeason === season));
    });
  }
  function controls() {
    buttons.forEach(button => button.disabled = ended || saving);
  }
  async function refresh() {
    if (ended || saving) return;
    try {
      const response = await fetch("/api/display/slideshow", {
        credentials: "same-origin", cache: "no-store"
      });
      if (!response.ok) throw new Error("Slideshow state unavailable");
      const value = await response.json();
      if (ended || saving) return;
      render(value.season);
      status.textContent = "";
    } catch {
      if (!ended) {
        current.textContent = "Unavailable";
        status.textContent = "Unable to read the current slideshow.";
      }
    }
  }
  buttons.forEach(button => {
    button.addEventListener("click", async () => {
      const season = button.dataset.cpsSeason;
      if (ended || saving || !allowed.has(season) || season === selected) return;
      saving = true;
      controls();
      status.textContent = "Switching to " + title(season) + "…";
      try {
        const value = await window.SentinelWorkflow.call(
          "/api/admin/slideshow/season", {season}, {report: false}
        );
        if (ended) return;
        render(value.season);
        status.textContent = title(season) + " selected.";
      } catch (error) {
        if (!ended) status.textContent = error.message || "Season change failed.";
      } finally {
        saving = false;
        controls();
      }
    });
  });
  window.addEventListener("sentinel-session-ended", () => {
    ended = true;
    controls();
  });
  window.addEventListener("pagehide", () => { ended = true; });
  refresh();
  setInterval(refresh, 15000);
})();
