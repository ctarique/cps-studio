"use strict";

(() => {
  const $ = id => document.getElementById(id);

  const gateway = window.SentinelWorkflow;

  let ended = false;


  function formatTime(value) {
    if (value === undefined || value === null) {
      return "Not recorded";
    }

    const date = new Date(
      typeof value === "number"
        ? value * 1000
        : value
    );

    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString();
  }


  function experimentName(value) {
    return {
      "led-status-v1": "Experiment 1 · ESP32-CAM LED",
      "autonomous-car-v1": "Experiment 2 · Autonomous Car"
    }[value] || value;
  }


  function showReview(value) {
    const panel = $("run-review-detail");

    $("review-metadata").textContent = JSON.stringify({
      run_id: value.run_id || value.id,
      state: value.state,
      experiment: experimentName(value.experiment),
      access_model: value.access_model,
      owner_ref: value.owner_ref,
      submitted_at: formatTime(
        value.submitted_at || value.created_at
      ),
      rejection_reasons: value.reasons || [],
      source_sha256: value.source_sha256,
      program_sha256: value.program_sha256
    }, null, 2);

    /*
     * Submitted source is untrusted student content.
     * Always render as text, never HTML.
     */
    $("review-source").textContent =
      value.source ||
      "No submitted custom program is associated with this run.";

    panel.hidden = false;
  }


  async function refreshDevices() {
    const value = await gateway.call(
      "/api/admin/devices",
      undefined,
      {report: false}
    );

    if (ended) return;

    $("devices").replaceChildren();

    (value.devices || []).forEach(device => {
      const card = document.createElement("article");

      card.className = "mini-card";

      const title = document.createElement("h3");

      title.textContent =
        device.name +
        " · Device " +
        device.number;

      const experiment = document.createElement("p");

      experiment.textContent =
        experimentName(device.experiment);

      const badge = document.createElement("span");

      badge.className =
        "badge " +
        (
          device.status === "AVAILABLE"
            ? "ready"
            : "planned-badge"
        );

      badge.textContent =
        device.status === "AVAILABLE"
          ? "Available"
          : "Disconnected";

      card.append(
        title,
        experiment,
        badge
      );

      $("devices").append(card);
    });
  }


  window.addEventListener(
    "sentinel-review",
    event => showReview(event.detail)
  );


  window.addEventListener(
    "sentinel-session-ended",
    () => {
      ended = true;

      if ($("run-review-detail")) {
        $("run-review-detail").hidden = true;
      }
    }
  );


  window.addEventListener(
    "pagehide",
    () => {
      ended = true;
    }
  );


  window.addEventListener(
    "pageshow",
    event => {
      if (event.persisted) {
        location.reload();
      }
    }
  );


  refreshDevices().catch(() => {
    if (!ended) {
      $("devices").textContent =
        "Device profiles unavailable.";
    }
  });
})();


/* =========================================================
   Administration semantic status coloring
   ========================================================= */

(() => {
  "use strict";

  const statusClasses = [
    "admin-status-online",
    "admin-status-unlocked",
    "admin-status-disconnected"
  ];


  function applyStatusColor(element) {

    const value =
      element.textContent
        .trim()
        .toLowerCase();


    statusClasses.forEach(
      name => element.classList.remove(name)
    );


    if (value === "online") {

      element.classList.add(
        "admin-status-online"
      );

    } else if (value === "unlocked") {

      element.classList.add(
        "admin-status-unlocked"
      );

    } else if (value === "disconnected") {

      element.classList.add(
        "admin-status-disconnected"
      );

    }

  }


  function refreshStatusColors() {

    document
      .querySelectorAll("dd")
      .forEach(applyStatusColor);

  }


  refreshStatusColors();


  const observer =
    new MutationObserver(
      refreshStatusColors
    );


  observer.observe(
    document.body,
    {
      subtree: true,
      childList: true,
      characterData: true
    }
  );

})();
