/* LEO PRODUCTS — catalogue forms (vanilla JavaScript).
   Convenience only: the server validates every rule again. */
(function () {
  "use strict";

  // Show only the options of a dependent <select> that match a parent value.
  //   childSelect: <select data-subcategory-for="id_category">  options carry data-parent
  //   childSelect: <select data-unit-for="id_measurement_type">  options carry data-measurement
  function linkSelects(child, parent, attr) {
    function refresh() {
      var value = parent.value;
      var current = child.options[child.selectedIndex];
      Array.prototype.forEach.call(child.options, function (opt) {
        if (!opt.value) return; // keep the empty "All / None" option
        var match = !value || opt.getAttribute(attr) === value;
        opt.hidden = !match;
        opt.disabled = !match;
      });
      if (current && current.value && current.disabled) child.value = "";
    }
    parent.addEventListener("change", refresh);
    refresh();
  }

  function setup() {
    document.querySelectorAll("select[data-subcategory-for]").forEach(function (child) {
      var parent = document.getElementById(child.getAttribute("data-subcategory-for"));
      if (parent) linkSelects(child, parent, "data-parent");
    });
    document.querySelectorAll("select[data-unit-for]").forEach(function (child) {
      var parent = document.getElementById(child.getAttribute("data-unit-for"));
      if (parent) linkSelects(child, parent, "data-measurement");
    });

    // Live preview of a chosen image before it is uploaded.
    document.querySelectorAll(".leo-image-field").forEach(function (wrap) {
      var input = wrap.querySelector('input[type="file"]');
      var preview = wrap.querySelector(".leo-image-preview");
      if (!input || !preview) return;
      input.addEventListener("change", function () {
        var file = input.files && input.files[0];
        if (!file || !/^image\/(jpeg|png|webp)$/.test(file.type)) return;
        preview.src = URL.createObjectURL(file);
        preview.classList.remove("leo-img--placeholder");
        preview.alt = "Preview of the new image";
      });
    });
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
