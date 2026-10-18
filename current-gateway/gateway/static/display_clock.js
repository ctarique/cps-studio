(() => {
  "use strict";

  const dateNode =
    document.getElementById("display-date");

  const timeNode =
    document.getElementById("display-time");

  if (!dateNode || !timeNode) {
    return;
  }

  const dateFormatter =
    new Intl.DateTimeFormat(
      "en-US",
      {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric"
      }
    );

  const timeFormatter =
    new Intl.DateTimeFormat(
      "en-US",
      {
        hour: "numeric",
        minute: "2-digit"
      }
    );

  function updateClock() {
    const now = new Date();

    dateNode.textContent =
      dateFormatter.format(now);

    timeNode.textContent =
      timeFormatter.format(now);
  }

  updateClock();

  window.setInterval(
    updateClock,
    1000
  );
})();
