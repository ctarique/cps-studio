"use strict";

(() => {
  const links = document.querySelectorAll(
    "[data-home-display-reset]"
  );

  if (!links.length) return;

  links.forEach(link => {
    link.addEventListener("click", async event => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      event.preventDefault();

      const destination =
        link.getAttribute("href") || "/";

      try {
        await fetch("/api/display/home", {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json"
          },
          body: "{}"
        });
      } catch {
        /*
         * Portal navigation still proceeds if the
         * supporting display request cannot complete.
         */
      }

      window.location.assign(destination);
    });
  });
})();
