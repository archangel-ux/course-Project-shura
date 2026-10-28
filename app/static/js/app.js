// Progressive enhancements. Every page works without JavaScript.
//
// Navigation: same-site links and forms are loaded with fetch() and only the <body> is
// swapped, so the browser keeps CSS, fonts and this script in memory — a page change costs
// one server round trip and no re-parse. Links are prefetched on hover, so most clicks open
// instantly. Anything unusual (PDF, CSV, new tab, other origin) falls back to normal loading.
(function () {
  "use strict";

  const body = document.body;
  const numberFormat = new Intl.NumberFormat("ru-RU");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const csrf = () => body.dataset.csrf;

  // ================================================================ page features
  // init(root) runs on first load and after every swap. Listeners on document live below, once.

  function init() {
    document.querySelectorAll(".select select").forEach(enhanceSelect);
    initFilters();
    initConfirm();
    initPasswords();
    initRegister();
    initRows();
    initToasts();
    initCopy();
    initPhoto();
    initCountUp();
    initMovementForms();
    initStocktake();
    initDropzones();
    initTelegram();
    initCallback();
  }

  // ---------------------------------------------------------------- custom dropdowns
  // The native <select> stays in the form; we draw a styled button + listbox and keep both
  // in sync. Long lists get a search box.

  let openSelect = null;
  const closeOpenSelect = () => { if (openSelect) openSelect(); };

  function enhanceSelect(select) {
    const wrap = select.closest(".select");
    if (!wrap || wrap.classList.contains("is-enhanced")) return;
    wrap.classList.add("is-enhanced");
    select.tabIndex = -1;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "cselect__button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    if (select.getAttribute("aria-label")) button.setAttribute("aria-label", select.getAttribute("aria-label"));
    const label = document.createElement("span");
    button.appendChild(label);
    wrap.insertBefore(button, select);

    const render = () => {
      const option = select.selectedOptions[0];
      label.textContent = option ? option.textContent : "";
      button.classList.toggle("is-placeholder", !option || option.value === "");
    };
    render();
    select.addEventListener("change", render);

    function open() {
      closeOpenSelect();
      const options = Array.from(select.options);
      const searchable = options.length > 8 || select.hasAttribute("data-searchable");
      const panel = document.createElement("div");
      panel.className = "cselect__panel";
      let search = null;
      if (searchable) {
        search = document.createElement("input");
        search.className = "cselect__search";
        search.type = "search";
        search.placeholder = body.dataset.textSearch || "";
        search.autocomplete = "off";
        panel.appendChild(search);
      }
      const list = document.createElement("ul");
      list.className = "cselect__list";
      list.setAttribute("role", "listbox");
      panel.appendChild(list);
      const empty = document.createElement("div");
      empty.className = "cselect__empty";
      empty.textContent = body.dataset.textNoResults || "";

      let items = [];
      let shown = [];
      let active = -1;
      const setActive = (index) => {
        if (items[active]) items[active].classList.remove("is-active");
        active = Math.min(Math.max(index, 0), items.length - 1);
        if (items[active]) {
          items[active].classList.add("is-active");
          items[active].scrollIntoView({ block: "nearest" });
        }
      };
      const build = (needle) => {
        list.textContent = "";
        shown = options.filter((o) => !needle || o.textContent.toLowerCase().includes(needle));
        items = shown.map((option) => {
          const item = document.createElement("li");
          item.className = "cselect__option" + (option.value === "" ? " is-placeholder" : "");
          item.setAttribute("role", "option");
          item.setAttribute("aria-selected", String(option.selected && option.value !== ""));
          const text = document.createElement("span");
          text.textContent = option.textContent;
          item.appendChild(text);
          item.addEventListener("mousedown", (event) => event.preventDefault());
          item.addEventListener("click", () => choose(option));
          item.addEventListener("mousemove", () => { if (items[active] !== item) setActive(items.indexOf(item)); });
          list.appendChild(item);
          return item;
        });
        if (!items.length) list.appendChild(empty);
        setActive(Math.max(0, shown.findIndex((o) => o.selected)));
      };
      const choose = (option) => {
        if (select.value !== option.value) {
          select.value = option.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        close();
        button.focus();
      };

      const place = () => {
        const rect = button.getBoundingClientRect();
        const below = window.innerHeight - rect.bottom - 12;
        const above = rect.top - 12;
        const maxHeight = Math.min(340, Math.max(below, above));
        panel.style.minWidth = rect.width + "px";
        panel.style.maxWidth = Math.max(rect.width, 320) + "px";
        panel.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - Math.max(rect.width, 200) - 8)) + "px";
        list.style.maxHeight = maxHeight - (search ? 48 : 12) + "px";
        if (below < 220 && above > below) {
          panel.style.top = "";
          panel.style.bottom = window.innerHeight - rect.top + 6 + "px";
        } else {
          panel.style.bottom = "";
          panel.style.top = rect.bottom + 6 + "px";
        }
      };

      const onKey = (event) => {
        if (event.key === "ArrowDown") { event.preventDefault(); setActive(active + 1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); setActive(active - 1); }
        else if (event.key === "Enter") { event.preventDefault(); if (shown[active]) choose(shown[active]); }
        else if (event.key === "Escape" || event.key === "Tab") { close(); if (event.key === "Escape") button.focus(); }
      };
      const onOutside = (event) => { if (!panel.contains(event.target) && !button.contains(event.target)) close(); };
      const onScroll = (event) => { if (!panel.contains(event.target)) close(); };

      function close() {
        panel.remove();
        wrap.classList.remove("is-open");
        button.setAttribute("aria-expanded", "false");
        document.removeEventListener("mousedown", onOutside);
        window.removeEventListener("resize", close);
        window.removeEventListener("scroll", onScroll, true);
        openSelect = null;
      }

      build("");
      document.body.appendChild(panel);
      place();
      wrap.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      panel.addEventListener("keydown", onKey);
      if (search) {
        search.addEventListener("input", () => build(search.value.trim().toLowerCase()));
        search.focus();
      } else {
        panel.tabIndex = -1;
        panel.focus();
      }
      document.addEventListener("mousedown", onOutside);
      window.addEventListener("resize", close);
      window.addEventListener("scroll", onScroll, true);
      openSelect = close;
    }

    button.addEventListener("click", () => (wrap.classList.contains("is-open") ? closeOpenSelect() : open()));
    button.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) { event.preventDefault(); open(); }
    });
  }

  // ---------------------------------------------------------------- filters

  // Selects and tabs reload the list; the search box filters rows instantly without a request.
  function initFilters() {
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
    document.querySelectorAll("form[data-autosubmit-select]").forEach((form) => {
      form.addEventListener("change", () => form.requestSubmit());
    });
  }

  // ---------------------------------------------------------------- dialogs

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

  // A confirmed form is submitted again with requestSubmit(), so navigation still goes through fetch.
  function initConfirm() {
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (form.dataset.confirmed) { delete form.dataset.confirmed; return; }
        event.preventDefault();
        const submitter = event.submitter;
        askConfirm(form.dataset.confirm).then((ok) => {
          if (!ok) return;
          form.dataset.confirmed = "1";
          form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
        });
      });
    });
    document.querySelectorAll("[data-confirm-submit]").forEach((button) => {
      button.addEventListener("click", (event) => {
        if (button.dataset.confirmed) { delete button.dataset.confirmed; return; }
        event.preventDefault();
        askConfirm(button.dataset.confirmSubmit).then((ok) => {
          if (!ok) return;
          button.dataset.confirmed = "1";
          button.form.requestSubmit(button);
        });
      });
    });
  }

  // ---------------------------------------------------------------- passwords

  function initPasswords() {
    document.querySelectorAll("input[type=password]").forEach((input) => {
      if (input.parentNode.classList.contains("password")) return;
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
  }

  // Registration: strength meter and a live "passwords match" border.
  function initRegister() {
    document.querySelectorAll("form[data-register]").forEach((form) => {
      const input = form.querySelector("[data-strength-input]");
      const confirm = form.querySelector("[data-confirm-input]");
      const meter = form.querySelector("[data-strength]");
      const text = meter.querySelector(".strength__text");
      const hint = text.textContent;
      const labels = meter.dataset.labels.split("|");
      const score = (value) => {
        if (value.length < 8) return value ? 1 : 0;
        let points = 1;
        if (value.length >= 12) points += 1;
        if (/[a-zа-яәғқңөұүһі]/.test(value) && /[A-ZА-ЯӘҒҚҢӨҰҮҺІ]/.test(value)) points += 1;
        if (/\d/.test(value) && /[^\p{L}\d]/u.test(value)) points += 1;
        else if (/\d/.test(value) || /[^\p{L}\d]/u.test(value)) points += 0.5;
        return Math.min(4, Math.floor(points));
      };
      form.addEventListener("input", () => {
        const level = score(input.value);
        meter.dataset.level = level;
        text.textContent = level ? labels[level - 1] : hint;
        if (confirm.value) {
          const same = confirm.value === input.value;
          confirm.classList.toggle("is-match", same);
          confirm.classList.toggle("is-mismatch", !same);
        } else {
          confirm.classList.remove("is-match", "is-mismatch");
        }
      });
    });
  }

  // ---------------------------------------------------------------- small helpers

  function initRows() {
    document.querySelectorAll("tr[data-href]").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest("a, button, input, select")) return;
        navigate(row.dataset.href);
      });
      row.addEventListener("pointerenter", () => prefetch(row.dataset.href));
    });
  }

  function initToasts() {
    document.querySelectorAll("[data-toast]").forEach((toast) => {
      const close = () => {
        toast.classList.add("is-leaving");
        setTimeout(() => toast.remove(), 250);
      };
      toast.querySelector("[data-dismiss]")?.addEventListener("click", close);
      if (toast.classList.contains("toast--success")) setTimeout(close, 7000);
    });
  }

  function copyText(text, button) {
    navigator.clipboard?.writeText(text).then(() => {
      const before = button.dataset.tip;
      button.dataset.tip = body.dataset.textCopied;
      showTip(button);
      setTimeout(() => { if (before === undefined) delete button.dataset.tip; else button.dataset.tip = before; }, 1500);
    });
  }

  function initCopy() {
    document.querySelectorAll("[data-copy]").forEach((button) => {
      const source = button.parentNode.querySelector("[data-copy-source]");
      button.addEventListener("click", () => { source.select(); copyText(source.value, button); });
    });
    document.querySelectorAll("[data-copy-text]").forEach((button) => {
      button.addEventListener("click", () => copyText(button.dataset.copyText, button));
    });
  }

  // Product photo: upload as soon as a file is chosen.
  function initPhoto() {
    document.querySelectorAll("[data-photo-input]").forEach((input) => {
      input.addEventListener("change", () => { if (input.files[0]) input.form.requestSubmit(); });
    });
  }

  // Numbers count up once when they scroll into view. The element keeps its final width
  // from the first frame, so neighbours never shift while the digits change.
  let countObserver = null;
  function initCountUp() {
    if (reduceMotion || !("IntersectionObserver" in window)) return;
    countObserver?.disconnect();
    const animate = (element) => {
      const target = Number(element.dataset.count);
      if (!Number.isFinite(target) || target === 0) return;
      const suffix = element.dataset.suffix || "";
      element.style.minWidth = element.getBoundingClientRect().width + "px";
      const start = performance.now();
      const duration = Math.min(900, 400 + String(Math.abs(target)).length * 70);
      const frame = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        element.textContent = numberFormat.format(Math.round(target * eased)) + suffix;
        if (progress < 1) requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    };
    countObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { animate(entry.target); countObserver.unobserve(entry.target); }
      });
    });
    document.querySelectorAll("[data-count]").forEach((element) => countObserver.observe(element));
  }

  // ---------------------------------------------------------------- operation form

  function initMovementForms() {
    document.querySelectorAll("form[data-movement-form]").forEach((form) => {
      const warehouseSelect = form.querySelector("select[name=warehouse_id]");
      const fromLabel = form.querySelector("[data-from-label]");
      const lines = form.querySelector("[data-lines]");
      const type = () => form.querySelector("input[name=movement_type]:checked")?.value || "IN";

      const syncType = () => {
        const current = type();
        form.querySelectorAll("[data-only-in]").forEach((el) => { el.hidden = current !== "IN"; });
        form.querySelectorAll("[data-only-out]").forEach((el) => { el.hidden = current !== "OUT"; });
        form.querySelectorAll("[data-only-transfer]").forEach((el) => { el.hidden = current !== "TRANSFER"; });
        if (fromLabel) fromLabel.textContent = current === "TRANSFER" ? fromLabel.dataset.textTransfer : fromLabel.dataset.textIn;
      };

      const syncLine = (line) => {
        const select = line.querySelector("[data-product-select]");
        const stockline = line.querySelector("[data-stockline]");
        const qtyInput = line.querySelector("input[name=quantity]");
        if (!select || !stockline) return;
        const option = select.selectedOptions[0];
        if (!option || !option.value) { stockline.textContent = ""; return; }
        let stock = {};
        try { stock = JSON.parse(option.dataset.stock || "{}"); } catch (error) { stock = {}; }
        const qty = Number(stock[warehouseSelect?.value] || 0);
        const min = Number(option.dataset.min);
        stockline.innerHTML = stockline.dataset.template
          .replace("{qty}", "<b>" + numberFormat.format(qty) + "</b>")
          .replace("{min}", numberFormat.format(min))
          .replaceAll("{unit}", option.dataset.unit);
        stockline.classList.toggle("is-low", qty <= min);
        if (qtyInput) {
          if (type() === "IN") qtyInput.removeAttribute("max"); else qtyInput.max = String(qty);
        }
      };
      const syncLines = () => {
        form.querySelectorAll("[data-line]").forEach(syncLine);
        if (lines) lines.classList.toggle("is-single", form.querySelectorAll("[data-line]").length < 2);
      };

      if (lines) {
        const template = lines.querySelector("[data-line]").cloneNode(true);
        template.querySelectorAll(".cselect__button").forEach((el) => el.remove());
        template.querySelectorAll(".select").forEach((el) => el.classList.remove("is-enhanced", "is-open"));
        lines.querySelector("[data-add-line]").addEventListener("click", () => {
          const line = template.cloneNode(true);
          line.querySelector("select").value = "";
          line.querySelector("input[name=quantity]").value = "";
          line.querySelector("[data-stockline]").textContent = "";
          lines.insertBefore(line, lines.querySelector("[data-add-line]"));
          enhanceSelect(line.querySelector("select"));
          syncLines();
          line.querySelector(".cselect__button")?.click();
        });
        lines.addEventListener("click", (event) => {
          const remove = event.target.closest("[data-remove-line]");
          if (!remove || form.querySelectorAll("[data-line]").length < 2) return;
          remove.closest("[data-line]").remove();
          syncLines();
        });
      }

      form.addEventListener("change", () => { syncType(); syncLines(); });
      syncType();
      syncLines();
    });
  }

  function initStocktake() {
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
  }

  function initDropzones() {
    document.querySelectorAll("[data-dropzone]").forEach((zone) => {
      const input = zone.querySelector("[data-file-input]");
      const label = zone.querySelector("[data-file-name]");
      input.addEventListener("change", () => { if (input.files[0]) label.textContent = input.files[0].name; });
      ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, () => zone.classList.add("is-over")));
      ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, () => zone.classList.remove("is-over")));
    });
  }

  // While the "open the bot" step is shown, ask the server every 3 s whether /start arrived.
  function initTelegram() {
    const telegram = document.querySelector("[data-telegram-check]");
    if (!telegram) return;
    let tries = 0;
    const poll = () => {
      if (!telegram.isConnected) return; // the user went to another page
      if (document.hidden) { setTimeout(poll, 3000); return; }
      fetch(telegram.dataset.telegramCheck, {
        method: "POST",
        headers: { Accept: "application/json", "X-CSRF-Token": csrf() },
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.linked) navigate(data.redirect, { replace: true });
          else if (++tries < 100) setTimeout(poll, 3000);
        })
        .catch(() => { if (++tries < 100) setTimeout(poll, 5000); });
    };
    setTimeout(poll, 3000);
  }

  // Supabase email links (reset password, change email) put the session in the URL hash.
  function initCallback() {
    const callback = document.getElementById("callback-status");
    if (!callback) return;
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
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
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

  // ================================================================ document-level, bound once

  // Dropdown menus close on outside click and Escape.
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.menu[open]").forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelectorAll("details.menu[open]").forEach((menu) => { menu.open = false; });
  });

  // ---------------------------------------------------------------- tooltips

  const tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  let tipTarget = null;

  function showTip(target, x, y) {
    if (!tip.isConnected) document.body.appendChild(tip);
    tipTarget = target;
    tip.textContent = target.dataset.tip;
    const rect = target.getBoundingClientRect();
    const left = x !== undefined ? x : rect.left + rect.width / 2;
    const top = y !== undefined ? y : rect.top;
    tip.style.left = Math.min(Math.max(left, 80), window.innerWidth - 80) + "px";
    tip.style.top = Math.max(top, 40) + "px";
    tip.classList.add("is-on");
  }
  function hideTip() {
    tipTarget = null;
    tip.classList.remove("is-on");
  }
  document.addEventListener("pointerover", (event) => {
    const target = event.target.closest?.("[data-tip]");
    if (target && target.dataset.tip) showTip(target);
  });
  document.addEventListener("pointermove", (event) => {
    if (tipTarget && tipTarget.closest(".chart, .donut, .abc__bar")) showTip(tipTarget, event.clientX, event.clientY - 6);
  });
  document.addEventListener("pointerout", (event) => {
    if (tipTarget && !tipTarget.contains(event.relatedTarget)) hideTip();
  });
  document.addEventListener("focusin", (event) => {
    const target = event.target.closest?.("[data-tip]");
    if (target) showTip(target);
  });
  document.addEventListener("focusout", hideTip);
  window.addEventListener("scroll", hideTip, { passive: true });

  // ================================================================ fast navigation

  const progress = document.createElement("div");
  progress.className = "navbar-progress";
  const PREFETCH_TTL = 15000;
  const cache = new Map(); // url → { at, promise }
  let navToken = 0;

  const sameOrigin = (url) => url.origin === window.location.origin;

  function eligibleLink(link) {
    if (!link || !link.href || link.target && link.target !== "_self" || link.hasAttribute("download")) return false;
    if (link.dataset.reload !== undefined) return false;
    const url = new URL(link.href, window.location.href);
    if (!sameOrigin(url)) return false;
    if (/\.(pdf|csv)$/i.test(url.pathname) || url.pathname.startsWith("/static/")) return false;
    // a hash on the same page is a scroll, not a navigation
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return false;
    return url;
  }

  // GET pages only. A prefetched page is used once, then dropped (it may carry flash messages).
  function load(url, options) {
    return fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" }, ...options })
      .then((response) => {
        const type = response.headers.get("Content-Type") || "";
        if (!type.includes("text/html")) throw new Error("not html");
        return response.text().then((html) => ({ html, url: response.url, redirected: response.redirected }));
      });
  }

  function prefetch(href) {
    const url = new URL(href, window.location.href);
    if (!sameOrigin(url)) return;
    const key = url.href;
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < PREFETCH_TTL) return;
    const promise = load(key);
    promise.catch(() => cache.delete(key));
    cache.set(key, { at: Date.now(), promise });
  }

  function takeCached(key) {
    const hit = cache.get(key);
    cache.delete(key);
    return hit && Date.now() - hit.at < PREFETCH_TTL ? hit.promise : null;
  }

  function startProgress() {
    if (!progress.isConnected) document.documentElement.appendChild(progress);
    progress.className = "navbar-progress";
    void progress.offsetWidth; // restart the transition
    progress.classList.add("is-loading");
  }
  function endProgress() {
    progress.classList.add("is-done");
  }

  function swap(html, url, { push = true, replace = false, scroll = true } = {}) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    closeOpenSelect();
    hideTip();
    document.title = doc.title;
    document.documentElement.lang = doc.documentElement.lang;
    if (doc.documentElement.dataset.theme) document.documentElement.dataset.theme = doc.documentElement.dataset.theme;
    const scheme = doc.querySelector('meta[name="color-scheme"]');
    const ownScheme = document.querySelector('meta[name="color-scheme"]');
    if (scheme && ownScheme) ownScheme.content = scheme.content;
    // keep <body> itself (and this script's references); copy its attributes and children
    Array.from(body.attributes).forEach((attr) => body.removeAttribute(attr.name));
    Array.from(doc.body.attributes).forEach((attr) => body.setAttribute(attr.name, attr.value));
    body.replaceChildren(...doc.body.childNodes);
    if (replace) history.replaceState({ scroll: 0 }, "", url);
    else if (push) history.pushState({ scroll: 0 }, "", url);
    const hash = new URL(url, window.location.href).hash;
    if (hash && document.querySelector(hash)) document.querySelector(hash).scrollIntoView();
    else if (scroll) window.scrollTo(0, 0);
    init();
  }

  function navigate(href, { replace = false, method = "GET", body: formBody = null } = {}) {
    const url = new URL(href, window.location.href);
    const token = ++navToken;
    // remember where we were, for the back button
    history.replaceState({ ...(history.state || {}), scroll: window.scrollY }, "");
    startProgress();
    const request = method === "GET"
      ? (takeCached(url.href) || load(url.href))
      : load(url.href, { method, body: formBody });
    return request
      .then(({ html, url: finalUrl, redirected }) => {
        if (token !== navToken) return; // a newer click won
        endProgress();
        // a POST that rendered a page (validation error) keeps the address it came from
        const keepAddress = method !== "GET" && !redirected;
        swap(html, keepAddress ? window.location.href : finalUrl, { push: !keepAddress && !replace, replace });
      })
      .catch(() => {
        if (token !== navToken) return;
        // anything unexpected: let the browser do a normal load
        if (method === "GET") window.location.href = url.href;
        else window.location.reload();
      });
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest("a");
    const url = eligibleLink(link);
    if (!url) return;
    event.preventDefault();
    navigate(url.href);
  });

  // Prefetch after a short hover (a pass-over does not count) and on touch start.
  let hoverTimer = null;
  document.addEventListener("pointerover", (event) => {
    const link = event.target.closest?.("a");
    const url = eligibleLink(link);
    if (!url || url.href === window.location.href) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => prefetch(url.href), 65);
  });
  document.addEventListener("pointerout", (event) => {
    if (event.target.closest?.("a")) clearTimeout(hoverTimer);
  });
  document.addEventListener("touchstart", (event) => {
    const url = eligibleLink(event.target.closest?.("a"));
    if (url) prefetch(url.href);
  }, { passive: true });

  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (form.dataset.reload !== undefined || (form.target && form.target !== "_self")) return;
    const submitter = event.submitter;
    const action = new URL(submitter?.getAttribute("formaction") || form.getAttribute("action") || window.location.href, window.location.href);
    if (!sameOrigin(action)) return;
    const method = (submitter?.getAttribute("formmethod") || form.method || "get").toUpperCase();
    const data = new FormData(form, submitter && submitter.form === form ? submitter : undefined);
    event.preventDefault();
    if (method === "GET") {
      const query = new URLSearchParams();
      data.forEach((value, key) => { if (typeof value === "string") query.append(key, value); });
      action.search = query.toString();
      navigate(action.href);
    } else {
      cache.clear(); // data changed; prefetched pages are stale
      navigate(action.href, { method, body: data });
    }
  });

  window.addEventListener("popstate", (event) => {
    const scroll = event.state?.scroll || 0;
    const token = ++navToken;
    startProgress();
    load(window.location.href)
      .then(({ html }) => {
        if (token !== navToken) return;
        endProgress();
        swap(html, window.location.href, { push: false, scroll: false });
        window.scrollTo(0, scroll);
      })
      .catch(() => window.location.reload());
  });

  if (!history.state) history.replaceState({ scroll: 0 }, "");
  init();
})();
