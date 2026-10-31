/* LEO PRODUCTS — send the signed payment form to the gateway automatically (the button remains as a fallback). */
(function () {
  "use strict";
  var form = document.getElementById("gatewayForm");
  if (form) form.submit();
})();
