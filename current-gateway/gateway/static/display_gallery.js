(() => {
  "use strict";

  // Read-only synced slideshow. Presentation never authorizes device control.
  const gallery = document.getElementById("ready-gallery");
  const layers = [
    document.getElementById("ready-gallery-image-a"),
    document.getElementById("ready-gallery-image-b")
  ];
  if (!gallery || layers.some(layer => !layer)) return;

  const INTERVAL_MS = 200;
  const REFRESH_MS = 2500;
  const MAX_RTT_MS = 3000;
  const MAX_STALE_MS = 15000;
  const state = {
    snapshot: null,
    offsetMs: 0,
    lastRefreshMs: 0,
    index: -1,
    activeLayer: 0,
    generation: 0,
    stopped: false,
    pendingIndex: -1,
    retrying: false
  };

  const isIdle = () => document.body.dataset.visibleState === "idle";
  const serverNow = () => Date.now() + state.offsetMs;

  function validSnapshot(s) {
    return s && typeof s === "object" &&
      /^(fall|spring|winter)$/.test(s.season) &&
      /^[a-f0-9]{32}$/.test(s.revision) &&
      Number.isSafeInteger(s.started_at_ms) &&
      Number.isSafeInteger(s.server_now_ms) &&
      s.slide_duration_ms === 11200 && s.crossfade_ms === 1200 &&
      Array.isArray(s.slides) && s.slides.length >= 1 &&
      s.slides.length <= 50 &&
      s.slides.every((url, i) =>
        url === `/display/slides/${s.season}/slide-${String(i + 1).padStart(2, "0")}.jpg`
      );
  }

  function preload(url) {
    const img = new Image();
    img.src = url;
    return img;
  }

  function showImmediate(index) {
    const s = state.snapshot;
    if (!s || !isIdle()) return;
    state.generation++;
    state.pendingIndex = -1;
    state.index = index;
    state.activeLayer = 0;
    layers[0].src = s.slides[index];
    layers[0].classList.add("is-active");
    layers[1].classList.remove("is-active");
    preload(s.slides[(index + 1) % s.slides.length]);
  }

  function transitionTo(index) {
    const s = state.snapshot;
    if (!s || !isIdle() || state.pendingIndex === index) return;
    const generation = ++state.generation;
    state.pendingIndex = index;
    const incomingIndex = state.activeLayer ? 0 : 1;
    const incoming = layers[incomingIndex];
    const outgoing = layers[state.activeLayer];
    const source = s.slides[index];
    const reveal = () => {
      if (state.stopped || !isIdle() || generation !== state.generation ||
          state.snapshot !== s || state.pendingIndex !== index) return;
      incoming.classList.add("is-active");
      outgoing.classList.remove("is-active");
      state.activeLayer = incomingIndex;
      state.index = index;
      state.pendingIndex = -1;
      preload(s.slides[(index + 1) % s.slides.length]);
    };
    incoming.src = source;
    if (incoming.complete && incoming.naturalWidth > 0) {
      reveal();
    } else {
      incoming.addEventListener("load", reveal, { once: true });
      incoming.addEventListener("error", () => {
        if (generation === state.generation) state.pendingIndex = -1;
      }, { once: true });
    }
  }

  function tick() {
    if (state.stopped || !isIdle() || !state.snapshot) return;
    if (Date.now() - state.lastRefreshMs > MAX_STALE_MS) return;
    const s = state.snapshot;
    const elapsed = Math.max(0, serverNow() - s.started_at_ms);
    const index = Math.floor(elapsed / s.slide_duration_ms) % s.slides.length;
    if (state.index === -1) {
      showImmediate(index);
    } else if (index !== state.index) {
      const expected = (state.index + 1) % s.slides.length;
      // If the viewer missed several slides, join immediately, without
      // crossfading through obsolete photographs.
      if (index === expected) transitionTo(index);
      else showImmediate(index);
    }
  }

  async function refresh() {
    if (state.stopped || state.retrying) return;
    state.retrying = true;
    const started = Date.now();
    try {
      const response = await fetch("/api/display/slideshow", {
        cache: "no-store", credentials: "same-origin"
      });
      if (!response.ok) throw new Error("slideshow unavailable");
      const next = await response.json();
      const ended = Date.now();
      if (!validSnapshot(next) || ended - started > MAX_RTT_MS) return;
      if (state.stopped) return;
      const changed = !state.snapshot || state.snapshot.revision !== next.revision;
      state.offsetMs = next.server_now_ms - ((started + ended) / 2);
      state.lastRefreshMs = ended;
      state.snapshot = next;
      if (changed) {
        state.index = -1;
        state.generation++;
        state.pendingIndex = -1;
      }
      tick();
    } catch (_) {
      // Keep last displayed image; do not restart an unsynchronized timer.
    } finally {
      state.retrying = false;
    }
  }

  const observer = new MutationObserver(() => {
    if (!isIdle()) {
      state.generation++;
      state.pendingIndex = -1;
    } else {
      tick();
    }
  });
  observer.observe(document.body, {
    attributes: true, attributeFilter: ["data-visible-state"]
  });

  const tickTimer = setInterval(tick, INTERVAL_MS);
  const refreshTimer = setInterval(refresh, REFRESH_MS);
  refresh();

  window.addEventListener("pagehide", () => {
    state.stopped = true;
    state.generation++;
    clearInterval(tickTimer);
    clearInterval(refreshTimer);
    observer.disconnect();
  }, { once: true });
})();
