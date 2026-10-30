/* LEO PRODUCTS — checkout form: show the address only for home delivery and
   offer only the payment methods allowed for the chosen option.
   Purely a convenience: the server validates every choice again. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("checkoutForm");
    if (!form) return;
    var mapEl = document.getElementById("leoPaymentMap");
    var paymentMap = mapEl ? JSON.parse(mapEl.textContent) : {};
    var fulfilmentInputs = form.querySelectorAll('input[name="fulfilment"]');
    var paymentInputs = form.querySelectorAll('input[name="payment_method"]');

    function chosenFulfilment() {
      var checked = form.querySelector('input[name="fulfilment"]:checked');
      return checked ? checked.value : null;
    }

    function update() {
      var fulfilment = chosenFulfilment();
      form.querySelectorAll("[data-for-fulfilment]").forEach(function (section) {
        // Visible until a choice is made, so nothing is hidden by surprise.
        section.hidden = fulfilment !== null && section.getAttribute("data-for-fulfilment") !== fulfilment;
      });
      var allowed = fulfilment && paymentMap[fulfilment];
      paymentInputs.forEach(function (input) {
        var label = input.closest(".leo-choice");
        var ok = !allowed || allowed.indexOf(input.value) !== -1;
        input.disabled = !ok;
        if (!ok && input.checked) input.checked = false;
        if (label) label.hidden = !ok;
      });
    }

    fulfilmentInputs.forEach(function (input) { input.addEventListener("change", update); });
    update();
  });
})();
