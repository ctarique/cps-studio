"use strict";

(() => {
  const camStatus =
    document.getElementById("led-cam-status");

  const guidedLedState =
    document.getElementById("guided-led-state");

  if (!camStatus || !guidedLedState) return;

  let stopped = false;

  function setConnection(state) {
    camStatus.classList.remove(
      "led-live-online",
      "led-live-unavailable",
      "led-live-unknown"
    );

    if (state === "online") {
      camStatus.textContent = "";
      camStatus.setAttribute(
        "aria-label",
        "ESP32-CAM status: connected"
      );
      camStatus.title = "Connected";
      camStatus.classList.add(
        "led-live-online"
      );
      return;
    }

    if (state === "unavailable") {
      camStatus.textContent = "";
      camStatus.setAttribute(
        "aria-label",
        "ESP32-CAM status: unavailable"
      );
      camStatus.title = "Unavailable";
      camStatus.classList.add(
        "led-live-unavailable"
      );
      return;
    }

    camStatus.textContent = "";
    camStatus.setAttribute(
      "aria-label",
      "ESP32-CAM status: checking"
    );
    camStatus.title = "Checking";
    camStatus.classList.add(
      "led-live-unknown"
    );
  }

  function setLed(value, available) {
    const targets =
      [guidedLedState];

    targets.forEach(element => {
      element.classList.remove(
        "led-state-on",
        "led-state-off",
        "led-state-unknown"
      );
    });

    if (!available) {
      targets.forEach(element => {
        element.textContent = "LED —";
        element.classList.add(
          "led-state-unknown"
        );
      });
      return;
    }

    if (value === 1) {
      targets.forEach(element => {
        element.textContent = "LED ON";
        element.classList.add(
          "led-state-on"
        );
      });
      return;
    }

    if (value === 0) {
      targets.forEach(element => {
        element.textContent = "LED OFF";
        element.classList.add(
          "led-state-off"
        );
      });
      return;
    }

    targets.forEach(element => {
      element.textContent = "LED —";
      element.classList.add(
        "led-state-unknown"
      );
    });
  }

  async function refresh() {
    try {
      const response = await fetch(
        "/api/display/devices",
        {
          cache: "no-store",
          credentials: "same-origin"
        }
      );

      if (!response.ok) {
        throw new Error(
          "DEVICE_STATUS_UNAVAILABLE"
        );
      }

      const value = await response.json();
      const cam = value && value.cam;

      const connected =
        Boolean(
          cam &&
          cam.authenticated === true &&
          cam.fresh === true &&
          cam.reachable === true
        );

      if (!connected) {
        setConnection("unavailable");
        setLed(null, false);
        return;
      }

      setConnection("online");

      setLed(
        cam.led_reported,
        true
      );

    } catch {
      setConnection("unavailable");
      setLed(null, false);
    }
  }

  async function loop() {
    if (stopped) return;

    await refresh();

    if (!stopped) {
      window.setTimeout(
        loop,
        1000
      );
    }
  }

  window.addEventListener(
    "pagehide",
    () => {
      stopped = true;
    },
    {once: true}
  );

  void loop();
})();
