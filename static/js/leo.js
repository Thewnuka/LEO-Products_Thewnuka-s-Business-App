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

    // Show / hide password buttons (partials/_form_field.html). Only changes how the
    // field is displayed; the password itself is submitted exactly as before.
    document.querySelectorAll("button[data-password-toggle]").forEach(function (button) {
      var input = document.getElementById(button.getAttribute("data-password-toggle"));
      if (!input) return;
      var icon = button.querySelector("i");
      button.hidden = false;
      button.addEventListener("click", function () {
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        button.setAttribute("aria-pressed", show ? "true" : "false");
        var label = show ? "Hide password" : "Show password";
        button.setAttribute("aria-label", label);
        button.title = label;
        if (icon) icon.className = show ? "bi bi-eye-slash" : "bi bi-eye";
        input.focus();
      });
      // Hide the password again before the form is sent, so the browser never stores it as plain text.
      if (input.form) input.form.addEventListener("submit", function () { input.type = "password"; });
    });

    // Staff portal: keep the sidebar where it was when moving between pages, so choosing
    // "Dashboard" (or any item) doesn't send the menu back to the top. Also tells the CSS
    // how tall the sticky top bar is, so the sidebar column fits exactly beneath it.
    var staffHeader = document.querySelector(".leo-staff-header");
    if (staffHeader) {
      var setHeaderHeight = function () {
        document.documentElement.style.setProperty("--leo-header-h", staffHeader.offsetHeight + "px");
      };
      setHeaderHeight();
      window.addEventListener("resize", setHeaderHeight);
    }
    var sideColumn = document.querySelector(".leo-sidebar");
    if (sideColumn) {
      var SIDEBAR_KEY = "leo-sidebar-scroll";
      var saved = null;
      try { saved = window.sessionStorage.getItem(SIDEBAR_KEY); } catch (e) { /* storage unavailable */ }
      if (saved !== null) {
        sideColumn.scrollTop = parseInt(saved, 10) || 0;
      }
      // Make sure the current page's link is visible (e.g. first visit, or a link opened from elsewhere).
      var activeLink = sideColumn.querySelector(".nav-link.active");
      if (activeLink && sideColumn.scrollHeight > sideColumn.clientHeight) {
        var top = activeLink.offsetTop, view = sideColumn.scrollTop;
        if (top < view || top + activeLink.offsetHeight > view + sideColumn.clientHeight) {
          sideColumn.scrollTop = Math.max(0, top - sideColumn.clientHeight / 3);
        }
      }
      var saveSidebar = function () {
        try { window.sessionStorage.setItem(SIDEBAR_KEY, String(sideColumn.scrollTop)); } catch (e) { /* ignore */ }
      };
      sideColumn.addEventListener("click", saveSidebar);
      window.addEventListener("pagehide", saveSidebar);
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
