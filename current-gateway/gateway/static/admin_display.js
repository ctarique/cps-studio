"use strict";

(() => {

  const $ = id =>
    document.getElementById(id);

  const api =
    window.SentinelDisplay;

  const buttons =
    Array.from(
      document.querySelectorAll(
        "[data-display-state]"
      )
    );

  const labels = {
    LOCKED: "Setup",
    READY: "Ready",
    SELECT_EXPERIMENT: "Select CPS Apps",
    LED_FLASHER: "LED Flasher",
    AUTONOMOUS_CAR: "Autonomous Car",
    TRACK_STRAIGHT: "Track 01 — Straight",
    TRACK_WIDE_STRAIGHT: "Track 02 — Straight Wide",
    TRACK_CURVE: "Track 03 — Curve",
    TRACK_WIDE_CURVE: "Track 04 — Curve Wide",
    TRACK_CHALLENGE: "Track 05 — Challenge",
    TRACK_WIDE_CHALLENGE: "Track 06 — Challenge Wide",
    TRACK_CIRCLE: "Track 07 — Circle",
    TRACK_WIDE_CIRCLE: "Track 08 — Circle Wide",
    TRACK_OVAL: "Track 09 — Oval",
    TRACK_ELLIPTICAL: "Track 10 — Oval Wide",
    TRACK_INFINITY: "Track 11 — Infinity",
    TRACK_WIDE_INFINITY: "Track 12 — Infinity Wide"
  };

  let version = 0;
  let ended = false;
  let busy = false;
  let current = null;


  function canonicalState(state) {

    if (
      state.mode === "SETUP_REQUIRED" ||
      state.mode === "RECOVERY"
    ) {
      return "LOCKED";
    }

    if (state.mode === "IDLE") {
      return "READY";
    }

    if (
      state.mode === "SELECT_EXPERIMENT"
    ) {
      return "SELECT_EXPERIMENT";
    }

    if (
      state.mode === "LED_SETUP" ||
      state.mode === "LED_READY" ||
      state.mode === "LED_RUNNING" ||
      state.mode === "LED_COMPLETE"
    ) {
      return "LED_FLASHER";
    }

    if (
      state.mode ===
        "AUTONOMOUS_CAR_SETUP" ||
      state.mode ===
        "EXPERIMENT_COMPLETE"
    ) {
      return "AUTONOMOUS_CAR";
    }

    if (
      state.mode === "TRACK_ACTIVE"
    ) {

      const tracks = {
        "straight": "TRACK_STRAIGHT",
        "wide-straight": "TRACK_WIDE_STRAIGHT",
        "curve": "TRACK_CURVE",
        "wide-curve": "TRACK_WIDE_CURVE",
        "challenge": "TRACK_CHALLENGE",
        "wide-challenge": "TRACK_WIDE_CHALLENGE",
        "circle": "TRACK_CIRCLE",
        "wide-circle": "TRACK_WIDE_CIRCLE",
        "oval": "TRACK_OVAL",
        "elliptical": "TRACK_ELLIPTICAL",
        "infinity": "TRACK_INFINITY",
        "wide-infinity": "TRACK_WIDE_INFINITY"
      };

      return tracks[state.track] || null;
    }

    return null;
  }


  function setMessage(message = "") {

    const element =
      $("admin-display-result");

    if (!element) return;

    element.textContent = message;
    element.hidden = !message;
  }


  function syncButtons() {

    buttons.forEach(button => {

      const selected =
        button.dataset.displayState ===
        current;

      button.setAttribute(
        "aria-pressed",
        selected ? "true" : "false"
      );

    });
  }


  function show(value) {

    const state =
      api.validateStatus(value);

    current =
      canonicalState(state);

    $("admin-display-mode").textContent =
      state.mode === "RECOVERY" ? "Recovery required" : labels[current] || "Unavailable";

    syncButtons();
  }


  function unavailable() {

    current = null;

    $("admin-display-mode").textContent =
      "Unavailable";

    syncButtons();
  }


  async function refresh() {

    const requestVersion =
      ++version;

    try {

      const value =
        await api.readJson(
          "/api/display/status"
        );

      if (
        !ended &&
        requestVersion === version
      ) {
        show(value);
      }

    } catch {

      if (
        !ended &&
        requestVersion === version
      ) {
        unavailable();
      }

    }
  }


  async function postState(mode) {

    const csrf =
      document.querySelector(
        'meta[name="sentinel-csrf"]'
      );

    if (!csrf || !csrf.content) {
      throw new Error(
        "Administrator session unavailable."
      );
    }

    const response =
      await fetch(
        "/api/display/state",
        {
          method: "POST",

          credentials: "same-origin",

          cache: "no-store",

          headers: {
            "X-Sentinel-CSRF":
              csrf.content,

            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify({
              mode
            })
        }
      );

    let value;

    try {
      value =
        await response.json();
    } catch {
      value = {
        error:
          "INVALID_GATEWAY_RESPONSE"
      };
    }

    if (response.status === 401) {

      window.dispatchEvent(
        new Event(
          "sentinel-session-ended"
        )
      );

      location.replace(
        "/admin/login"
      );

      throw new Error(
        "Administrator session expired."
      );
    }

    if (!response.ok) {

      const error =
        new Error(
          value.error ||
          "DISPLAY_REQUEST_FAILED"
        );

      error.code =
        value.error;

      throw error;
    }

    return value;
  }


  async function selectState(mode) {

    if (
      busy ||
      ended ||
      !labels[mode]
    ) {
      return;
    }

    setMessage("");

    /*
     * Locked must reflect the REAL Gateway lock state.
     * Reuse the existing recovery/lock control rather than
     * creating a presentation-only fake lock.
     */
    if (mode === "LOCKED") {
      busy = true;
      try {
        // Public display modes are presentation, not execution authority.
        const health = await api.readJson("/api/health", {credentials: "same-origin"});
        if (typeof health.locked !== "boolean") throw new Error("Invalid Gateway state.");
        if (!health.locked) {
          const workflow = window.SentinelWorkflow;
          if (!workflow) throw new Error("Gateway lock control unavailable.");
          await workflow.action(async () => {
            await workflow.call("/api/admin/recovery", {action: "LOCK_STOP"});
            await workflow.health();
          });
          const confirmed = await api.readJson("/api/health", {credentials: "same-origin"});
          if (confirmed.locked !== true) throw new Error("Gateway lock was not confirmed. Review Gateway Status.");
        }
        setMessage("Gateway locked. Review the recorded device response above.");
        await refresh();
      } catch (error) {
        setMessage(error.message || "Gateway lock could not be confirmed.");
      } finally {
        busy = false;
      }
      return;
    }

    busy = true;

    try {

      const value =
        await postState(mode);

      version += 1;

      show(value);

    } catch (error) {

      if (
        error.code ===
        "GATEWAY_LOCKED"
      ) {

        setMessage(
          "Unlock the Gateway before selecting this Lab Display state."
        );

      } else {

        setMessage(
          "The Lab Display state could not be changed."
        );

      }

      await refresh();

    } finally {

      busy = false;

    }
  }


  buttons.forEach(button => {

    button.addEventListener(
      "click",
      () => {
        void selectState(
          button.dataset.displayState
        );
      }
    );

  });


  window.addEventListener(
    "sentinel-display-status",
    event => {

      version += 1;

      try {
        show(event.detail);
      } catch {
        unavailable();
      }

    }
  );


  window.addEventListener(
    "sentinel-session-ended",
    () => {

      ended = true;
      version += 1;
      unavailable();

    }
  );


  window.addEventListener(
    "pagehide",
    () => {

      ended = true;
      version += 1;

    }
  );


  setInterval(
    () => {
      if (!ended) {
        void refresh();
      }
    },
    3000
  );


  void refresh();

})();
