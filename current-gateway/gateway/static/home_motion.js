(() => {
  const body = document.body;

  if (
    !body.classList.contains("home-page") ||
    !body.classList.contains("scps-doc-ui")
  ) {
    return;
  }

  const sections = Array.from(
    document.querySelectorAll(
      ".home-gallery-section, .home-content-section"
    )
  );

  const reducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  if (reducedMotion) {
    sections.forEach(section => {
      section.classList.add("is-visible");
    });

    return;
  }

  body.classList.add("motion-ready");

  if (!("IntersectionObserver" in window)) {
    sections.forEach(section => {
      section.classList.add("is-visible");
    });

    return;
  }

  const observer =
    new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) {
            return;
          }

          entry.target.classList.add(
            "is-visible"
          );

          observer.unobserve(
            entry.target
          );
        });
      },
      {
        threshold: .10,
        rootMargin:
          "0px 0px -6% 0px"
      }
    );

  sections.forEach(section => {
    observer.observe(section);
  });
})();
