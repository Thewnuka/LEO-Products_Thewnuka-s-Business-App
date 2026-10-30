/* LEO PRODUCTS — storefront product page (vanilla JavaScript).
   Shows the price, availability and image of the chosen option. The server
   checks the option and quantity again when the form is submitted. */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("addToCart");
    if (!form) return;
    var price = document.getElementById("shopPrice");
    var avail = document.getElementById("shopAvailability");
    var qty = document.getElementById("qty");
    var images = document.querySelectorAll("[data-variation-image]");
    var mainImage = document.querySelector(".leo-product-gallery__img:not([data-variation-image])");

    function show(radio) {
      if (!radio) return;
      if (price) price.textContent = radio.getAttribute("data-price");
      if (avail) {
        var low = radio.getAttribute("data-low") === "1";
        avail.innerHTML = "";
        var span = document.createElement("span");
        span.className = "leo-avail" + (low ? " leo-avail--low" : "");
        span.innerHTML = '<i class="bi bi-check-circle" aria-hidden="true"></i>';
        span.appendChild(document.createTextNode(radio.getAttribute("data-availability")));
        avail.appendChild(span);
      }
      if (qty) {
        var max = parseInt(radio.getAttribute("data-max"), 10) || 1;
        qty.max = String(max);
        if ((parseInt(qty.value, 10) || 1) > max) qty.value = String(max);
      }
      var shown = false;
      images.forEach(function (img) {
        var match = img.getAttribute("data-variation-image") === radio.value;
        img.hidden = !match;
        if (match) shown = true;
      });
      if (mainImage) mainImage.hidden = shown;
    }

    form.querySelectorAll('input[name="variation"]').forEach(function (radio) {
      radio.addEventListener("change", function () { show(radio); });
    });
    show(form.querySelector('input[name="variation"]:checked'));
  });
})();
