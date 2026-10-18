"use strict";

(() => {
  const $ = id =>
    document.getElementById(id);

  const api =
    window.SentinelDisplay;

  const tracks = [
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

  let currentView = "lab";
  let polling = false;
  let stopped = false;
  let twinAllowed = false;
  let accessPolling = false;
  // Preserve a direct Twin link until the first verified permission response.
  let pendingInitialTwin = requestedView() === "twin";


  function requestedView() {
    const params =
      new URLSearchParams(
        window.location.search
      );

    return params.get("view") === "twin"
      ? "twin"
      : "lab";
  }


  function setView(view, updateUrl = false) {
    currentView =
      view === "twin" && twinAllowed
        ? "twin"
        : "lab";

    document.body.dataset.viewMode =
      currentView;

    $("view-lab").setAttribute(
      "aria-pressed",
      String(currentView === "lab")
    );

    $("view-twin").setAttribute(
      "aria-pressed",
      String(currentView === "twin")
    );

    if (updateUrl) {
      const url =
        new URL(window.location.href);

      if (currentView === "twin") {
        url.searchParams.set(
          "view",
          "twin"
        );
      } else {
        url.searchParams.delete(
          "view"
        );
      }

      window.history.replaceState(
        null,
        "",
        url
      );
    }

    if (currentView === "twin") {
      refresh();
    }
  }


  /*
   * This is a presentation gate, not OS or device authorization.
   * Trust only a successful, current Gateway health response.
   */
  function updateTwinPermission(allowed) {
    twinAllowed = allowed === true;

    const button = $("view-twin");
    button.disabled = !twinAllowed;
    button.setAttribute(
      "aria-disabled",
      String(!twinAllowed)
    );
    button.title = twinAllowed
      ? "Show Digital Twin"
      : "Instructor must unlock Gateway";
    button.style.opacity = twinAllowed ? "" : "0.45";

    if (!twinAllowed && currentView === "twin") {
      setView("lab", true);
    }
  }


  async function refreshTwinPermission() {
    if (stopped || accessPolling) {
      return;
    }
    accessPolling = true;

    try {
      const [health, displayStatus] = await Promise.all([
        api.readJson("/api/health"),
        api.readJson("/api/display/status")
      ]);
      const status = api.validateStatus(displayStatus);
      if (!health || typeof health !== "object" || typeof health.locked !== "boolean") {
        throw new Error("Gateway permission state unavailable.");
      }

      updateTwinPermission(
        health !== null &&
        typeof health === "object" &&
        health.locked === false &&
        status.mode !== "SETUP_REQUIRED" &&
        status.mode !== "RECOVERY"
      );
      if (pendingInitialTwin) {
        pendingInitialTwin = false;
        setView(twinAllowed ? "twin" : "lab", true);
      }
    } catch {
      updateTwinPermission(false);
    } finally {
      accessPolling = false;
    }
  }


  function setSelectedExperiment(experiment) {
    const led =
      $("twin-card-led");

    const car =
      $("twin-card-car");

    led.classList.remove(
      "is-active",
      "is-inactive"
    );

    car.classList.remove(
      "is-active",
      "is-inactive"
    );

    if (experiment === "led") {
      led.classList.add("is-active");
      car.classList.add("is-inactive");
    } else if (experiment === "autonomous-car") {
      car.classList.add("is-active");
      led.classList.add("is-inactive");
    }
  }


  function rssiStrength(rssi) {
    if (
      !Number.isInteger(rssi) ||
      rssi < -127 ||
      rssi > 0
    ) {
      return "unknown";
    }

    if (rssi >= -60) {
      return "strong";
    }

    if (rssi >= -75) {
      return "medium";
    }

    return "weak";
  }


  function updateWifi(
    iconId,
    valueId,
    rssi,
    available,
    unavailableText
  ) {
    const icon = $(iconId);
    const label = $(valueId);

    icon.dataset.strength = "unknown";

    icon.setAttribute(
      "aria-label",
      "Wi-Fi RSSI unavailable"
    );

    label.textContent =
      unavailableText;

    if (
      available !== true ||
      !Number.isInteger(rssi) ||
      rssi < -127 ||
      rssi > 0
    ) {
      return;
    }

    const strength =
      rssiStrength(rssi);

    icon.dataset.strength =
      strength;

    icon.setAttribute(
      "aria-label",
      `Wi-Fi RSSI ${rssi} dBm, ${strength} signal`
    );

    label.textContent =
      `${rssi} dBm`;
  }


  function updateConnectionIndicator(
    id,
    connected
  ) {
    const indicator = $(id);

    if (!indicator) return;

    indicator.classList.remove(
      "is-connected",
      "is-disconnected",
      "is-unknown"
    );

    if (connected === true) {
      indicator.classList.add(
        "is-connected"
      );

      indicator.title =
        "Device connected";
      return;
    }

    if (connected === false) {
      indicator.classList.add(
        "is-disconnected"
      );

      indicator.title =
        "Device disconnected";
      return;
    }

    indicator.classList.add(
      "is-unknown"
    );

    indicator.title =
      "Checking device connection";
  }


  function updateCam(value) {
    const bulb =
      $("twin-cam-led");

    /*
     * CAM-01 does not yet report authenticated RSSI.
     * Do not estimate or infer signal strength elsewhere.
     */
    updateWifi(
      "twin-wifi-led",
      "twin-wifi-led-value",
      null,
      false,
      "RSSI unavailable"
    );

    /*
     * Never infer physical state from workflow state.
     * Only a fresh authenticated device report may
     * illuminate the Digital Twin bulb.
     */
    bulb.classList.remove("is-on");

    bulb.setAttribute(
      "aria-label",
      "ESP32-CAM LED state unavailable"
    );

    if (
      !value ||
      typeof value !== "object" ||
      !value.cam ||
      typeof value.cam !== "object"
    ) {
      updateConnectionIndicator(
        "twin-connection-led",
        false
      );
      return;
    }

    const cam = value.cam;

    const camConnected =
      cam.fresh === true &&
      cam.authenticated === true &&
      cam.reachable === true;

    updateConnectionIndicator(
      "twin-connection-led",
      camConnected
    );

    if (
      cam.fresh !== true ||
      cam.authenticated !== true ||
      (cam.led_reported !== 0 &&
       cam.led_reported !== 1)
    ) {
      return;
    }

    if (cam.led_reported === 1) {
      bulb.classList.add("is-on");

      bulb.setAttribute(
        "aria-label",
        "ESP32-CAM reports LED on"
      );
    } else {
      bulb.setAttribute(
        "aria-label",
        "ESP32-CAM reports LED off"
      );
    }
  }


  function trackLabel(track) {
    const labels = {
      "straight": "Straight",
      "wide-straight": "Straight Wide",
      "curve": "Curve",
      "wide-curve": "Curve Wide",
      "challenge": "Challenge",
      "wide-challenge": "Challenge Wide",
      "circle": "Circle",
      "wide-circle": "Circle Wide",
      "oval": "Oval",
      "elliptical": "Oval Wide",
      "infinity": "Infinity",
      "wide-infinity": "Infinity Wide"
    };

    return labels[track] || "Not selected";
  }


  function updateTrack(track) {
    const stage =
      $("twin-track-stage");

    /*
     * With no selected track, the Digital Twin
     * shows the neutral checkered racing surface.
     */
    const valid =
      tracks.includes(track)
        ? track
        : null;

    stage.dataset.track =
      valid || "none";

    $("twin-track-none").hidden =
      Boolean(valid);

    tracks.forEach(id => {
      $("twin-track-" + id).hidden =
        id !== valid;
    });
  }



  // Presentation only: does not extend physical execution.
  const runIndicatorHoldMs = 2000;
  const runIndicatorUntil = {
    motorA: 0,
    motorB: 0,
    camera: 0
  };

  function updateCarTelemetry(car, authenticated) {
    const ldr32 =
      $("twin-car-ldr32");

    const ldr33 =
      $("twin-car-ldr33");

    const motorA =
      $("twin-car-motor-a");

    const motorB =
      $("twin-car-motor-b");

    const camera =
      $("twin-car-camera");

    const motorAState =
      motorA.querySelector(
        ".twin-car-use-state"
      );

    const motorBState =
      motorB.querySelector(
        ".twin-car-use-state"
      );

    const cameraState =
      camera.querySelector(
        ".twin-car-use-state"
      );

    const vehicle =
      $("twin-car-image");

    const ldr32Sensor =
      ldr32.closest(
        ".twin-car-sensor"
      );

    const ldr33Sensor =
      ldr33.closest(
        ".twin-car-sensor"
      );

    ldr32.textContent = "—";
    ldr33.textContent = "—";

    ldr32Sensor.dataset.level =
      "unknown";

    ldr33Sensor.dataset.level =
      "unknown";

    motorA.classList.remove(
      "is-active"
    );

    motorB.classList.remove(
      "is-active"
    );

    vehicle.classList.remove(
      "motor-a-active",
      "motor-b-active",
      "camera-active"
    );

    camera.classList.remove(
      "is-active"
    );

    /*
     * Camera activity is Gateway action state from a
     * successfully verified authenticated JPEG. It is
     * intentionally independent from camera_ready.
     */
    const cameraActive =
      Boolean(
        car &&
        car.camera_active === true
      );

    const now = performance.now();
    const valid = Boolean(authenticated && car);

    if (!valid) {
      runIndicatorUntil.motorA = 0;
      runIndicatorUntil.motorB = 0;
      runIndicatorUntil.camera = 0;
    } else {
      if (car.motor_a_active === true) {
        runIndicatorUntil.motorA = now + runIndicatorHoldMs;
      }
      if (car.motor_b_active === true) {
        runIndicatorUntil.motorB = now + runIndicatorHoldMs;
      }
      if (cameraActive) {
        runIndicatorUntil.camera = now + runIndicatorHoldMs;
      }
    }

    const motorAShown = valid && now < runIndicatorUntil.motorA;
    const motorBShown = valid && now < runIndicatorUntil.motorB;
    const cameraShown = valid && now < runIndicatorUntil.camera;

    camera.classList.toggle(
      "is-active",
      cameraShown
    );

    vehicle.classList.toggle(
      "camera-active",
      cameraActive
    );

    if (motorAState) {
      motorAState.textContent =
        authenticated && car
          ? (
              motorAShown
                ? "RUN"
                : "IDLE"
            )
          : "—";
    }

    if (motorBState) {
      motorBState.textContent =
        authenticated && car
          ? (
              motorBShown
                ? "RUN"
                : "IDLE"
            )
          : "—";
    }

    if (cameraState) {
      cameraState.textContent =
        authenticated && car
          ? (
              cameraShown
                ? "RUN"
                : "IDLE"
            )
          : "—";
    }

    if (!authenticated || !car) {
      return;
    }

    if (
      Number.isInteger(car.ldr32) &&
      car.ldr32 >= 0 &&
      car.ldr32 <= 4095
    ) {
      ldr32.textContent =
        String(car.ldr32);

      ldr32Sensor.dataset.level =
        car.ldr32 >= 3072
          ? "high"
          : car.ldr32 >= 1536
            ? "medium"
            : car.ldr32 > 0
              ? "low"
              : "dark";
    }

    if (
      Number.isInteger(car.ldr33) &&
      car.ldr33 >= 0 &&
      car.ldr33 <= 4095
    ) {
      ldr33.textContent =
        String(car.ldr33);

      ldr33Sensor.dataset.level =
        car.ldr33 >= 3072
          ? "high"
          : car.ldr33 >= 1536
            ? "medium"
            : car.ldr33 > 0
              ? "low"
              : "dark";
    }

    motorA.classList.toggle(
      "is-active",
      motorAShown
    );

    motorB.classList.toggle(
      "is-active",
      motorBShown
    );

    vehicle.classList.toggle(
      "motor-a-active",
      car.motor_a_active === true
    );

    vehicle.classList.toggle(
      "motor-b-active",
      car.motor_b_active === true
    );

    /*
     * Camera readiness remains available as authenticated
     * device telemetry, but the graphical camera indicator
     * lights only for an actual verified snapshot action.
     */
  }


  function updateCar(value, devices) {
    const active =
      value.experiment ===
      "autonomous-car";

    const track =
      active &&
      value.mode === "TRACK_ACTIVE"
        ? value.track
        : null;

    updateTrack(track);

    const car =
      devices &&
      typeof devices === "object" &&
      devices.car &&
      typeof devices.car === "object"
        ? devices.car
        : null;

    const authenticated =
      car &&
      car.fresh === true &&
      car.authenticated === true;

    const connected =
      Boolean(
        authenticated &&
        car.reachable === true
      );

    updateConnectionIndicator(
      "twin-connection-car",
      connected
    );

    updateWifi(
      "twin-wifi-car",
      "twin-wifi-car-value",
      authenticated
        ? car.rssi_dbm
        : null,
      authenticated,
      "RSSI —"
    );

    window.SentinelStatusRtt.update($("twin-car-rtt"), car);

    updateCarTelemetry(
      car,
      authenticated
    );
  }


  function present(value, devices) {
    setSelectedExperiment(
      value.experiment
    );

    updateCam(devices);
    updateCar(
      value,
      devices
    );
  }


  async function refresh() {
    if (
      stopped ||
      polling ||
      currentView !== "twin"
    ) {
      return;
    }

    polling = true;

    try {
      const statusRequest =
        api.readJson(
          "/api/display/status"
        );

      /*
       * Device telemetry is optional supporting data.
       * Failure must not break experiment/track display.
       */
      const deviceRequest =
        api.readJson(
          "/api/display/devices"
        ).catch(() => null);

      const [
        statusValue,
        devices
      ] = await Promise.all([
        statusRequest,
        deviceRequest
      ]);

      const value =
        api.validateStatus(
          statusValue
        );

      if (!stopped && twinAllowed && currentView === "twin") {
        present(
          value,
          devices
        );
      }

    } catch {
      if (!stopped) {
        setSelectedExperiment(null);

        updateConnectionIndicator(
          "twin-connection-led",
          false
        );

        updateConnectionIndicator(
          "twin-connection-car",
          false
        );

        $("twin-cam-led").classList.remove(
          "is-on"
        );

        updateTrack(null);

        updateWifi(
          "twin-wifi-car",
          "twin-wifi-car-value",
          null,
          false,
          "RSSI —"
        );

        window.SentinelStatusRtt.update($("twin-car-rtt"), null);

        updateCarTelemetry(
          null,
          false
        );

        updateWifi(
          "twin-wifi-led",
          "twin-wifi-led-value",
          null,
          false,
          "RSSI unavailable"
        );
      }

    } finally {
      polling = false;
    }
  }


  $("view-lab").addEventListener(
    "click",
    () => { pendingInitialTwin = false; setView("lab", true); }
  );

  $("view-twin").addEventListener(
    "click",
    () => setView("twin", true)
  );


  window.addEventListener(
    "pagehide",
    () => {
      stopped = true;
    }
  );


  setInterval(
    refresh,
    1000
  );

  setInterval(
    refreshTwinPermission,
    1000
  );

  updateTwinPermission(false);
  setView("lab", false);
  refreshTwinPermission();
})();
