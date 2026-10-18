"use strict";

(() => {
  // SCPS SETUP SCREEN FIX 2026-10-13
  // The HDMI Chromium kiosk loads its display through the Pi loopback URL.
  // This is a visual-only distinction; it is not an authorization boundary.
  const displayParams = new URLSearchParams(window.location.search);
  const kioskMode = displayParams.get("kiosk");
  const loopbackHost =
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost";

  const isPhysicalTv =
    kioskMode === "1" ||
    (
      kioskMode !== "0" &&
      loopbackHost &&
      window.location.port === "8080"
    );
  document.body.classList.add(
    isPhysicalTv ? "scps-physical-tv" : "scps-workstation-display"
  );

  const $ = id =>
    document.getElementById(id);

  const api =
    window.SentinelDisplay;

  const trackIds = [
    "straight",
    "wide-straight",
    "curve",
    "wide-curve",
    "challenge",
    "wide-challenge",
    "circle",
    "wide-circle",
    "oval",
    "elliptical",
    "infinity",
    "wide-infinity"
  ];

  let tracks = null;
  let polling = false;
  let lastValid = performance.now();

  let generation = 0;
  let desiredTrack = null;
  let stopped = false;

  let currentPresentation = null;


  function delay(ms) {
    return new Promise(
      resolve => setTimeout(resolve, ms)
    );
  }


  function setBodyMode(mode) {
    document.body.dataset.displayMode =
      String(mode || "unknown")
        .toLowerCase()
        .replaceAll("_", "-");
  }


  function setVisibleState(state) {
    document.body.dataset.visibleState =
      state;
  }


  function animateState(key) {
    if (key === currentPresentation) {
      return;
    }

    currentPresentation = key;

    const shell =
      $("display-shell");

    shell.classList.remove(
      "display-state-enter"
    );

    void shell.offsetWidth;

    shell.classList.add(
      "display-state-enter"
    );
  }


  function setProgress(value = null) {
    const container =
      $("display-progress");

    const fill =
      $("display-progress-fill");

    if (value === null) {
      container.hidden = true;
      fill.style.width = "0%";
      return;
    }

    const bounded =
      Math.max(
        0,
        Math.min(
          100,
          Number(value)
        )
      );

    container.hidden = false;
    fill.style.width =
      bounded + "%";
  }


  function setView({
    key,
    visibleState,
    mode,
    context,
    kicker,
    title,
    tagline = null,
    ready = false,
    state = "",
    guidance = "",
    choices = false,
    progress = null
  }) {

    animateState(key);

    setVisibleState(
      visibleState
    );

    setBodyMode(
      mode
    );

    $("display-context").textContent =
      context;

    $("display-kicker").textContent =
      kicker;

    const titleElement =
      $("display-title");

    if (title === "CPS Studio") {
      // Do not replace an animated span on each one-second status poll.
      // Recreating it resets the CSS animation and looks like flickering.
      if (
        titleElement.textContent !== "CPS Studio" ||
        !titleElement.querySelector(".display-cps-glow")
      ) {
        titleElement.replaceChildren();

        const cpsElement =
          document.createElement("span");

        cpsElement.className =
          "display-cps-glow";

        cpsElement.textContent =
          "CPS";

        titleElement.append(
          cpsElement,
          document.createTextNode(" Studio")
        );
      }
    } else if (
      titleElement.textContent !== title ||
      titleElement.querySelector(".display-cps-glow")
    ) {
      titleElement.textContent = title;
    }


    const taglineElement =
      $("display-tagline");

    taglineElement.hidden =
      !tagline;

    taglineElement.textContent =
      tagline || "";


    $("display-ready").hidden =
      !ready;


    const stateElement =
      $("display-state");

    stateElement.hidden =
      !state;

    stateElement.textContent =
      state;


    const guidanceElement =
      $("display-guidance");

    guidanceElement.hidden =
      !guidance;

    guidanceElement.textContent =
      guidance;


    $("display-experiment-choice").hidden =
      !choices;


    setProgress(
      progress
    );
  }


  function clearTrack() {
    desiredTrack = null;
    generation += 1;

    $("track-surface").hidden =
      true;

    trackIds.forEach(id => {
      const surface =
        $("display-track-" + id);

      if (surface) {
        surface.hidden = true;
      }
    });

    document.body.classList.remove(
      "track-mode",
      "track-reveal"
    );

    $("display-presentation").hidden =
      false;
  }


  function presentLocked() {
    clearTrack();

    setView({
      key: "locked",
      visibleState: "locked",
      mode: "LOCKED",

      context: "",
      kicker: "",

      title:
        "CPS Studio",

      tagline:
        "Instructor Setup Required",

      state:
        "Locked",

      guidance: ""
    });
  }

  function presentIdle() {
    clearTrack();

    setView({
      key: "idle",
      visibleState: "idle",
      mode: "IDLE",

      context: "",
      kicker: "",

      title:
        "CPS Studio",

      tagline:
        "Secure access to real-world CPS experimentation.",

      state:
        "Gateway Unlocked",

      guidance:
        "Device readiness is checked before physical execution."
    });
  }

  function presentSelectExperiment() {
    clearTrack();

    setView({
      key: "select-experiment",
      visibleState: "select-experiment",
      mode: "SELECT_EXPERIMENT",

      context: "",
      kicker: "",

      title:
        "Select CPS App",

      state: "",
      guidance: "",

      choices: true
    });
  }

  function presentLed() {
    clearTrack();

    setView({
      key: "led-experiment",
      visibleState: "led-experiment",
      mode: "LED_EXPERIMENT",

      context:
        "EXPERIMENT 1 · ESP32-CAM",

      kicker:
        "BOUNDED PROGRAM EXECUTION",

      title:
        "LED Flasher",

      state:
        "Observe physical LED or Digital Twin",

      guidance:
        "Observe the ESP32-CAM onboard LED while interacting with the experiment."
    });
  }


  function presentAutonomousCar() {
    clearTrack();

    setView({
      key: "autonomous-car",
      visibleState: "autonomous-car",
      mode: "AUTONOMOUS_CAR",

      context:
        "EXPERIMENT 2 · ESP32-WROVER",

      kicker:
        "TV-AS-A-TRACK",

      title:
        "Autonomous Car",

      state:
        "Select a Track",

      guidance:
        ""
    });
  }


  function unavailable() {
    presentLocked();
  }


  async function presentTrack(value) {

    if (
      desiredTrack === value.track &&
      !$("track-surface").hidden
    ) {
      return;
    }

    clearTrack();

    const version =
      generation;

    if (!tracks) {
      tracks =
        api.validateCatalog(
          await api.readJson(
            "/api/display/tracks"
          )
        );
    }

    if (
      stopped ||
      version !== generation
    ) {
      return;
    }

    const track =
      tracks.find(
        item =>
          item.id === value.track
      );

    const surface =
      track &&
      $("display-track-" + track.id);

    if (!surface) {
      throw new Error(
        "Approved inline track is unavailable."
      );
    }

    setView({
      key:
        "track-" + track.id,

      visibleState:
        "track-" + track.id,

      mode:
        "TRACK_" +
        track.id.toUpperCase(),

      context:
        "EXPERIMENT 2 · ESP32-WROVER",

      kicker:
        "TV-AS-A-TRACK",

      title:
        track.label,

      state:
        "Loading"
    });

    await delay(2500);

    if (
      stopped ||
      version !== generation
    ) {
      return;
    }

    desiredTrack =
      track.id;

    surface.hidden =
      false;

    $("display-presentation").hidden =
      true;

    document.body.classList.add(
      "track-mode",
      "track-reveal"
    );

    document.body.dataset.displayMode =
      "track-" + track.id;

    document.body.dataset.visibleState =
      "track-" + track.id;

    $("track-surface").hidden =
      false;
  }


  async function present(value) {

    /*
     * Current backend states are mapped to the
     * simplified visible Lab Display model.
     */

    if (
      value.mode === "SETUP_REQUIRED" ||
      value.mode === "RECOVERY"
    ) {
      presentLocked();
      return;
    }


    if (value.mode === "IDLE") {
      presentIdle();
      return;
    }


    if (
      value.mode === "SELECT_EXPERIMENT"
    ) {
      presentSelectExperiment();
      return;
    }


    if (
      value.mode === "LED_SETUP" ||
      value.mode === "LED_READY" ||
      value.mode === "LED_RUNNING" ||
      value.mode === "LED_COMPLETE"
    ) {
      presentLed();
      return;
    }


    if (
      value.mode ===
      "AUTONOMOUS_CAR_SETUP"
    ) {
      presentAutonomousCar();
      return;
    }


    if (
      value.mode === "TRACK_ACTIVE"
    ) {
      await presentTrack(value);
      return;
    }


    if (
      value.mode ===
      "EXPERIMENT_COMPLETE"
    ) {
      presentAutonomousCar();
      return;
    }


    unavailable();
  }


  async function refresh() {

    if (
      polling ||
      stopped
    ) {
      return;
    }

    polling = true;

    const started =
      performance.now();

    try {

      const value =
        api.validateStatus(
          await api.readJson(
            "/api/display/status"
          )
        );

      if (
        stopped ||
        performance.now() -
          started >= 5000
      ) {
        return;
      }

      lastValid =
        performance.now();

      await present(value);

    } catch {

      if (!stopped) {
        unavailable();
      }

    } finally {

      polling = false;

    }
  }


  /*
   * Never leave stale experiment content on
   * the physical display if Gateway polling stops.
   */
  setInterval(
    () => {

      if (
        !stopped &&
        performance.now() -
          lastValid >= 5000
      ) {
        unavailable();
      }

    },
    500
  );


  setInterval(
    refresh,
    1000
  );


  window.addEventListener(
    "pagehide",
    () => {
      stopped = true;
      clearTrack();
    }
  );


  refresh();

})();
