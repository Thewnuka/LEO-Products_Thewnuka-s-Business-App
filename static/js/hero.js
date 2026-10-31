/* LEO PRODUCTS — home page hero image cards (vanilla JavaScript).
   One card changes at a time, in the order given by data-order (0-based card
   positions, e.g. "0,2,1" = Box 1 → Box 3 → Box 2), every data-interval ms.
   Order and timing are set in apps/core/hero.py; the images come from the
   Owner's "Home page images" page. Without JavaScript the first image of
   each card simply stays in place. */
(function () {
  "use strict";

  function setup() {
    var wrap = document.querySelector("[data-hero-cards]");
    if (!wrap) return;
    var cards = Array.prototype.slice.call(wrap.querySelectorAll("[data-hero-card]"));
    var interval = parseInt(wrap.getAttribute("data-interval"), 10) || 3500;
    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Cards with only one image have nothing to change, so they are left out.
    var order = (wrap.getAttribute("data-order") || "").split(",")
      .map(function (n) { return parseInt(n, 10); })
      .filter(function (n) { return cards[n] && cards[n].querySelectorAll("img").length > 1; });
    if (!order.length || reduceMotion) return;

    var step = 0;
    var timer = null;

    function advance(card) {
      var imgs = card.querySelectorAll("img");
      var current = 0;
      for (var i = 0; i < imgs.length; i++) {
        if (imgs[i].classList.contains("is-active")) { current = i; break; }
      }
      var next = (current + 1) % imgs.length;
      imgs[current].classList.remove("is-active");
      imgs[current].setAttribute("aria-hidden", "true");
      imgs[next].classList.add("is-active");
      imgs[next].removeAttribute("aria-hidden");
    }

    function tick() {
      advance(cards[order[step]]);
      step = (step + 1) % order.length;
      timer = window.setTimeout(tick, interval);
    }

    function start() {
      if (timer === null) timer = window.setTimeout(tick, interval);
    }

    function stop() {
      window.clearTimeout(timer);
      timer = null;
    }

    // Pause while the tab is hidden, so the cards don't jump several steps on return.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else start();
    });
    window.addEventListener("pagehide", stop);
    window.addEventListener("pageshow", function (event) { if (event.persisted) start(); });
    start();
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
