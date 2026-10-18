"use strict";

(() => {
  const $ = id => document.getElementById(id);

  const source = $("custom-source");
  const templateSelect = $("custom-template");
  const templateLoadButton = $("custom-template-load");

  if (!source || !templateSelect || !templateLoadButton) return;

  const submitButton = $("custom-submit");
  const runButton = $("custom-run");
  const checkButton = $("custom-check");
  const refreshButton = $("custom-refresh");

  const status = $("custom-status");
  const result = $("custom-result");
  const runs = $("custom-runs");

  let selectedRun = null;
  let busy = false;
  let checkedSource = null;
  let observingRun = null;
  let completionTimer = null;
  let completionAttempts = 0;
  let completionDeadline = 0;

  const templates = Object.freeze({
    "single-pulse": `void experiment() {
  led(1);
  wait_ms(1000);
  led(0);
  status();
}`,

    "triple-blink": `void experiment() {
  led(1);
  wait_ms(300);
  led(0);
  wait_ms(300);

  led(1);
  wait_ms(300);
  led(0);
  wait_ms(300);

  led(1);
  wait_ms(300);
  led(0);
  status();
}`,

    "heartbeat": `void experiment() {
  led(1);
  wait_ms(120);
  led(0);
  wait_ms(120);
  led(1);
  wait_ms(250);
  led(0);
  wait_ms(800);

  led(1);
  wait_ms(120);
  led(0);
  wait_ms(120);
  led(1);
  wait_ms(250);
  led(0);
  status();
}`,

    "slow-beacon": `void experiment() {
  led(1);
  wait_ms(700);
  led(0);
  wait_ms(700);

  led(1);
  wait_ms(700);
  led(0);
  wait_ms(700);

  led(1);
  wait_ms(700);
  led(0);
  status();
}`,

    "accelerating": `void experiment() {
  led(1);
  wait_ms(700);
  led(0);
  wait_ms(500);

  led(1);
  wait_ms(500);
  led(0);
  wait_ms(300);

  led(1);
  wait_ms(300);
  led(0);
  wait_ms(150);

  led(1);
  wait_ms(150);
  led(0);
  status();
}`,

    "two-short-one-long": `void experiment() {
  led(1);
  wait_ms(500);
  led(0);
  wait_ms(500);

  led(1);
  wait_ms(500);
  led(0);
  wait_ms(500);

  led(1);
  wait_ms(1000);
  led(0);
  status();
}`
  });


  function labelStage(value) {
    return String(value || "UNKNOWN")
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/\b\w/g, c => c.toUpperCase());
  }


  function canCheck(run) {
    return run &&
      ["COMMUNICATING", "DEVICE_REPORTED", "INCOMPLETE"]
        .includes(run.state);
  }


  function sync() {
    const waiting = busy || observingRun !== null;
    submitButton.disabled = waiting;
    source.disabled = waiting;
    templateSelect.disabled = waiting;

    runButton.disabled =
      busy ||
      !selectedRun ||
      selectedRun.can_run !== true ||
      checkedSource === null ||
      source.value !== checkedSource;

    checkButton.disabled =
      busy ||
      !canCheck(selectedRun);

    refreshButton.disabled = busy;
    templateLoadButton.disabled = waiting;
  }


  function showError(error) {
    const payload = error && error.payload ? error.payload : {};

    const code = payload.error || "";

    const friendly = {
      GATEWAY_LOCKED:
        "The experiment is not currently available for execution. Ask the instructor to prepare the Gateway.",

      DEVICE_BUSY:
        "The ESP32-CAM is already running an experiment. Wait for it to finish before trying again.",

      POLICY_REJECTED:
        "The program is outside the permitted experiment policy.",

      WORKFLOW_ORDER:
        "This action is not valid for the program's current state.",

      NOT_CURRENT_DEVICE_RUN:
        "The ESP32-CAM is reporting a different run. Ask the instructor to review the experiment state.",

      STATUS_UNAVAILABLE:
        "A fresh device report could not be obtained."
    }[code];

    result.textContent =
      friendly ||
      error.message ||
      "The request could not be completed.";
  }


  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options
    });

    let value;

    try {
      value = await response.json();
    } catch {
      value = {error: "INVALID_GATEWAY_RESPONSE"};
    }

    if (!response.ok) {
      const error = new Error(
        value.error || "The request could not be completed."
      );

      error.payload = value;
      error.status = response.status;

      throw error;
    }

    return value;
  }


  function describeRun(run) {
    const reasons =
      Array.isArray(run.reasons) && run.reasons.length
        ? " · " + run.reasons.join("; ")
        : "";

    if (run.state === "READY_TO_RUN") {
      return run.can_run
        ? "Program accepted · Ready to Run"
        : "Program accepted · Waiting for experiment availability";
    }

    if (run.state === "REJECTED") {
      return "Program rejected" + reasons;
    }

    return labelStage(run.state) + reasons;
  }


  async function loadRun(runId) {
    const value = await request("/api/runs/" + runId);

    selectedRun = value;

    status.textContent = describeRun(value);

    sync();

    return value;
  }


  async function refreshRuns() {
    const value = await request("/api/runs");

    runs.replaceChildren();

    if (!value.runs || !value.runs.length) {
      const empty = document.createElement("p");

      empty.className = "hint";
      empty.textContent = "No custom programs recorded in this workstation session.";

      runs.append(empty);

      return;
    }

    value.runs.forEach(run => {
      const row = document.createElement("div");

      row.className = "run-row";

      const select = document.createElement("button");

      select.type = "button";
      select.className = "secondary-button compact-button";
      select.textContent = "Select";

      select.addEventListener("click", () => {
        void perform(async () => {
          const selected = await loadRun(run.run_id || run.id);

          result.textContent =
            "Selected program " +
            selected.run_id +
            " · " +
            describeRun(selected);
        });
      });

      const text = document.createElement("span");

      text.textContent =
        (run.run_id || run.id) +
        " · " +
        labelStage(run.state);

      row.append(select, text);

      runs.append(row);
    });
  }


  async function perform(fn) {
    if (busy) return;

    busy = true;
    sync();

    try {
      await fn();
    } catch (error) {
      showError(error);
    } finally {
      busy = false;
      sync();
    }
  }


  function sourceChanged() {
    checkedSource = null;

    if (selectedRun && selectedRun.can_run === true) {
      selectedRun = {
        ...selectedRun,
        can_run: false
      };
    }

    status.textContent =
      "Program changed · Check required";

    result.textContent =
      "The editor has changed. Nothing new has been sent to the ESP32-CAM. " +
      "Check this program before running it.";

    sync();
  }


  source.addEventListener("input", sourceChanged);


  templateLoadButton.addEventListener("click", () => {
    const template = templates[templateSelect.value];

    if (!template) return;

    source.value = template;
    sourceChanged();
    source.focus();
  });


  submitButton.addEventListener("click", () => {
    void perform(async () => {
      selectedRun = null;
      checkedSource = null;
      const submittedSource = source.value;
      sync();

      const response = await fetch("/api/submissions", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          source: submittedSource,
          experiment: "led-status-v1"
        })
      });

      let value;

      try {
        value = await response.json();
      } catch {
        value = {error: "INVALID_GATEWAY_RESPONSE"};
      }

      if (!response.ok) {
        if (value.run_id) {
          try {
            selectedRun = await request("/api/runs/" + value.run_id);

            status.textContent = describeRun(selectedRun);
          } catch {
            selectedRun = null;
          }
        }

        const reasons =
          Array.isArray(value.reasons) && value.reasons.length
            ? value.reasons.join("; ")
            : value.error || "Program rejected.";

        result.textContent =
          "Program not accepted.\n" + reasons;

        await refreshRuns();

        return;
      }

      selectedRun = await request("/api/runs/" + value.run_id);
      if (source.value !== submittedSource) {
        sourceChanged();
        return;
      }
      checkedSource = submittedSource;

      status.textContent = describeRun(selectedRun);

      result.textContent =
        "Program accepted.\n" +
        "Run ID: " +
        value.run_id +
        "\nNothing has been sent to the ESP32-CAM yet.";

      await refreshRuns();
    });
  });


  runButton.addEventListener("click", () => {
    void perform(async () => {
      if (
        !selectedRun ||
        selectedRun.can_run !== true ||
        checkedSource === null ||
        source.value !== checkedSource
      ) {
        throw new Error(
          "Check the current program and confirm that it is Ready to Run first."
        );
      }

      const runId = selectedRun.run_id;

      /*
       * Remove local execution eligibility before dispatch.
       * If the reply is lost, the browser must not offer a blind retry.
       */
      selectedRun = {
        ...selectedRun,
        can_run: false
      };

      sync();

      // A recovery or STOP in another session can invalidate a checked program.
      // Refresh authority before dispatch; the execution endpoint still enforces it.
      const currentRun = await request("/api/runs/" + runId);
      if (currentRun.state !== "READY_TO_RUN" || currentRun.can_run !== true) {
        selectedRun = {...currentRun, can_run: false};
        checkedSource = null;
        status.textContent = describeRun(currentRun);
        throw new Error("This program is no longer Ready to Run. Select Check to prepare a fresh run.");
      }

      try {
        await request(
          "/api/runs/" + runId + "/execute",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: "{}"
          }
        );
      } catch (error) {
        selectedRun = null;

        result.textContent =
          "The execution result could not be confirmed. " +
          "Do not retry the program blindly; ask the instructor to review the run.";

        throw error;
      }

      selectedRun = await request("/api/runs/" + runId);

      status.textContent = describeRun(selectedRun);

      result.textContent =
        "Program sent to the ESP32-CAM.\n" +
        "The Gateway recorded the device response for this run.";

      startCompletionCheck(runId);
    });
  });


  // Status observations never resend an execution. Each new execution needs Check.
  function stopCompletionCheck() {
    observingRun = null;
    if (completionTimer !== null) clearTimeout(completionTimer);
    completionTimer = null;
    sync();
  }

  function incompleteCompletion(message) {
    stopCompletionCheck();
    status.textContent = "Completion not confirmed · Check required before another run";
    result.textContent = message + " No execution was retried. Ask the instructor to review an uncertain device state.";
  }

  function startCompletionCheck(runId) {
    stopCompletionCheck();
    observingRun = runId;
    completionAttempts = 0;
    completionDeadline = Date.now() + 15000;
    checkedSource = null;
    status.textContent = "Program sent · Checking completion";
    completionTimer = setTimeout(() => observeCompletion(runId), 1000);
    sync();
  }

  async function observeCompletion(runId) {
    if (observingRun !== runId) return;
    if (completionAttempts >= 12 || Date.now() >= completionDeadline) {
      incompleteCompletion("A completed LED-OFF report was not received within the observation window.");
      return;
    }
    completionAttempts += 1;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const value = await request("/api/runs/" + runId + "/status", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", signal: controller.signal
      });
      if (observingRun !== runId) return;
      const report = value.reported || {};
      if (value.current_device_run !== true || report.run_id !== runId) {
        incompleteCompletion("The ESP32-CAM is reporting a different run.");
        return;
      }
      if (report.led_reported === 0 && ["COMPLETE", "STOPPED", "IDLE"].includes(report.state)) {
        selectedRun = {...selectedRun, state: value.state || "DEVICE_REPORTED_COMPLETE", can_run: false};
        stopCompletionCheck();
        status.textContent = "Device reported complete · Check required for another run";
        result.textContent = "ESP32-CAM reported LED OFF · " + labelStage(report.state) +
          ". This device report is not a physical observation. Select Check to prepare another run.";
      } else if (report.state === "RUNNING") {
        status.textContent = "Device reports running · Checking completion";
        completionTimer = setTimeout(() => observeCompletion(runId), 1000);
      } else {
        incompleteCompletion("The device report did not confirm the expected completed LED-OFF state.");
      }
    } catch (error) {
      if (observingRun === runId) incompleteCompletion("A fresh device report could not be obtained.");
    } finally {
      clearTimeout(timeout);
    }
  }

  window.addEventListener("pagehide", stopCompletionCheck);
  window.addEventListener("sentinel-led-stopped", () => {
    stopCompletionCheck();
    checkedSource = null;
    if (selectedRun) selectedRun = {...selectedRun, can_run: false};
    status.textContent = "LED OFF reported · Check required";
    result.textContent = "The ESP32-CAM reported LED OFF. Check the current program before another run.";
    sync();
  });

  checkButton.addEventListener("click", () => {
    void perform(async () => {
      if (!selectedRun) {
        throw new Error("Select a program first.");
      }

      const value = await request(
        "/api/runs/" + selectedRun.run_id + "/status",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: "{}"
        }
      );

      const report = value.reported || {};

      const led =
        report.led_reported === 1
          ? "ON"
          : report.led_reported === 0
            ? "OFF"
            : "UNKNOWN";

      result.textContent =
        "Device report received.\n" +
        "Run correlation: " +
        (value.current_device_run ? "Current run" : "Different run") +
        "\nDevice state: " +
        labelStage(report.state) +
        "\nLED reported: " +
        led;

      selectedRun = await request(
        "/api/runs/" + selectedRun.run_id
      );

      status.textContent = describeRun(selectedRun);
    });
  });


  refreshButton.addEventListener("click", () => {
    void perform(refreshRuns);
  });


  sync();

  void perform(refreshRuns);
})();
