(() => {
  "use strict";

  let cloneSequence = 0;


  function rewriteReference(value, idMap) {

    if (!value) {
      return value;
    }

    let result = value;

    idMap.forEach(
      (newId, oldId) => {

        result = result.replaceAll(
          `url(#${oldId})`,
          `url(#${newId})`
        );

        if (result === `#${oldId}`) {
          result = `#${newId}`;
        }
      }
    );

    return result;
  }


  function makeIndependentSvg(source) {

    const clone =
      source.cloneNode(true);

    cloneSequence += 1;

    const prefix =
      `select-asset-${cloneSequence}-`;

    const idMap =
      new Map();


    clone
      .querySelectorAll("[id]")
      .forEach(node => {

        const oldId =
          node.id;

        const newId =
          prefix + oldId;

        idMap.set(
          oldId,
          newId
        );

        node.id =
          newId;
      });


    const referenceAttributes = [
      "fill",
      "stroke",
      "filter",
      "clip-path",
      "mask",
      "marker-start",
      "marker-mid",
      "marker-end",
      "href",
      "xlink:href",
      "style"
    ];


    clone
      .querySelectorAll("*")
      .forEach(node => {

        referenceAttributes.forEach(
          attribute => {

            if (
              !node.hasAttribute(attribute)
            ) {
              return;
            }

            node.setAttribute(
              attribute,
              rewriteReference(
                node.getAttribute(attribute),
                idMap
              )
            );
          }
        );
      });


    clone.removeAttribute("id");

    clone.classList.add(
      "select-experiment-asset-svg"
    );

    return clone;
  }


  function cloneVisual(
    sourceSelector,
    targetSelector
  ) {

    const source =
      document.querySelector(
        sourceSelector
      );

    const target =
      document.querySelector(
        targetSelector
      );

    if (
      !source ||
      !target ||
      target.dataset.visualReady === "true"
    ) {
      return;
    }

    target.replaceChildren(
      makeIndependentSvg(source)
    );

    target.dataset.visualReady =
      "true";
  }


  function init() {

    cloneVisual(
      "#twin-cam-led .twin-smart-bulb-svg",
      '[data-select-asset="cam"]'
    );

    cloneVisual(
      "#twin-car-image .twin-racecar-svg",
      '[data-select-asset="car"]'
    );
  }


  if (
    document.readyState === "loading"
  ) {

    document.addEventListener(
      "DOMContentLoaded",
      init,
      { once: true }
    );

  } else {

    init();
  }

})();
