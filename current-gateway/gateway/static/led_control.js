"use strict";

(() => {
  const healthText = document.getElementById("health");
  const deviceStatus = document.getElementById("device-status");
  const result = document.getElementById("result");
  const onButton = document.getElementById("led-on");
  const offButton = document.getElementById("led-off");
  const displayApi = window.SentinelDisplay;

  let busy = false;
  let displayPrepareAttempted = false;
  let gatewayLocked = true;
  let activeRunId = null;
  let verifyTimer = null;
  let countdownTimer = null;
  let verificationDeadline = 0;

  function clearActiveRun() {
    activeRunId = null;

    if (verifyTimer !== null) {
      clearTimeout(verifyTimer);
      verifyTimer = null;
    }

    if (countdownTimer !== null) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function syncButtons() {
    onButton.disabled =
      busy ||
      gatewayLocked ||
      activeRunId !== null;

    offButton.disabled = busy;
  }

  async function prepareDisplayIfIdle() {
    if (
      displayPrepareAttempted ||
      gatewayLocked ||
      !displayApi
    ) return;

    displayPrepareAttempted = true;

    try {
      const current = displayApi.validateStatus(
        await displayApi.readJson("/api/display/status")
      );

      // Selecting an experiment may claim an idle presentation,
      // but it never overrides another active workflow.
      if (!["IDLE", "SELECT_EXPERIMENT"].includes(current.mode)) return;

      displayApi.validateStatus(
        await displayApi.readJson(
          "/api/display/prepare",
          {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({
              experiment: "led-status-v1"
            })
          }
        )
      );

    } catch {
      // Display presentation is supporting UI only.
      // Failure never grants authority or blocks safety controls.
    }
  }

  function labelStage(value) {
    return String(value || "UNKNOWN")
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  async function health() {
    try {
      const response = await fetch("/api/health", {
        cache: "no-store",
        credentials: "same-origin"
      });

      if (!response.ok) throw new Error();

      const state = await response.json();
      gatewayLocked = Boolean(state.locked);

      healthText.textContent =
        gatewayLocked
          ? "Instructor setup is required before the experiment can run."
          : "Experiment ready.";

      syncButtons();

      if (!gatewayLocked) {
        void prepareDisplayIfIdle();
      }

    } catch {
      gatewayLocked = true;
      healthText.textContent =
        "Gateway unavailable. Physical state unknown.";
      syncButtons();
    }
  }

  function scheduleVerification(runId) {
    clearActiveRun();
    activeRunId = runId;
    verificationDeadline = Date.now() + 15000;

    let remaining = 5;

    deviceStatus.textContent =
      `ESP32-CAM reports LED ON. ` +
      `Automatic timeout active — ${remaining}s remaining.`;

    countdownTimer = setInterval(() => {
      remaining -= 1;

      if (activeRunId !== runId) return;

      if (remaining > 0) {
        deviceStatus.textContent =
          `ESP32-CAM reports LED ON. ` +
          `Automatic timeout active — ${remaining}s remaining.`;
      } else {
        clearInterval(countdownTimer);
        countdownTimer = null;

        deviceStatus.textContent =
          "Safety window elapsed. Verifying a fresh device report…";
      }
    }, 1000);

    verifyTimer = setTimeout(
      () => verifyRun(runId),
      6000
    );

    syncButtons();
  }

  async function verifyRun(runId) {
    if (activeRunId !== runId) return;
    verifyTimer = null;
    if (Date.now() >= verificationDeadline) {
      clearActiveRun();
      deviceStatus.textContent = "Completion was not confirmed within the observation window. Ask the instructor to review device state.";
      syncButtons();
      return;
    }
    if (busy) {
      verifyTimer = setTimeout(() => verifyRun(runId), 1000);
      return;
    }

    busy = true;
    syncButtons();
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 3000);

    try {
      const response = await fetch(
        "/api/experiments/led/status",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          cache: "no-store",
          body: JSON.stringify({
            run_id: runId
          }),
          signal: controller.signal
        }
      );

      let value;

      try {
        value = await response.json();
      } catch {
        value = {
          error: "INVALID_GATEWAY_RESPONSE"
        };
      }

      result.textContent =
        response.ok
          ? "Device report received."
          : "Device status could not be confirmed.";

      if (!response.ok) {
        clearActiveRun();

        deviceStatus.textContent =
          value.error === "NOT_CURRENT_DEVICE_RUN"
            ? "The ESP32 is reporting a different run. Physical state requires review."
            : "Fresh device status was not confirmed. Physical state may be unknown.";

        return;
      }

      const report = value.reported || {};

      if (
        report.led_reported === 0 &&
        ["COMPLETE", "STOPPED", "IDLE"].includes(report.state)
      ) {
        clearActiveRun();

        deviceStatus.textContent =
          `ESP32-CAM reports LED OFF · ${labelStage(report.state)}.`;

        result.textContent =
          "Guided interaction complete. ESP32-CAM reported LED OFF.";

      } else if (report.state === "RUNNING") {
        deviceStatus.textContent =
          "ESP32-CAM reports that the guided interaction is still running.";

        result.textContent =
          "The guided interaction is still running.";

      } else {
        clearActiveRun();

        deviceStatus.textContent =
          "Fresh device report received, but the expected completed LED-OFF state was not confirmed.";
      }

    } catch {
      clearActiveRun();

      result.textContent =
        "Gateway connection unavailable.";

      deviceStatus.textContent =
        "Fresh status was not confirmed. Physical state may be unknown.";

    } finally {
      clearTimeout(deadline);
      busy = false;
      await health();
      if (activeRunId === runId) {
        verifyTimer = setTimeout(() => verifyRun(runId), 1000);
      }
      syncButtons();
    }
  }

  async function control(action) {
    if (busy) return;

    busy = true;
    syncButtons();

    try {
      const response = await fetch(
        "/api/experiments/led/control",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          cache: "no-store",
          body: JSON.stringify({action})
        }
      );

      let value;

      try {
        value = await response.json();
      } catch {
        value = {
          error: "INVALID_GATEWAY_RESPONSE"
        };
      }

      result.textContent =
        response.ok
          ? "Command accepted by CPS Studio."
          : "Command was not accepted.";

      if (!response.ok) {
        if (value.error === "GATEWAY_LOCKED") {
          deviceStatus.textContent =
            "LED ON is unavailable until an instructor unlocks the Gateway.";

        } else if (value.error === "DEVICE_BUSY") {
          deviceStatus.textContent =
            "ESP32-CAM is already running a bounded LED interaction. Wait for completion or request LED OFF.";

        } else {
          deviceStatus.textContent =
            "Command was not confirmed. Physical state may be unknown.";
        }

        return;
      }

      if (action === "ON") {
        if (
          value.reported &&
          value.reported.led_reported === 1
        ) {
          result.textContent =
            "LED ON was reported by the ESP32-CAM. The safety timeout is active.";

          scheduleVerification(value.run_id);

        } else {
          deviceStatus.textContent =
            "Gateway accepted the ON command, but LED ON was not reported.";
        }

      } else {
        if (
          value.reported &&
          value.reported.led_reported === 0
        ) {
          clearActiveRun();
          window.dispatchEvent(new CustomEvent("sentinel-led-stopped", {detail: value}));

          deviceStatus.textContent =
            "ESP32-CAM reports LED OFF.";

          result.textContent =
            "LED OFF was reported by the ESP32-CAM.";

        } else {
          deviceStatus.textContent =
            "Gateway accepted the OFF command, but LED OFF was not reported.";
        }
      }

    } catch {
      result.textContent =
        "Gateway connection unavailable.";

      deviceStatus.textContent =
        "Command was not confirmed. Physical state may be unknown.";

    } finally {
      busy = false;

      await health();
      syncButtons();
    }
  }

  onButton.addEventListener(
    "click",
    () => control("ON")
  );

  offButton.addEventListener(
    "click",
    () => control("OFF")
  );

  window.addEventListener(
    "pagehide",
    clearActiveRun
  );

  health();
  setInterval(health, 5000);
})();
