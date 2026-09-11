/* =========================================================================
   Brillante - JS de la tienda
   El estado real vive en el servidor: este archivo solo dispara peticiones y
   refleja la respuesta (totales, contador del carrito, mensajes).
   ========================================================================= */
(function () {
  "use strict";

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  const money = (value) =>
    "$ " +
    Number(value || 0)
      .toFixed(2)
      .replace(".", ",")
      .replace(/\B(?=(\d{3})+(?!\d)(?=,))/g, ".");

  /* ------------------------------------------------------------ toasts -- */
  const toastHost = $("#toasts");

  function toast(message, type = "success") {
    if (!toastHost || !message) return;
    const icons = { success: "✓", error: "!", info: "i" };
    const el = document.createElement("div");
    el.className = `toast toast--${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.innerHTML =
      `<span class="toast__icon">${icons[type] || "✓"}</span><span class="toast__text"></span>` +
      `<button class="toast__close" aria-label="Cerrar">×</button>`;
    $(".toast__text", el).textContent = message;
    toastHost.appendChild(el);

    const dismiss = () => {
      el.classList.add("is-out");
      setTimeout(() => el.remove(), 250);
    };
    $(".toast__close", el).addEventListener("click", dismiss);
    setTimeout(dismiss, 4200);
  }
  window.brillanteToast = toast;

  // Mensajes flash entregados por el servidor
  $$("#flash-data [data-flash]").forEach((node) =>
    toast(node.dataset.message, node.dataset.category)
  );

  /* ------------------------------------------------- contador del carrito -- */
  function paintCart(summary) {
    if (!summary) return;
    const badge = $("#cart-count");
    if (badge) {
      badge.textContent = summary.units;
      badge.hidden = summary.units === 0;
      badge.classList.remove("is-bump");
      void badge.offsetWidth; // fuerza reinicio de la animacion
      badge.classList.add("is-bump");
    }
    const total = $("#cart-total-label");
    if (total) total.textContent = money(summary.products_total);
  }

  async function postCart(url, data) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: data,
      credentials: "same-origin",
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (err) {
      payload = { ok: false, message: "No pudimos procesar la operacion." };
    }
    return payload;
  }

  /* ------------------------------------------- agregar al carrito (AJAX) -- */
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-cart-add]");
    if (!form) return;
    event.preventDefault();

    const button = $("button[type=submit]", form);
    const originalText = button ? button.innerHTML : "";
    if (button) {
      button.disabled = true;
      button.innerHTML = "Agregando…";
    }

    const payload = await postCart(form.action, new FormData(form));
    if (button) {
      button.disabled = false;
      button.innerHTML = originalText;
    }

    paintCart(payload.summary);
    toast(payload.message, payload.ok ? "success" : "error");
  });

  /* ------------------------------------------- pagina del carrito (AJAX) -- */
  const cartPage = $("#cart-page");
  if (cartPage) {
    const refresh = () => window.location.reload();

    cartPage.addEventListener("click", async (event) => {
      const stepper = event.target.closest("[data-qty-step]");
      if (stepper) {
        const wrap = stepper.closest("[data-cart-line]");
        const input = $("input[name=quantity]", wrap);
        const next = Number(input.value) + Number(stepper.dataset.qtyStep);
        const max = Number(input.max || 99);
        if (next < 1 || next > max) {
          if (next > max) toast(`Solo hay ${max} unidades disponibles.`, "error");
          return;
        }
        input.value = next;
        await updateLine(wrap, next);
        return;
      }

      const removeBtn = event.target.closest("[data-cart-remove]");
      if (removeBtn) {
        event.preventDefault();
        const wrap = removeBtn.closest("[data-cart-line]");
        wrap.classList.add("is-loading");
        const payload = await postCart(removeBtn.dataset.cartRemove, new FormData());
        paintCart(payload.summary);
        toast(payload.message, payload.ok ? "info" : "error");
        refresh();
      }
    });

    cartPage.addEventListener("change", async (event) => {
      const input = event.target.closest("input[name=quantity]");
      if (!input) return;
      const wrap = input.closest("[data-cart-line]");
      await updateLine(wrap, input.value);
    });

    async function updateLine(wrap, quantity) {
      wrap.classList.add("is-loading");
      const data = new FormData();
      data.append("quantity", quantity);
      const payload = await postCart(wrap.dataset.cartLine, data);
      paintCart(payload.summary);
      if (!payload.ok) toast(payload.message, "error");
      refresh();
    }
  }

  /* ----------------------------------------------------- selector cantidad -- */
  $$("[data-qty]").forEach((widget) => {
    const input = $("input", widget);
    const max = Number(input.max || 99);
    const sync = () => {
      let value = parseInt(input.value, 10);
      if (isNaN(value) || value < 1) value = 1;
      if (value > max) {
        value = max;
        toast(`Solo hay ${max} unidades disponibles.`, "info");
      }
      input.value = value;
      $$("button", widget).forEach((btn) => {
        const step = Number(btn.dataset.step);
        btn.disabled = (step < 0 && value <= 1) || (step > 0 && value >= max);
      });
    };
    $$("button", widget).forEach((btn) =>
      btn.addEventListener("click", () => {
        input.value = Number(input.value) + Number(btn.dataset.step);
        sync();
      })
    );
    input.addEventListener("change", sync);
    sync();
  });

  /* ------------------------------------------------ sugerencias de busqueda -- */
  const searchForm = $("#search-form");
  if (searchForm) {
    const input = $("#search-input", searchForm);
    const box = $("#suggestions");
    let timer = null;
    let lastTerm = "";

    const hide = () => {
      box.hidden = true;
      box.innerHTML = "";
    };

    const render = (data) => {
      if (!data.products.length && !data.categories.length) {
        hide();
        return;
      }
      let html = "";
      if (data.categories.length) {
        html += '<div class="suggestions__group"><div class="suggestions__title">Categorías</div>';
        data.categories.forEach((c) => {
          html += `<a class="suggestion" href="${c.url}"><span class="suggestion__name">${escapeHtml(
            c.name
          )}</span></a>`;
        });
        html += "</div>";
      }
      if (data.products.length) {
        html += '<div class="suggestions__group"><div class="suggestions__title">Productos</div>';
        data.products.forEach((p) => {
          html +=
            `<a class="suggestion" href="${p.url}">` +
            `<img src="/static/${p.image}" alt="" loading="lazy">` +
            `<span><span class="suggestion__name">${escapeHtml(p.name)}</span>` +
            `<span class="suggestion__meta">${escapeHtml(p.brand)}</span></span>` +
            `<span class="suggestion__price">${money(p.price)}</span></a>`;
        });
        html += "</div>";
      }
      box.innerHTML = html;
      box.hidden = false;
    };

    input.addEventListener("input", () => {
      const term = input.value.trim();
      clearTimeout(timer);
      if (term.length < 2) {
        hide();
        return;
      }
      timer = setTimeout(async () => {
        if (term === lastTerm) return;
        lastTerm = term;
        try {
          const response = await fetch(`/api/sugerencias?q=${encodeURIComponent(term)}`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          render(await response.json());
        } catch (err) {
          hide();
        }
      }, 220);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hide();
    });
    document.addEventListener("click", (event) => {
      if (!searchForm.contains(event.target)) hide();
    });
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /* ------------------------------------------------------- menu de usuario -- */
  const userMenu = $("#user-menu");
  if (userMenu) {
    const trigger = $("[data-menu-trigger]", userMenu);
    const panel = $("[data-menu-panel]", userMenu);
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      panel.hidden = !panel.hidden;
      trigger.setAttribute("aria-expanded", String(!panel.hidden));
    });
    document.addEventListener("click", (event) => {
      if (!userMenu.contains(event.target)) {
        panel.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") panel.hidden = true;
    });
  }

  /* ------------------------------------------------------- filtros mobile -- */
  const filters = $("#filters");
  const filtersBackdrop = $("#filters-backdrop");
  if (filters) {
    const open = () => {
      filters.classList.add("is-open");
      if (filtersBackdrop) filtersBackdrop.hidden = false;
      document.body.style.overflow = "hidden";
    };
    const close = () => {
      filters.classList.remove("is-open");
      if (filtersBackdrop) filtersBackdrop.hidden = true;
      document.body.style.overflow = "";
    };
    $$("[data-filters-open]").forEach((btn) => btn.addEventListener("click", open));
    $$("[data-filters-close]").forEach((btn) => btn.addEventListener("click", close));
    if (filtersBackdrop) filtersBackdrop.addEventListener("click", close);
  }

  // Enviar el formulario de filtros al tocar un checkbox o cambiar el orden
  $$("[data-autosubmit]").forEach((element) =>
    element.addEventListener("change", () => element.closest("form").submit())
  );

  /* -------------------------------------------------------- volver arriba -- */
  const toTop = $("#to-top");
  if (toTop) {
    const onScroll = () => toTop.classList.toggle("is-visible", window.scrollY > 600);
    window.addEventListener("scroll", onScroll, { passive: true });
    toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
    onScroll();
  }

  /* ----------------------------- fallback si una imagen no puede cargarse -- */
  document.addEventListener(
    "error",
    (event) => {
      const img = event.target;
      if (img.tagName !== "IMG" || img.dataset.fallbackApplied) return;
      img.dataset.fallbackApplied = "1";
      img.src = "/static/images/placeholder.svg";
    },
    true
  );

  /* ------------------------------------- confirmacion en acciones sensibles -- */
  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
  });
})();
