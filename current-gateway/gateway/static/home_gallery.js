(() => {
  const gallery = document.querySelector("[data-slideshow]");
  if (!gallery) return;

  const strip = gallery.querySelector(".home-photo-grid");
  if (!strip) return;

  const BASE = "/static/device-icons/";

  const files = [
    {
      filename: "public-rover.svg",
      alt: "Autonomous four-wheel cyber-physical systems rover"
    },
    {
      filename: "public-gateway.svg",
      alt: "Raspberry Pi gateway computing board"
    },
    {
      filename: "public-camera.svg",
      alt: "ESP32 camera development board"
    },
    {
      filename: "public-mcu.svg",
      alt: "ESP32 wireless microcontroller development board"
    },
    {
      filename: "public-sensor.svg",
      alt: "Ultrasonic distance sensor module"
    },
    {
      filename: "public-chassis.svg",
      alt: "Two-wheel robotic motor and chassis platform"
    },
    {
      filename: "public-breadboard.svg",
      alt: "Electronics breadboard and prototyping circuit"
    },
    {
      filename: "public-printer.svg",
      alt: "Desktop additive-manufacturing 3D printer"
    },
    {
      filename: "public-display.svg",
      alt: "Laboratory display screen"
    },
    {
      filename: "public-switch.svg",
      alt: "Ethernet network switch"
    },
    {
      filename: "public-handheld.svg",
      alt: "Handheld embedded security testing device"
    }
  ];

  /*
   * Remove old slideshow arrows if they still exist.
   */
  gallery
    .querySelectorAll(
      "[data-gallery-previous], [data-gallery-next]"
    )
    .forEach(control => control.remove());

  /*
   * Build one finite 1–15 photo strip.
   */
  strip.replaceChildren();

  files.forEach((item, index) => {
    const figure = document.createElement("figure");
    figure.className = "panorama-photo";

    const image = document.createElement("img");

    image.src = BASE + item.filename;
    image.alt = item.alt;

    image.loading =
      index < 3 ? "eager" : "lazy";

    image.decoding = "async";

    figure.appendChild(image);
    strip.appendChild(figure);
  });

  let direction = 1;
  let lastFrame = performance.now();
  let lastInteraction = 0;
  let edgePauseUntil = 0;

  let dragging = false;
  let dragStartX = 0;
  let dragStartScroll = 0;

  const AUTO_SPEED = 0.030;
  const USER_PAUSE_MS = 2200;
  const EDGE_PAUSE_MS = 1200;

  function maxScroll() {
    return Math.max(
      0,
      strip.scrollWidth - strip.clientWidth
    );
  }

  function markInteraction() {
    lastInteraction = performance.now();
  }

  /*
   * Mouse wheel / trackpad.
   *
   * Horizontal trackpad motion uses deltaX.
   * Vertical mouse-wheel motion is converted to horizontal.
   */
  gallery.addEventListener(
    "wheel",
    event => {
      const horizontal =
        Math.abs(event.deltaX) >
        Math.abs(event.deltaY)
          ? event.deltaX
          : event.deltaY;

      if (!Number.isFinite(horizontal)) return;

      event.preventDefault();

      markInteraction();

      const maximum = maxScroll();

      strip.scrollLeft = Math.max(
        0,
        Math.min(
          maximum,
          strip.scrollLeft + horizontal * 1.15
        )
      );
    },
    { passive: false }
  );

  /*
   * Mouse drag.
   */
  strip.addEventListener(
    "pointerdown",
    event => {
      if (event.pointerType !== "mouse") return;

      dragging = true;

      dragStartX = event.clientX;
      dragStartScroll = strip.scrollLeft;

      strip.classList.add("is-dragging");

      markInteraction();

      strip.setPointerCapture(event.pointerId);
    }
  );

  strip.addEventListener(
    "pointermove",
    event => {
      if (!dragging) return;

      const distance =
        event.clientX - dragStartX;

      const maximum = maxScroll();

      strip.scrollLeft = Math.max(
        0,
        Math.min(
          maximum,
          dragStartScroll - distance
        )
      );

      markInteraction();
    }
  );

  function endDrag(event) {
    if (!dragging) return;

    dragging = false;

    strip.classList.remove("is-dragging");

    markInteraction();

    if (
      strip.hasPointerCapture &&
      strip.hasPointerCapture(event.pointerId)
    ) {
      strip.releasePointerCapture(event.pointerId);
    }
  }

  strip.addEventListener("pointerup", endDrag);
  strip.addEventListener("pointercancel", endDrag);

  /*
   * Continuous bounded automatic movement.
   *
   * It reverses when it reaches an edge rather than wrapping.
   */
  function animate(now) {
    const elapsed = Math.min(
      now - lastFrame,
      50
    );

    lastFrame = now;

    const maximum = maxScroll();

    const userIdle =
      now - lastInteraction >
      USER_PAUSE_MS;

    const edgePauseFinished =
      now >= edgePauseUntil;

    if (
      maximum > 0 &&
      !document.hidden &&
      !dragging &&
      userIdle &&
      edgePauseFinished
    ) {
      strip.scrollLeft +=
        elapsed *
        AUTO_SPEED *
        direction;

      if (strip.scrollLeft >= maximum) {
        strip.scrollLeft = maximum;
        direction = -1;
        edgePauseUntil =
          now + EDGE_PAUSE_MS;
      }

      if (strip.scrollLeft <= 0) {
        strip.scrollLeft = 0;
        direction = 1;
        edgePauseUntil =
          now + EDGE_PAUSE_MS;
      }
    }

    requestAnimationFrame(animate);
  }

  /*
   * Ensure a clean starting position after reload/restart.
   */
  strip.scrollLeft = 0;

  requestAnimationFrame(animate);
})();
