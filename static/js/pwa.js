/* LEO PRODUCTS — register the service worker (installable app). It caches static files only; see apps/core/pwa.py. */
(function () {
  "use strict";
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* the site works without it */ });
  });
})();
