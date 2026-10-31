/* LEO PRODUCTS — printable report page: Print button. */
(function () {
  "use strict";
  var button = document.getElementById("printReport");
  if (button) button.addEventListener("click", function () { window.print(); });
})();
