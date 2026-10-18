"use strict";

/* Presentation only. The Gateway measures the authenticated CAR status request.
 * This helper performs no requests and never measures browser network latency. */
(() => {
  const expiryTimers = new WeakMap();
  const freshnessMs = 8000;

  function update(element, car) {
    if (!element) return;
    clearTimeout(expiryTimers.get(element));
    const value = car && car.status_rtt;
    let state = value && ["SUCCESS", "STALE", "FAILED", "UNAVAILABLE"].includes(value.state)
      ? value.state : "UNAVAILABLE";
    const age = value && Number.isInteger(value.age_ms) && value.age_ms >= 0
      ? value.age_ms : null;
    if (state === "SUCCESS" && age !== null && age > freshnessMs) state = "STALE";
    if (state === "SUCCESS" && !(car.authenticated === true && car.fresh === true &&
        Number.isFinite(value.ms) && value.ms >= 0 && age !== null)) state = "UNAVAILABLE";

    const labels = {STALE: "RTT stale", FAILED: "RTT failed", UNAVAILABLE: "RTT unavailable"};
    element.textContent = state === "SUCCESS" ? `RTT ${value.ms.toFixed(1)} ms` : labels[state];
    element.dataset.state = state;
    element.title = "Gateway to CAR-01 authenticated status request round trip; includes response validation. " +
      (state === "SUCCESS" ? "Fresh successful measurement." :
       state === "STALE" ? "The last successful measurement is stale." :
       state === "FAILED" ? "The latest CAR status request failed; no current timing is shown." :
       "No authenticated status timing is available.");
    element.hidden = false;
    if (state === "SUCCESS") {
      expiryTimers.set(element, setTimeout(() => update(element, {
        status_rtt: {state: "STALE", ms: null, age_ms: freshnessMs + 1}
      }), Math.max(1, freshnessMs - age + 1)));
    }
  }

  window.SentinelStatusRtt = Object.freeze({update});
})();
