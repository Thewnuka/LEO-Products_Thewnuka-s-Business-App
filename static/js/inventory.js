/* LEO PRODUCTS — inventory forms (vanilla JavaScript).
   Convenience only: every rule is validated again on the server. */
(function () {
  "use strict";

  function money(n) {
    return "LKR " + (isFinite(n) ? n : 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // Track-new-item form: show the raw-material or finished-product fields.
  function setupItemForm() {
    var form = document.getElementById("itemForm");
    if (!form) return;
    var radios = form.querySelectorAll('input[name="kind"]');
    if (!radios.length) return;
    function refresh() {
      var checked = form.querySelector('input[name="kind"]:checked');
      var kind = checked ? checked.value : "";
      form.querySelectorAll("[data-kind-section]").forEach(function (section) {
        section.hidden = section.getAttribute("data-kind-section") !== kind;
      });
    }
    radios.forEach(function (r) { r.addEventListener("change", refresh); });
    refresh();
  }

  // Adjust-stock form: "Direction" only matters for "Other adjustment".
  function setupAdjustForm() {
    var form = document.getElementById("adjustForm");
    if (!form) return;
    var type = form.querySelector('select[name="movement_type"]');
    var wrap = form.querySelector('[data-show-for="OTHER"]');
    if (!type || !wrap) return;
    function refresh() { wrap.hidden = type.value !== "OTHER"; }
    type.addEventListener("change", refresh);
    refresh();
  }

  // Purchase form: add lines, match units to the chosen item, live totals.
  function setupPurchaseForm() {
    var form = document.getElementById("purchaseForm");
    if (!form) return;
    var container = document.getElementById("purchaseLines");
    var template = document.getElementById("emptyLine");
    var totalForms = form.querySelector('input[name="lines-TOTAL_FORMS"]');
    var totalEl = document.getElementById("purchaseTotal");

    function setupLine(line) {
      var item = line.querySelector('select[name$="-item"]');
      var unit = line.querySelector('select[name$="-unit"]');
      var qty = line.querySelector('input[name$="-quantity"]');
      var cost = line.querySelector('input[name$="-unit_cost"]');
      var countLabel = line.querySelector("[data-count-display]");  // not [data-count-label]: item <option>s carry that attribute
      var unitField = unit ? unit.closest(".leo-field") : null;

      function refreshUnits() {
        var opt = item && item.options[item.selectedIndex];
        var finished = opt && opt.getAttribute("data-finished") === "1";
        if (unitField) unitField.hidden = !!finished;
        if (countLabel) {
          countLabel.hidden = !finished;
          countLabel.textContent = finished ? opt.getAttribute("data-count-label") : "";
        }
        if (!unit || finished || !opt || !opt.value) return;
        var measurement = opt.getAttribute("data-measurement");
        var stockUnit = opt.getAttribute("data-stock-unit");
        Array.prototype.forEach.call(unit.options, function (u) {
          if (!u.value) return;
          var ok = u.getAttribute("data-measurement") === measurement &&
                   (u.value === stockUnit || u.getAttribute("data-convertible") === "1");
          u.hidden = !ok;
          u.disabled = !ok;
        });
        if (unit.value && unit.options[unit.selectedIndex].disabled) unit.value = "";
      }
      function refreshTotal() {
        var t = (parseFloat(qty && qty.value) || 0) * (parseFloat(cost && cost.value) || 0);
        var out = line.querySelector("[data-line-total]");
        if (out) out.textContent = money(Math.round(t * 100) / 100);
        refreshGrandTotal();
      }
      if (item) item.addEventListener("change", refreshUnits);
      [qty, cost].forEach(function (el) { if (el) el.addEventListener("input", refreshTotal); });
      var del = line.querySelector('input[name$="-DELETE"]');
      if (del) del.addEventListener("change", function () { line.classList.toggle("leo-line--removed", del.checked); refreshGrandTotal(); });
      refreshUnits();
      refreshTotal();
    }

    function refreshGrandTotal() {
      var sum = 0;
      container.querySelectorAll("[data-line]").forEach(function (line) {
        var del = line.querySelector('input[name$="-DELETE"]');
        if (del && del.checked) return;
        var q = parseFloat((line.querySelector('input[name$="-quantity"]') || {}).value) || 0;
        var c = parseFloat((line.querySelector('input[name$="-unit_cost"]') || {}).value) || 0;
        sum += Math.round(q * c * 100) / 100;
      });
      if (totalEl) totalEl.textContent = money(sum);
    }

    container.querySelectorAll("[data-line]").forEach(setupLine);
    var addBtn = document.getElementById("addLine");
    if (addBtn && template && totalForms) {
      addBtn.addEventListener("click", function () {
        var index = parseInt(totalForms.value, 10);
        var html = template.innerHTML.replace(/__prefix__/g, String(index));
        var wrapper = document.createElement("div");
        wrapper.innerHTML = html.trim();
        var line = wrapper.firstElementChild;
        container.appendChild(line);
        totalForms.value = String(index + 1);
        setupLine(line);
        var first = line.querySelector("select");
        if (first) first.focus();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupItemForm();
    setupAdjustForm();
    setupPurchaseForm();
  });
})();
