"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const instructor = document.body.dataset.role === "instructor";
  let selectedRun = null;
  let busy = false;
  let gatewayLocked = null;

  function showResult(value) {
    const result = $("result");
    if (!result) return;
    if (value && typeof value === "object" && typeof value.locked === "boolean" && "response_available" in value) {
      if (!value.locked) {
        result.textContent = "Gateway unlocked. Device readiness will be checked before physical execution.";
      } else if (value.response_available) {
        result.textContent = "Gateway locked. Device response recorded. Physical state has not been observed here.";
      } else {
        result.textContent = "Gateway locked. A fresh device response was not confirmed. Ask the instructor to review device state.";
      }
    } else {
      result.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }
  }

  async function call(path, data, options = {}) {
    const headers = instructor
      ? {"X-Sentinel-CSRF": document.querySelector('meta[name="sentinel-csrf"]').content}
      : {};
    const opts = {method: data === undefined ? "GET" : "POST", headers,
      credentials: "same-origin", cache: "no-store"};
    if (data !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(data);
    }
    const response = await fetch(path, opts);
    let value;
    try { value = await response.json(); }
    catch { value = {error: "INVALID_GATEWAY_RESPONSE"}; }
    // An issued token belongs only in its dedicated, one-time panel.
    if (options.report !== false) {
      const printable = {...value};
      if (typeof printable.token === "string") printable.token = "[shown only in the issuance panel]";
      showResult(printable);
    }
    if (instructor && response.status === 401) {
      window.dispatchEvent(new Event("sentinel-session-ended"));
      location.replace("/admin/login");
    }
    if (!response.ok) {
      const error = new Error(instructor && response.status === 401
        ? "Administrator session expired. Sign in again."
        : value.error || "Request failed; review the recorded result.");
      error.payload = value;
      error.status = response.status;
      throw error;
    }
    return value;
  }

  function validRunId() { return /^[0-9a-f]{32}$/.test($("run").value.trim()); }
  function rid() {
    if (!validRunId()) throw new Error("Select a valid run ID.");
    return $("run").value.trim();
  }
  function selectedMatches() {
    return selectedRun && selectedRun.run_id === $("run").value.trim();
  }
  function syncControls() {
    // Presentation controls own their independent request lifecycle.
    document.querySelectorAll("button:not([data-display-state])").forEach(button => { button.disabled = busy; });
    if ($("gateway-lock")) $("gateway-lock").disabled = busy || gatewayLocked !== false;
    if ($("gateway-unlock")) $("gateway-unlock").disabled = busy || gatewayLocked !== true;
    if ($("submit")) $("submit").disabled = busy;
    if ($("prepare-display")) $("prepare-display").disabled = busy;
    if ($("refresh")) $("refresh").disabled = busy;
    document.querySelectorAll("[data-act]").forEach(button => {
      const operation = button.dataset.act;
      let enabled = validRunId();
      if (operation === "execute") enabled = enabled && selectedMatches() && selectedRun.can_run === true;
      if (operation === "exception") enabled = enabled && selectedMatches() && selectedRun.can_request_exception === true;
      button.disabled = busy || !enabled;
    });
    window.dispatchEvent(new CustomEvent("sentinel-controls", {detail: {busy}}));
  }
  function setSelected(run) {
    selectedRun = run ? {...run, run_id: run.run_id || run.id} : null;
    if (run) $("run").value = selectedRun.run_id;
    if ($("run-state")) {
      $("run-state").textContent = run
        ? [labelStage(run.state), ...(run.reasons || [])].join(" · ")
        : "Select or submit an attempt to see its available actions.";
    }
    syncControls();
  }
  function clearSelection() {
    $("run").value = "";
    setSelected(null);
  }
  async function action(fn) {
    if (busy) return;
    busy = true;
    syncControls();
    try { await fn(); }
    catch (error) {
      const message = error instanceof TypeError
        ? "Connection unavailable. Do not retry execution blindly; ask the instructor to check the run and Gateway state."
        : error.message;
      const result = $("result");
      showResult((result ? result.textContent + "\n" : "") + message);
    } finally {
      busy = false;
      syncControls();
    }
  }
  async function loadRun(runId, report = true) {
    const value = await call("/api/runs/" + runId, undefined, {report});
    if ($("run").value.trim() === runId) setSelected(value);
    return value;
  }
  async function selectRun(runId) {
    clearSelection();
    $("run").value = runId;
    await loadRun(runId);
  }
  function labelStage(stage) {
    return String(stage || "UNKNOWN").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
  }
  async function refreshRuns(report = true) {
    const value = await call("/api/runs", undefined, {report});
    $("runs").replaceChildren();
    if (!value.runs.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "No attempts recorded yet.";
      $("runs").append(empty);
    }
    value.runs.forEach(run => {
      const row = document.createElement("div");
      row.className = "run-row";
      const select = document.createElement("button");
      select.type = "button";
      select.className = "secondary-button compact-button";
      select.textContent = "Select";
      select.onclick = () => action(() => selectRun(run.run_id || run.id));
      const text = document.createElement("span");
      text.textContent = (run.run_id || run.id) + " · " + labelStage(run.state);
      row.append(select, text);
      $("runs").append(row);
    });
    syncControls();
  }

  $("run").addEventListener("input", () => setSelected(null));

  if ($("submit")) $("submit").onclick = () => action(async () => {
    clearSelection();

    try {
      const value = await call("/api/submissions", {
        source: $("source").value,
        experiment: "led-status-v1"
      });

      setSelected({...value, can_run: false, can_request_exception: false});
      await loadRun(value.run_id, false);
      await refreshRuns(false);
    } catch (error) {
      if (error.payload && error.payload.run_id) {
        setSelected({...error.payload, can_run: false, can_request_exception: false});
        await loadRun(error.payload.run_id, false);
        await refreshRuns(false);
      }
      throw error;
    }
  });

  document.querySelectorAll("[data-act]").forEach(button => {
    button.onclick = () => action(async () => {
      const operation = button.dataset.act;
      const runId = rid();
      if (operation === "details") return loadRun(runId);
      if (operation === "execute" && !(selectedMatches() && selectedRun.can_run === true))
        throw new Error("Refresh the run details before choosing Run.");
      if (operation === "exception" && !(selectedMatches() && selectedRun.can_request_exception === true))
        throw new Error("This attempt cannot request an exception in its current state.");
      const adminOperation = ["review", "evidence"].includes(operation);
      const path = "/api/" + (adminOperation ? "admin/" : "") + "runs/" + runId + "/" + operation;
      // Clear execution eligibility before dispatch so a lost reply cannot expose retry.
      if (["execute", "exception"].includes(operation)) setSelected(null);
      const value = await call(path, ["review", "evidence"].includes(operation) ? undefined : {});
      if (operation === "review") window.dispatchEvent(new CustomEvent("sentinel-review", {detail: value}));
      if (operation === "evidence") {
        const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: "application/json"}));
        const link = document.createElement("a");
        link.href = url;
        link.download = "run-" + runId + ".json";
        link.click();
        URL.revokeObjectURL(url);
      }
      await loadRun(runId, false);
      await refreshRuns(false);
    });
  });
  document.querySelectorAll("[data-recovery]").forEach(button => {
    button.onclick = () => action(async () => {
      const recoveryAction = button.dataset.recovery;

      try {
        const recoveryResult = await call(
          "/api/admin/recovery",
          {action: recoveryAction}
        );

        /*
         * UNLOCK performs a STATUS exchange.
         * LOCK_STOP performs an authenticated STOP exchange.
         *
         * A successful real-device response therefore establishes
         * recent authenticated Gateway-to-device communication.
         */
        if (
          recoveryAction === "UNLOCK" ||
          recoveryAction === "LOCK_STOP"
        ) {
          try {
            const healthResponse = await fetch(
              "/api/health",
              {cache: "no-store"}
            );

            const gatewayState =
              await healthResponse.json();

            const physicalTransport =
              String(
                gatewayState.transport || ""
              ).toLowerCase() !== "simulator";

            if (
              physicalTransport &&
              recoveryResult &&
              recoveryResult.response_available
            ) {
              document.body.dataset.camHealth =
                "Connected";
            }
          } catch {
            // Main health() call below handles Gateway state.
          }
        }

      } catch (error) {
        /*
         * On a real transport, a failed Lock/Unlock device
         * exchange means the current device connection cannot
         * be confirmed.
         */
        try {
          const healthResponse = await fetch(
            "/api/health",
            {cache: "no-store"}
          );

          const gatewayState =
            await healthResponse.json();

          if (
            String(
              gatewayState.transport || ""
            ).toLowerCase() !== "simulator"
          ) {
            document.body.dataset.camHealth =
              "Unavailable";
          }
        } catch {
          // Gateway itself may also be unavailable.
        }

        await health();
        throw error;
      }

      await health();
    });
  });
  $("refresh").onclick = () => action(() => refreshRuns());
  if ($("prepare-display")) $("prepare-display").onclick = () => action(() =>
    call("/api/display/prepare", {experiment: "led-status-v1"}));
  if ($("display-idle")) $("display-idle").onclick = () => action(async () => {
    const value = await call("/api/display/idle", {});
    window.dispatchEvent(new CustomEvent("sentinel-display-status", {detail: value}));
  });

    async function health() {
    const serviceElement = $("gateway-service");
    const accessElement = $("health");
    const camElement = $("esp32-cam-health");
    const carElement = $("esp32-wrover-health");
    const carRssiElement = $("esp32-wrover-rssi");
    const carRttElement = $("esp32-wrover-rtt");

    const setSystemClass = (element, value) => {
      if (!element) return;

      element.classList.remove(
        "system-health-online",
        "system-health-unavailable",
        "system-health-unknown"
      );

      if (value) {
        element.classList.add(value);
      }
    };

    try {
      const response = await fetch("/api/health", {
        cache: "no-store"
      });

      const state = await response.json();
      gatewayLocked = response.ok && typeof state.locked === "boolean" ? state.locked : null;

      // Gateway application/service health.
      if (serviceElement) {
        if (response.ok) {
          serviceElement.textContent = "Online";
          setSystemClass(
            serviceElement,
            "system-health-online"
          );
        } else {
          serviceElement.textContent = "Degraded";
          setSystemClass(
            serviceElement,
            "system-health-unavailable"
          );
        }
      }

      // Instructor experiment-access state.
      if (accessElement) {
        accessElement.textContent =
          state.locked ? "Locked" : "Unlocked";

        accessElement.classList.toggle(
          "gateway-status-locked",
          Boolean(state.locked)
        );

        accessElement.classList.toggle(
          "gateway-status-unlocked",
          !state.locked
        );
      }

      const unlockButton = $("gateway-unlock");
      if (unlockButton) {
        unlockButton.disabled = busy || gatewayLocked !== true;
      }

      const lockButton = $("gateway-lock");
      if (lockButton) {
        lockButton.disabled = busy || gatewayLocked !== false;
      }

      // Never claim that the physical ESP32-CAM is connected
      // when the Gateway is using the development simulator.
      if (camElement) {
        const physicalTransport =
          String(state.transport || "").toLowerCase() !==
          "simulator";

        if (!physicalTransport) {
          camElement.textContent = "Disconnected";
          setSystemClass(
            camElement,
            "system-health-unknown"
          );
        } else {
          const camHealth =
            String(
              state.esp32_cam_health || "NOT_CHECKED"
            ).toUpperCase();

          if (camHealth === "CONNECTED") {
            camElement.textContent = "Connected";
            setSystemClass(
              camElement,
              "system-health-online"
            );
          } else if (camHealth === "UNAVAILABLE") {
            camElement.textContent = "Unavailable";
            setSystemClass(
              camElement,
              "system-health-unavailable"
            );
          } else {
            camElement.textContent = "Not checked";
            setSystemClass(
              camElement,
              "system-health-unknown"
            );
          }
        }
      }

      // Live authenticated ESP32-WROVER RSSI.
      //
      // This endpoint exposes transient authenticated device telemetry.
      // Failure to retrieve RSSI must not change Gateway health state.
      if (carRssiElement) {
        try {
          const devicesResponse = await fetch(
            "/api/display/devices",
            {cache: "no-store"}
          );

          if (!devicesResponse.ok) throw new Error("Device telemetry unavailable.");
          const devicesState =
            await devicesResponse.json();

          window.SentinelStatusRtt.update(carRttElement, devicesState.car);

          const rssi =
            devicesState &&
            devicesState.car &&
            devicesState.car.authenticated === true &&
            devicesState.car.fresh === true
              ? devicesState.car.rssi_dbm
              : null;

          if (
            Number.isInteger(rssi) &&
            rssi >= -127 &&
            rssi <= 0
          ) {
            carRssiElement.textContent =
              "RSSI " + String(rssi) + " dBm";

            carRssiElement.hidden =
              false;
          } else {
            carRssiElement.textContent =
              "RSSI —";

            carRssiElement.hidden =
              true;
          }

        } catch {
          window.SentinelStatusRtt.update(carRttElement, null);
          carRssiElement.textContent =
            "RSSI —";

          carRssiElement.hidden =
            true;
        }
      }

      // Live authenticated ESP32-WROVER connectivity.
      if (carElement) {
        const carHealth =
          String(
            state.esp32_wrover_health || "NOT_CHECKED"
          ).toUpperCase();

        if (carHealth === "CONNECTED") {
          carElement.textContent = "Connected";
          setSystemClass(
            carElement,
            "system-health-online"
          );
        } else if (
          carHealth === "UNAVAILABLE" ||
          carHealth === "DISCONNECTED"
        ) {
          carElement.textContent = "Unavailable";
          setSystemClass(
            carElement,
            "system-health-unavailable"
          );
        } else {
          carElement.textContent = "Not checked";
          setSystemClass(
            carElement,
            "system-health-unknown"
          );
        }
      }

    } catch {
      window.SentinelStatusRtt.update(carRttElement, null);
      gatewayLocked = null;
      if ($("gateway-lock")) $("gateway-lock").disabled = true;
      if ($("gateway-unlock")) $("gateway-unlock").disabled = true;
      if (serviceElement) {
        serviceElement.textContent = "Unavailable";
        setSystemClass(
          serviceElement,
          "system-health-unavailable"
        );
      }

      if (accessElement) {
        accessElement.textContent = "Unknown";
        accessElement.classList.remove(
          "gateway-status-locked",
          "gateway-status-unlocked"
        );
      }

      if (camElement) {
        camElement.textContent = "Unknown";
        setSystemClass(
          camElement,
          "system-health-unknown"
        );
      }
    }
  }

  if ($("logout")) $("logout").onclick = () => action(async () => {
    window.dispatchEvent(new Event("sentinel-session-ended"));
    await call("/api/admin/logout", {});
    location.replace("/admin/login");
  });
  if (instructor) {
    setInterval(async () => {
      try {
        const response = await fetch("/admin", {cache: "no-store", credentials: "same-origin"});
        if (response.redirected || response.status === 401) {
          window.dispatchEvent(new Event("sentinel-session-ended"));
          location.replace("/admin/login");
        }
      } catch { /* A lost connection never grants or renews authority. */ }
    }, 30000);
  }
  window.SentinelWorkflow = {call, action, health, showResult, refreshRuns, selectRun, loadRun, syncControls,
    isBusy: () => busy};
  syncControls();
  health();
  setInterval(health, 5000);
})();
