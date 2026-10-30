/* LEO PRODUCTS — point-of-sale till (vanilla JS).
   Shows products, keeps the current sale in memory and sends it to the server.
   The server recalculates prices, stock, discount, total and change, and
   refuses anything that doesn't match; nothing here is trusted. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var dataEl = document.getElementById("posData");
    if (!dataEl) return;
    var data = JSON.parse(dataEl.textContent);
    var products = data.products;
    var byId = {};
    products.forEach(function (p) { byId[p.id] = p; });
    var cart = [];            // [{id, qty}] in the order items were added
    var activeCat = null;
    var busy = false;

    var $ = function (id) { return document.getElementById(id); };
    var search = $("posSearch"), cats = $("posCats"), grid = $("posProducts"), noProducts = $("posNoProducts");
    var lines = $("posLines"), empty = $("posEmpty"), clearBtn = $("posClear"), form = $("posForm");
    var discType = $("posDiscType"), discValue = $("posDiscValue"), discReason = $("posDiscReason");
    var approval = $("posApproval"), apprUser = $("posApprUser"), apprPass = $("posApprPass");
    var tendered = $("posTendered"), quick = $("posQuick"), change = $("posChange");
    var cashBox = $("posCashBox"), bankBox = $("posBankBox"), bankRef = $("posBankRef");
    var errorBox = $("posError"), submit = $("posSubmit");

    // ---- money helpers (cents as integers, rounding half up like the server) ----
    function cents(text) { return Math.round(parseFloat(text) * 100); }
    function fmt(c) {
      return data.currency + " " + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    // ---- products ----
    function renderCats() {
      var all = el("button", "leo-chip" + (activeCat === null ? " active" : ""), "All");
      all.type = "button";
      all.addEventListener("click", function () { activeCat = null; renderCats(); renderProducts(); });
      cats.replaceChildren(all);
      data.categories.forEach(function (c) {
        var b = el("button", "leo-chip" + (activeCat === c.id ? " active" : ""), c.name);
        b.type = "button";
        b.setAttribute("aria-pressed", activeCat === c.id ? "true" : "false");
        b.addEventListener("click", function () { activeCat = c.id; renderCats(); renderProducts(); });
        cats.appendChild(b);
      });
    }

    function matches(p, q) {
      if (activeCat !== null && p.category !== activeCat) return false;
      if (!q) return true;
      return (p.product + " " + p.size + " " + p.sku).toLowerCase().indexOf(q) !== -1;
    }

    function renderProducts() {
      var q = search.value.trim().toLowerCase();
      var shown = products.filter(function (p) { return matches(p, q); });
      grid.replaceChildren.apply(grid, shown.map(function (p) {
        var b = el("button", "leo-pos__tile");
        b.type = "button";
        b.appendChild(el("span", "leo-pos__tile-name", p.product));
        b.appendChild(el("span", "leo-pos__tile-size", p.size));
        b.appendChild(el("span", "leo-pos__tile-price", fmt(cents(p.price))));
        b.appendChild(el("span", "leo-pos__tile-stock", p.stock + " in stock · " + p.sku));
        b.addEventListener("click", function () { add(p.id); });
        return b;
      }));
      noProducts.hidden = shown.length > 0;
      return shown;
    }

    // ---- cart ----
    function qtyOf(id) {
      var line = cart.find(function (l) { return l.id === id; });
      return line ? line.qty : 0;
    }
    function showError(message) { errorBox.textContent = message; errorBox.hidden = !message; }

    function add(id) {
      var p = byId[id];
      var line = cart.find(function (l) { return l.id === id; });
      if ((line ? line.qty : 0) + 1 > p.stock) { showError("Only " + p.stock + " of " + p.product + " (" + p.size + ") in stock."); return; }
      if (line) line.qty += 1; else cart.push({ id: id, qty: 1 });
      showError("");
      render();
    }

    function setQty(id, qty) {
      var p = byId[id];
      qty = Math.floor(qty);
      if (!(qty > 0)) { cart = cart.filter(function (l) { return l.id !== id; }); }
      else {
        if (qty > p.stock) { qty = p.stock; showError("Only " + p.stock + " of " + p.product + " in stock."); }
        cart.find(function (l) { return l.id === id; }).qty = qty;
      }
      render();
    }

    function totals() {
      var subtotal = cart.reduce(function (sum, l) { return sum + cents(byId[l.id].price) * l.qty; }, 0);
      var discount = 0, value = parseFloat(discValue.value);
      if (discType.value && value > 0) {
        discount = discType.value === "PERCENT" ? Math.round(subtotal * Math.min(value, 100) / 100) : Math.round(value * 100);
      }
      var invalid = discount > subtotal;
      if (invalid) discount = subtotal;
      var percent = subtotal ? discount * 100 / subtotal : 0;
      return { subtotal: subtotal, discount: discount, total: subtotal - discount, percent: percent, invalidDiscount: invalid };
    }

    function renderLines() {
      lines.replaceChildren.apply(lines, cart.map(function (l) {
        var p = byId[l.id];
        var li = el("li", "leo-pos__line");
        var info = el("div", "leo-pos__line-info");
        info.appendChild(el("span", "fw-semibold", p.product));
        info.appendChild(el("span", "small text-body-secondary", p.size + " · " + fmt(cents(p.price)) + " each"));
        var qtyBox = el("div", "leo-pos__qty");
        var minus = el("button", "btn btn-leo-outline btn-sm", "−");
        minus.type = "button"; minus.setAttribute("aria-label", "One less " + p.product);
        minus.addEventListener("click", function () { setQty(l.id, l.qty - 1); });
        var input = el("input", "form-control form-control-sm");
        input.type = "number"; input.min = "0"; input.max = String(p.stock); input.value = l.qty; input.inputMode = "numeric";
        input.setAttribute("aria-label", "Quantity of " + p.product + " " + p.size);
        input.addEventListener("change", function () { setQty(l.id, parseInt(input.value, 10) || 0); });
        var plus = el("button", "btn btn-leo-outline btn-sm", "+");
        plus.type = "button"; plus.setAttribute("aria-label", "One more " + p.product);
        plus.addEventListener("click", function () { add(l.id); });
        qtyBox.append(minus, input, plus);
        var total = el("span", "leo-pos__line-total", fmt(cents(p.price) * l.qty));
        var remove = el("button", "btn btn-link btn-sm leo-cart-remove");
        remove.type = "button";
        remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i><span class="visually-hidden">Remove</span>';
        remove.addEventListener("click", function () { setQty(l.id, 0); });
        li.append(info, qtyBox, total, remove);
        return li;
      }));
      empty.hidden = cart.length > 0;
      clearBtn.disabled = cart.length === 0;
    }

    function method() { return form.querySelector('input[name="payment_method"]:checked').value; }

    function renderQuick(total) {
      var options = [total];
      [100000, 500000].forEach(function (step) {   // next LKR 1,000 and 5,000
        var up = Math.ceil(total / step) * step;
        if (up > total && options.indexOf(up) === -1) options.push(up);
      });
      quick.replaceChildren.apply(quick, options.map(function (c, i) {
        var b = el("button", "btn btn-leo-outline btn-sm", i === 0 ? "Exact" : fmt(c));
        b.type = "button";
        b.addEventListener("click", function () { tendered.value = (c / 100).toFixed(2); render(); });
        return b;
      }));
    }

    function render() {
      renderLines();
      var t = totals();
      $("posSubtotal").textContent = fmt(t.subtotal);
      $("posDiscount").textContent = t.discount ? "− " + fmt(t.discount) : "—";
      $("posTotal").textContent = fmt(t.total);
      approval.hidden = !(t.discount > 0 && t.percent > parseFloat(data.discountLimit) + 1e-9);
      var cash = method() === "CASH";
      cashBox.hidden = !cash;
      bankBox.hidden = cash;
      renderQuick(t.total);
      var given = tendered.value === "" ? null : cents(tendered.value);
      if (given === null) change.textContent = "—";
      else if (given < t.total) change.textContent = "Short by " + fmt(t.total - given);
      else change.textContent = fmt(given - t.total);
      var ready = cart.length > 0 && !t.invalidDiscount &&
        (cash ? given !== null && given >= t.total : bankRef.value.trim() !== "");
      submit.disabled = busy || !ready;
      var tooBig = "The discount can't be more than the sale amount.";
      if (t.invalidDiscount) showError(tooBig);
      else if (errorBox.textContent === tooBig) showError("");
      return t;
    }

    // ---- events ----
    search.addEventListener("input", renderProducts);
    search.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      event.preventDefault();
      var q = search.value.trim().toLowerCase();
      if (!q) return;
      // A barcode scanner types the SKU followed by Enter.
      var exact = products.find(function (p) { return p.sku.toLowerCase() === q; });
      var shown = renderProducts();
      var pick = exact || (shown.length === 1 ? shown[0] : null);
      if (pick) { add(pick.id); search.value = ""; renderProducts(); }
      else showError(shown.length ? "Several products match; tap the one you want." : "No product with that name or SKU.");
    });
    [discType, discValue, tendered, bankRef].forEach(function (input) { input.addEventListener("input", render); });
    form.querySelectorAll('input[name="payment_method"]').forEach(function (r) { r.addEventListener("change", render); });
    clearBtn.addEventListener("click", function () {
      if (cart.length && window.confirm("Remove all items from this sale?")) { cart = []; showError(""); render(); }
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (busy) return;
      var t = render();
      if (submit.disabled) return;
      busy = true;
      submit.disabled = true;
      submit.setAttribute("aria-busy", "true");
      submit.querySelector(".spinner-border").hidden = false;
      submit.querySelector("[data-label]").textContent = "Saving sale…";
      showError("");
      var payload = {
        token: data.token,
        lines: cart.map(function (l) { return { id: l.id, qty: l.qty }; }),
        payment_method: method(),
        cash_tendered: method() === "CASH" ? tendered.value : null,
        bank_reference: bankRef.value,
        discount_type: t.discount ? discType.value : "",
        discount_value: t.discount ? discValue.value : null,
        discount_reason: discReason.value,
        approver_username: approval.hidden ? "" : apprUser.value,
        approver_password: approval.hidden ? "" : apprPass.value,
        customer_name: $("posCustName").value,
        customer_phone: $("posCustPhone").value,
        expected_total: (t.total / 100).toFixed(2)
      };
      fetch(data.checkoutUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.json().catch(function () { return { ok: false, error: "Unexpected server response (" + response.status + ")." }; });
      }).then(function (result) {
        if (result.ok) { window.location.href = result.receipt_url; return; }
        apprPass.value = "";
        showError(result.error || "The sale could not be saved.");
        if (result.code === "needs_approval") approval.hidden = false;
        done();
      }).catch(function () {
        // Network problem: the same token is sent again on retry, so the sale can't be recorded twice.
        showError("Connection problem. Check the network and press Complete sale again.");
        done();
      });
    });

    function done() {
      busy = false;
      submit.removeAttribute("aria-busy");
      submit.querySelector(".spinner-border").hidden = true;
      submit.querySelector("[data-label]").textContent = "Complete sale";
      render();
    }

    renderCats();
    renderProducts();
    render();
  });
})();
