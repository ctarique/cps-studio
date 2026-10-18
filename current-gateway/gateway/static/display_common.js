"use strict";

(() => {
  const trackIds = new Set(["straight", "wide-straight", "curve", "wide-curve", "challenge", "wide-challenge", "circle", "wide-circle", "oval", "elliptical", "infinity", "wide-infinity"]);
  function exactKeys(value, keys) {
    return value && typeof value === "object" && !Array.isArray(value)
      && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
  }
  function validateStatus(value) {
    if (!exactKeys(value, ["mode", "experiment", "track"])) throw new Error("Invalid display response.");
    const {mode, experiment, track} = value;
    const valid = (["SETUP_REQUIRED", "IDLE", "SELECT_EXPERIMENT", "RECOVERY"].includes(mode) && experiment === null && track === null)
      || (["LED_SETUP", "LED_READY", "LED_RUNNING", "LED_COMPLETE"].includes(mode) && experiment === "led" && track === null)
      || (mode === "AUTONOMOUS_CAR_SETUP" && experiment === "autonomous-car" && track === null)
      || (mode === "TRACK_ACTIVE" && experiment === "autonomous-car" && trackIds.has(track))
      || (mode === "EXPERIMENT_COMPLETE" && experiment === "autonomous-car" && track === null);
    if (!valid) throw new Error("Invalid display state.");
    return {mode, experiment, track};
  }
  function validateCatalog(value) {
    if (!exactKeys(value, ["tracks"]) || !Array.isArray(value.tracks) || value.tracks.length !== trackIds.size)
      throw new Error("Invalid approved track catalog.");
    const seen = new Set();
    const tracks = value.tracks.map(track => {
      if (!exactKeys(track, ["id", "label"]) || !trackIds.has(track.id) || seen.has(track.id)
        || typeof track.label !== "string" || !track.label.trim() || track.label.length > 80)
        throw new Error("Invalid approved track identifier.");
      seen.add(track.id);
      return {id: track.id, label: track.label};
    });
    return tracks;
  }
  async function readJson(path, options = {}) {
    const controller = new AbortController();
    let timeout;
    const request = (async () => {
      const response = await fetch(path, {cache: "no-store", credentials: "omit", ...options, signal: controller.signal});
      const value = await response.json();
      if (!response.ok) {
        const error = new Error(typeof value.error === "string" ? value.error : "Display request failed.");
        error.status = response.status;
        throw error;
      }
      return value;
    })();
    const deadline = new Promise((_, reject) => {
      timeout = setTimeout(() => {
        controller.abort();
        reject(new Error("Lab Display request timed out. Refresh its status before trying again."));
      }, 3000);
    });
    try { return await Promise.race([request, deadline]); }
    finally { clearTimeout(timeout); }
  }
  window.SentinelDisplay = Object.freeze({validateStatus, validateCatalog, readJson});
})();
