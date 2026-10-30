/* LEO PRODUCTS — receipt page: Print button, and print automatically straight after a sale. */
(function () {
  "use strict";
  var button = document.getElementById("printReceipt");
  if (button) button.addEventListener("click", function () { window.print(); });
  if (/[?&]new=1(&|$)/.test(window.location.search) && document.body.classList.contains("receipt-page--thermal")) {
    window.addEventListener("load", function () { setTimeout(function () { window.print(); }, 300); });
  }
})();
