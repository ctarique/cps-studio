"use strict";

(() => {

  const api =
    window.SentinelDisplay;

  if (!api) return;


  async function selectExperimentScreen() {

    try {

      /*
       * Do not request a presentation change while
       * the real Gateway is locked.
       */
      const healthResponse =
        await fetch(
          "/api/health",
          {
            credentials: "same-origin",
            cache: "no-store"
          }
        );

      if (!healthResponse.ok) {
        return;
      }

      const health =
        await healthResponse.json();

      if (health.locked) {
        return;
      }


      /*
       * Never replace an actively running LED
       * presentation merely because somebody
       * navigated back to the experiment catalog.
       */
      const current =
        api.validateStatus(
          await api.readJson(
            "/api/display/status"
          )
        );

      if (
        current.mode === "LED_RUNNING" ||
        current.mode === "SETUP_REQUIRED" ||
        current.mode === "RECOVERY"
      ) {
        return;
      }


      await api.readJson(
        "/api/display/select-experiment",
        {
          method: "POST",

          credentials: "same-origin",

          headers: {
            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify({})
        }
      );

    } catch {

      /*
       * Lab Display presentation is supporting UI.
       * Failure here does not grant authority and
       * must not interfere with portal navigation.
       */

    }

  }


  void selectExperimentScreen();

})();
