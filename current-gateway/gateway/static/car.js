"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const api = window.SentinelDisplay;

  let tracks = [];
  let current = null;
  let prepared = false;
  let busy = false;
  let statusVersion = 0;
  let devicePoll = null;

  const deviceButtons = [
    "car-motor-a-cw-test",
    "car-motor-a-ccw-test",
    "car-motor-b-cw-test",
    "car-motor-b-ccw-test",
    "car-snapshot",
    "car-series",
  ];

  function canOpen() {
    return current && [
      "IDLE",
      "SELECT_EXPERIMENT",
      "AUTONOMOUS_CAR_SETUP",
      "TRACK_ACTIVE",
    ].includes(current.mode);
  }

  function carContextReady() {
    return Boolean(
      prepared &&
      current &&
      current.experiment === "autonomous-car" &&
      [
        "AUTONOMOUS_CAR_SETUP",
        "TRACK_ACTIVE",
      ].includes(current.mode)
    );
  }

  function syncControls() {
    $("car-prepare").disabled =
      busy || !canOpen();

    $("car-run").disabled = true;
    $("car-stop").disabled = true;

    document
      .querySelectorAll("[data-track-id]")
      .forEach(button => {
        button.disabled =
          busy ||
          !prepared ||
          !current ||
          !tracks.some(
            track =>
              track.id === button.dataset.trackId
          ) ||
          current.experiment !==
            "autonomous-car" ||
          ![
            "AUTONOMOUS_CAR_SETUP",
            "TRACK_ACTIVE",
          ].includes(current.mode);
      });

    deviceButtons.forEach(id => {
      const button = $(id);

      if (button) {
        button.disabled =
          busy || !carContextReady();
      }
    });
  }

  function setStatus(value) {
    current = value;

    prepared =
      [
        "AUTONOMOUS_CAR_SETUP",
        "TRACK_ACTIVE",
      ].includes(value.mode) &&
      value.experiment === "autonomous-car";

    const labels = {
      SETUP_REQUIRED:
        "Instructor Setup Required",
      IDLE:
        "Lab Ready",
      LED_SETUP:
        "LED setup",
      LED_READY:
        "LED program authorized",
      LED_RUNNING:
        "LED experiment running",
      LED_COMPLETE:
        "LED experiment complete",
      EXPERIMENT_COMPLETE:
        "Experiment complete",
      AUTONOMOUS_CAR_SETUP:
        "Waiting for track selection",
      TRACK_ACTIVE:
        "Track ready",
      RECOVERY:
        "Recovery requires an instructor",
    };

    $("car-display-status").textContent =
      "Lab Display: " +
      (labels[value.mode] || value.mode);

    const track = tracks.find(
      item => item.id === value.track
    );

    $("car-selected").textContent =
      "Selected: " +
      (track ? track.label : "none");

    syncControls();
  }

  function unavailable() {
    current = null;
    prepared = false;

    $("car-display-status").textContent =
      "Lab Display unavailable. Refresh its status before continuing.";

    $("car-selected").textContent =
      "Selected: unknown";

    syncControls();
  }

  async function postJson(path, data) {
    return api.readJson(
      path,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type":
            "application/json",
        },
        body: JSON.stringify(data),
      }
    );
  }

  async function mutateDisplay(path, data) {
    return api.validateStatus(
      await postJson(path, data)
    );
  }

  async function displayAction(fn) {
    if (busy) return;

    busy = true;
    statusVersion += 1;
    syncControls();

    try {
      const value = await fn();

      setStatus(value);

      $("car-result").textContent =
        "Display action accepted. " +
        $("car-display-status").textContent;

    } catch (error) {
      unavailable();

      const message =
        error.message === "DISPLAY_IN_USE"
          ? "Another workstation or active experiment owns the display."
          : error.message;

      $("car-result").textContent =
        message;

    } finally {
      busy = false;
      syncControls();
    }
  }

  function setLed(id, active) {
    const node = $(id);

    if (!node) return;

    node.classList.toggle(
      "is-active",
      active === true
    );
  }

  function updateDevices(value) {
    const car =
      value &&
      typeof value === "object"
        ? value.car
        : null;

    const trusted = Boolean(
      car &&
      car.fresh === true &&
      car.authenticated === true
    );

    const authState =
      $("car-device-auth");

    if (!authState) return;

    authState.classList.remove(
      "is-connected",
      "is-unavailable"
    );

    if (trusted) {
      authState.textContent =
        "Connected";

      authState.classList.add(
        "is-connected"
      );

    } else {
      authState.textContent =
        car && car.reachable === false
          ? "Unavailable"
          : "Telemetry unavailable";

      authState.classList.add(
        "is-unavailable"
      );
    }
  }

  async function refreshDevices() {
    try {
      updateDevices(
        await api.readJson(
          "/api/display/devices"
        )
      );
    } catch {
      updateDevices(null);
    }
  }

  async function refreshStatus() {
    const version =
      ++statusVersion;

    try {
      const value =
        api.validateStatus(
          await api.readJson(
            "/api/display/status"
          )
        );

      if (version !== statusVersion) {
        return;
      }

      setStatus(value);

    } catch {
      if (version === statusVersion) {
        unavailable();
      }
    }
  }

  async function deviceAction(action) {
    if (busy) return;

    busy = true;
    syncControls();

    try {
      const value =
        await postJson(
          "/api/experiments/autonomous-car/control",
          {action}
        );

      const actionNames = {
        MOTOR_A_CW_TEST: "Motor A clockwise",
        MOTOR_A_CCW_TEST: "Motor A counter-clockwise",
        MOTOR_B_CW_TEST: "Motor B clockwise",
        MOTOR_B_CCW_TEST: "Motor B counter-clockwise"
      };

      $("car-result").textContent =
        `${actionNames[action] || action} bounded pulse reported by CAR.`;

      await refreshDevices();

      return value;

    } catch (error) {
      $("car-result").textContent =
        error.message;

    } finally {
      busy = false;
      syncControls();
    }
  }

  function renderCaptures(frames) {
    const gallery =
      $("car-captures");

    gallery.replaceChildren();

    frames.forEach(frame => {
      const article =
        document.createElement("article");

      article.className =
        "car-capture-card";

      const image =
        document.createElement("img");

      image.src =
        frame.url +
        "?v=" +
        encodeURIComponent(
          frame.sha256.slice(0,12)
        );

      image.alt =
        "Verified autonomous car camera capture " +
        frame.index;

      const meta =
        document.createElement("div");

      meta.className =
        "car-capture-meta";

      const title =
        document.createElement("strong");

      title.textContent =
        "Capture " + frame.index;

      const detail =
        document.createElement("span");

      detail.textContent =
        frame.length +
        " bytes · " +
        frame.sha256.slice(0,12) +
        "…";

      meta.append(
        title,
        detail
      );

      article.append(
        image,
        meta
      );

      gallery.append(article);
    });
  }

  async function capture(mode) {
    if (busy) return;

    busy = true;
    syncControls();

    try {
      $("car-result").textContent =
        mode === "series"
          ? "Capturing three authenticated frames…"
          : "Capturing authenticated frame…";

      const value =
        await postJson(
          "/api/experiments/autonomous-car/snapshot",
          {mode}
        );

      renderCaptures(
        value.frames || []
      );

      $("car-result").textContent =
        value.frame_count === 1
          ? "Verified snapshot received."
          : "Verified three-frame series received.";

      await refreshDevices();

    } catch (error) {
      $("car-result").textContent =
        error.message;

    } finally {
      busy = false;
      syncControls();
    }
  }

  $("car-prepare").onclick =
    () => displayAction(
      async () => {
        if (!canOpen()) {
          throw new Error(
            "Ask an instructor to prepare the laboratory or return its display to idle."
          );
        }

        prepared = false;

        const value =
          await mutateDisplay(
            "/api/display/prepare",
            {
              experiment:
                "autonomous-car-v1",
            }
          );

        prepared =
          value.mode ===
            "AUTONOMOUS_CAR_SETUP" &&
          value.experiment ===
            "autonomous-car";

        return value;
      }
    );

  $("car-motor-a-cw-test").onclick =
    () => deviceAction(
      "MOTOR_A_CW_TEST"
    );

  $("car-motor-a-ccw-test").onclick =
    () => deviceAction(
      "MOTOR_A_CCW_TEST"
    );

  $("car-motor-b-cw-test").onclick =
    () => deviceAction(
      "MOTOR_B_CW_TEST"
    );

  $("car-motor-b-ccw-test").onclick =
    () => deviceAction(
      "MOTOR_B_CCW_TEST"
    );

  $("car-snapshot").onclick =
    () => capture("single");

  $("car-series").onclick =
    () => capture("series");

  document
    .querySelectorAll("[data-track-id]")
    .forEach(button => {
      button.onclick =
        () => displayAction(
          async () => {
            if (
              !prepared ||
              !current ||
              current.experiment !==
                "autonomous-car" ||
              ![
                "AUTONOMOUS_CAR_SETUP",
                "TRACK_ACTIVE",
              ].includes(current.mode) ||
              !tracks.some(
                track =>
                  track.id ===
                  button.dataset.trackId
              )
            ) {
              throw new Error(
                "Open the experiment before selecting an approved track."
              );
            }

            return mutateDisplay(
              "/api/display/track",
              {
                track_id:
                  button.dataset.trackId,
              }
            );
          }
        );
    });

  async function loadCatalog() {
    try {
      tracks =
        api.validateCatalog(
          await api.readJson(
            "/api/display/tracks"
          )
        );

      tracks.forEach(track => {
        const label =
          $("car-track-" +
            track.id +
            "-label");

        if (!label) {
          throw new Error(
            "Approved inline track is unavailable."
          );
        }

        label.textContent =
          track.label;
      });

      syncControls();

    } catch {
      tracks = [];

      $("car-result").textContent =
        "Approved tracks are unavailable. Reload this workstation page to retry.";

      unavailable();
    }
  }

  syncControls();
  loadCatalog();
  refreshDevices();

  devicePoll =
    window.setInterval(
      refreshDevices,
      1000
    );

  window.addEventListener(
    "beforeunload",
    () => {
      if (devicePoll) {
        window.clearInterval(
          devicePoll
        );
      }
    }
  );

  /*
   * Opening Experiment 2 establishes its Lab Display context
   * when the display is idle or waiting for experiment
   * selection. It never overrides another experiment.
   */
  (async () => {
    await refreshStatus();

    if (
      current &&
      [
        "IDLE",
        "SELECT_EXPERIMENT",
      ].includes(current.mode)
    ) {
      $("car-prepare").click();
    }
  })();

})();
