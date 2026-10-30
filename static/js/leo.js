/* LEO PRODUCTS — site-wide JavaScript (vanilla, no frameworks). */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // On phones, close the expanded navbar after tapping a same-page link
    // (e.g. "About"), so the menu does not cover the section scrolled to.
    var navCollapse = document.getElementById("leoMainNav");
    if (navCollapse && window.bootstrap) {
      navCollapse.querySelectorAll("a.nav-link:not(.dropdown-toggle)").forEach(function (link) {
        link.addEventListener("click", function () {
          if (navCollapse.classList.contains("show")) {
            window.bootstrap.Collapse.getOrCreateInstance(navCollapse).hide();
          }
        });
      });
    }

    // Same for the off-canvas sidebar on small screens.
    var sidebar = document.getElementById("leoSidebar");
    if (sidebar && window.bootstrap) {
      sidebar.querySelectorAll("a.nav-link").forEach(function (link) {
        link.addEventListener("click", function () {
          var instance = window.bootstrap.Offcanvas.getInstance(sidebar);
          if (instance) instance.hide();
        });
      });
    }

    // Ask before submitting forms marked with data-confirm="Question?"
    // (e.g. deactivating an account). The server still enforces permissions.
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
      });
    });

    // Same question for one button of a form (e.g. "Approve" next to "Reject").
    document.querySelectorAll("button[data-confirm-click]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        if (!window.confirm(button.getAttribute("data-confirm-click"))) event.preventDefault();
      });
    });

    // Forms marked data-once (e.g. "Place order") can be submitted only once
    // per page load, so a double click cannot send two requests. The server
    // also rejects duplicates; this just avoids a confusing second request.
    document.querySelectorAll("form[data-once]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;
        if (form.dataset.submitted) { event.preventDefault(); return; }
        form.dataset.submitted = "1";
        form.querySelectorAll('button[type="submit"]').forEach(function (button) {
          button.disabled = true;
          button.setAttribute("aria-busy", "true");
        });
      });
    });
    // Coming back with the browser's Back button restores the page from cache:
    // make those forms usable again.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      document.querySelectorAll("form[data-once]").forEach(function (form) {
        delete form.dataset.submitted;
        form.querySelectorAll('button[type="submit"]').forEach(function (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        });
      });
    });
  });
})();
