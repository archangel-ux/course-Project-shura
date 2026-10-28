// Small progressive enhancements. Every page works without JavaScript.
(function () {
  "use strict";

  const body = document.body;
  const csrf = body.dataset.csrf;
  const numberFormat = new Intl.NumberFormat("ru-RU");

  // Filter forms: selects and tabs reload the list; the search box filters rows instantly
  // without a reload (Enter still submits, so the search ends up in the URL).
  document.querySelectorAll("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", (event) => {
      if (event.target.type !== "search") form.requestSubmit();
    });
    const tbody = document.querySelector("tbody[data-filterable]");
    form.querySelectorAll("input[type=search]").forEach((input) => {
      if (!tbody) return;
      const rows = Array.from(tbody.rows);
      const empty = document.createElement("tr");
      empty.className = "no-results";
      empty.innerHTML = '<td colspan="99"></td>';
      empty.firstChild.textContent = body.dataset.textNoResults;
      input.addEventListener("input", () => {
        const needle = input.value.trim().toLowerCase();
        let shown = 0;
        rows.forEach((row) => {
          const match = !needle || row.textContent.toLowerCase().includes(needle);
          row.hidden = !match;
          if (match) shown += 1;
        });
        if (shown === 0) tbody.appendChild(empty); else empty.remove();
      });
    });
  });

  // Styled confirmation instead of the browser's confirm().
  function askConfirm(text) {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog");
      dialog.className = "dialog";
      dialog.innerHTML =
        '<p class="dialog__text"></p><div class="dialog__actions">' +
        '<button type="button" class="btn btn--text" value="cancel"></button>' +
        '<button type="button" class="btn btn--primary" value="ok"></button></div>';
      dialog.querySelector(".dialog__text").textContent = text;
      const [cancel, ok] = dialog.querySelectorAll("button");
      cancel.textContent = body.dataset.textCancel;
      ok.textContent = body.dataset.textOk;
      const close = (result) => { dialog.close(); dialog.remove(); resolve(result); };
      cancel.addEventListener("click", () => close(false));
      ok.addEventListener("click", () => close(true));
      dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(false); });
      document.body.appendChild(dialog);
      dialog.showModal();
      ok.focus();
    });
  }

  // Password fields get a show/hide button.
  document.querySelectorAll("input[type=password]").forEach((input) => {
    const wrapper = document.createElement("span");
    wrapper.className = "password";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "password__toggle";
    const eye = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>';
    const render = () => {
      const hidden = input.type === "password";
      toggle.innerHTML = eye + (hidden ? "" : '<path d="M4 4l16 16"/>') + "</svg>";
      toggle.setAttribute("aria-label", hidden ? body.dataset.textShow : body.dataset.textHide);
    };
    toggle.addEventListener("click", () => {
      input.type = input.type === "password" ? "text" : "password";
      render();
      input.focus();
    });
    render();
    wrapper.appendChild(toggle);
  });

  // Whole table rows are clickable where marked.
  document.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, select")) return;
      window.location.href = row.dataset.href;
    });
  });

  // Confirmation before destructive actions. form.submit() skips this handler on the second pass.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      askConfirm(form.dataset.confirm).then((ok) => { if (ok) form.submit(); });
    });
  });
  document.querySelectorAll("[data-confirm-submit]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      askConfirm(button.dataset.confirmSubmit).then((ok) => { if (ok) button.form.submit(); });
    });
  });

  // Dropdown menus close on outside click and Escape.
  const menus = document.querySelectorAll("details.menu");
  document.addEventListener("click", (event) => {
    menus.forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") menus.forEach((menu) => { menu.open = false; });
  });

  // Toasts: dismiss button, success ones fade on their own.
  document.querySelectorAll("[data-toast]").forEach((toast) => {
    const close = () => toast.remove();
    toast.querySelector("[data-dismiss]")?.addEventListener("click", close);
    if (!toast.classList.contains("toast--error")) setTimeout(close, 7000);
  });

  // Movement form: supplier only for stock-in, show the current balance of the chosen product.
  document.querySelectorAll("form[data-movement-form]").forEach((form) => {
    const supplierField = form.querySelector("[data-only-in]");
    const select = form.querySelector("[data-product-select]");
    const stockline = form.querySelector("[data-stockline]");

    const syncType = () => {
      const type = form.querySelector("input[name=movement_type]:checked")?.value;
      if (supplierField) supplierField.hidden = type !== "IN";
    };
    const syncProduct = () => {
      if (!select || !stockline) return;
      const option = select.selectedOptions[0];
      if (!option || !option.value) { stockline.textContent = ""; return; }
      const qty = Number(option.dataset.qty);
      const min = Number(option.dataset.min);
      stockline.innerHTML = stockline.dataset.template
        .replace("{qty}", "<b>" + numberFormat.format(qty) + "</b>")
        .replace("{min}", numberFormat.format(min))
        .replaceAll("{unit}", option.dataset.unit);
      stockline.classList.toggle("is-low", qty <= min);
    };
    form.addEventListener("change", () => { syncType(); syncProduct(); });
    syncType();
    syncProduct();
  });

  // Stocktake: live difference per row and a running summary.
  document.querySelectorAll("form[data-stocktake]").forEach((form) => {
    const summary = form.querySelector("[data-stocktake-summary]");
    const emptyText = summary.textContent;
    const update = () => {
      let counted = 0;
      let changed = 0;
      form.querySelectorAll("tr[data-system]").forEach((row) => {
        const input = row.querySelector("input");
        const cell = row.querySelector("[data-diff]");
        if (input.value === "") { cell.textContent = "—"; cell.className = "num"; return; }
        counted += 1;
        const diff = Number(input.value) - Number(row.dataset.system);
        if (diff !== 0) changed += 1;
        cell.textContent = diff === 0 ? "0" : (diff > 0 ? "+" : "−") + numberFormat.format(Math.abs(diff));
        cell.className = "num qty " + (diff > 0 ? "qty--in" : diff < 0 ? "qty--out" : "qty--adj");
      });
      summary.innerHTML = counted === 0 ? emptyText : summary.dataset.template
        .replace("{counted}", "<b>" + counted + "</b>")
        .replace("{changed}", "<b>" + changed + "</b>");
    };
    form.addEventListener("input", update);
    update();
  });

  // CSV dropzone: show the chosen file name, highlight on drag.
  document.querySelectorAll("[data-dropzone]").forEach((zone) => {
    const input = zone.querySelector("[data-file-input]");
    const label = zone.querySelector("[data-file-name]");
    input.addEventListener("change", () => { if (input.files[0]) label.textContent = input.files[0].name; });
    ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, () => zone.classList.add("is-over")));
    ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, () => zone.classList.remove("is-over")));
  });

  // Supabase email links (confirm signup, reset password, change email) put the session in the URL hash.
  const callback = document.getElementById("callback-status");
  if (callback) {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const query = new URLSearchParams(window.location.search);
    const fail = (text) => { callback.textContent = text || callback.dataset.errorText; };
    if (params.get("error_description") || query.get("error_description")) {
      fail(params.get("error_description") || query.get("error_description"));
    } else if (!params.get("access_token")) {
      fail();
    } else {
      fetch(callback.dataset.sessionUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          access_token: params.get("access_token"),
          refresh_token: params.get("refresh_token"),
          expires_in: params.get("expires_in"),
          type: params.get("type"),
        }),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          history.replaceState(null, "", window.location.pathname);
          if (ok && data.redirect) window.location.replace(data.redirect);
          else fail(data.error);
        })
        .catch(() => fail());
    }
  }
})();
