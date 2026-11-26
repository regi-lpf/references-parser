(function () {
  const ITEMS_PER_PAGE = 12;
  const HTML_ESCAPE_MAP = {
    "\u0026": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  };
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[\u0026<>"']/g, function (ch) {
      return HTML_ESCAPE_MAP[ch];
    });
  }
  function normalizeText(str) {
    return String(str || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }
  function safeUrl(url) {
    if (!url) return null;
    const trimmed = String(url).trim();
    if (/^https?:\/\//i.test(trimmed)) return trimmed;
    return null;
  }
  function isLocalEnvironment() {
    const host = (window.location && window.location.hostname) || "";
    const proto = (window.location && window.location.protocol) || "";
    return host === "localhost" || host === "127.0.0.1" || host === "::1" || proto === "file:";
  }
  function resolveDataUrl(rootEl) {
    const localUrl = rootEl.getAttribute("data-json-url-local");
    const prodUrl = rootEl.getAttribute("data-json-url");
    if (isLocalEnvironment() && localUrl) return localUrl;
    return prodUrl || localUrl || "";
  }
  function escapeCsvCell(val) {
    return "\"" + String(val == null ? "" : val).replace(/"/g, "\"\"") + "\"";
  }
  function initVitrine(rootEl) {
    if (!rootEl || rootEl.dataset.vbMounted === "1") return;
    rootEl.dataset.vbMounted = "1";
    const titleEl = rootEl.querySelector("#vb-title");
    const tabsEl = rootEl.querySelector("#vb-tabs");
    const catLabelEl = rootEl.querySelector("#vb-categoria-label");
    const searchEl = rootEl.querySelector("#vb-search");
    const catEl = rootEl.querySelector("#vb-filter-categoria");
    const anoEl = rootEl.querySelector("#vb-filter-ano");
    const onlyAvailEl = rootEl.querySelector("#vb-only-available");
    const clearEl = rootEl.querySelector("#vb-clear");
    const statsEl = rootEl.querySelector("#vb-stats");
    const gridEl = rootEl.querySelector("#vb-grid");
    const pagEl = rootEl.querySelector("#vb-pagination");
    const downloadJsonEl = rootEl.querySelector("#vb-download-json");
    const downloadCsvEl = rootEl.querySelector("#vb-download-csv");
    const liveEl = rootEl.querySelector("#vb-live-feedback");
    if (!gridEl || !statsEl || !searchEl || !catEl || !anoEl) return;
    let allData = [];
    let filteredData = [];
    let currentPage = 1;
    let debounceTimer = null;
    let rawPayload = null;
    function syncHeaderConfig() {
      const titulo = rootEl.getAttribute("data-titulo") || "Acervo Bibliográfico";
      const catLabel = rootEl.getAttribute("data-categoria-label") || "Categoria";
      if (titleEl) titleEl.textContent = titulo;
      if (catLabelEl) catLabelEl.textContent = catLabel;
      catEl.setAttribute("aria-label", "Filtrar por " + catLabel.toLowerCase());
      const jsonUrl = resolveDataUrl(rootEl);
      if (downloadJsonEl && jsonUrl) {
        downloadJsonEl.setAttribute("href", jsonUrl);
      }
      return jsonUrl;
    }
    function announce(msg) {
      if (liveEl) liveEl.textContent = msg;
    }
    function populateFilters(items) {
      const catLabel = rootEl.getAttribute("data-categoria-label") || "Categoria";
      catEl.innerHTML = "<option value=\"\">Todos (" + escapeHtml(catLabel) + ")</option>";
      const cats = Array.from(new Set(items.map(function (d) { return d.categoria; }).filter(Boolean))).sort();
      cats.forEach(function (c) {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        catEl.appendChild(opt);
      });
      anoEl.innerHTML = "<option value=\"\">Todos os anos</option>";
      const anos = Array.from(new Set(items.map(function (d) { return d.ano; }).filter(function (a) { return a != null; }))).sort(function (a, b) { return b - a; });
      anos.forEach(function (a) {
        const opt = document.createElement("option");
        opt.value = String(a);
        opt.textContent = String(a);
        anoEl.appendChild(opt);
      });
    }
    function renderCards(items) {
      if (!items.length) {
        gridEl.innerHTML = "<div class=\"vb-empty\"><p>Nenhuma referência encontrada para os filtros selecionados.</p><button type=\"button\" class=\"vb-btn\" data-vb-reset=\"1\">Limpar filtros</button></div>";
        return;
      }
      const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
      gridEl.innerHTML = items.map(function (item, idx) {
        const globalIdx = startIndex + idx;
        const pubHref = safeUrl(item.link_obra);
        const lattesHref = safeUrl(item.link_lattes);
        const pubAction = pubHref
          ? "<a href=\"" + escapeHtml(pubHref) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"vb-btn is-primary\">Acessar Texto</a>"
          : "<span class=\"vb-badge pending\">Texto Indisponível</span>";
        const lattesAction = lattesHref
          ? "<a href=\"" + escapeHtml(lattesHref) + "\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"vb-btn\">CV Lattes</a>"
          : "";
        const anoBadge = item.ano != null
          ? "<span class=\"vb-badge green\">" + escapeHtml(item.ano) + "</span>"
          : "<span class=\"vb-badge pending\">S/D</span>";
        const veiculoHtml = item.veiculo_ou_ies
          ? "<div><b>Fonte / Instituição:</b> " + escapeHtml(item.veiculo_ou_ies) + "</div>"
          : "";
        return "<article class=\"vb-card\">"
          + "<div class=\"vb-badges\">" + anoBadge + "<span class=\"vb-badge\">" + escapeHtml(item.categoria || "Publicação") + "</span></div>"
          + "<h3 class=\"vb-card-title\">" + escapeHtml(item.titulo || item.citacao_original) + "</h3>"
          + "<div class=\"vb-meta\">"
          + "<div><b>Autor(a):</b> " + escapeHtml(item.autor || "Não informado") + "</div>"
          + veiculoHtml
          + "</div>"
          + "<div class=\"vb-card-footer\">"
          + pubAction
          + "<div class=\"vb-card-actions\">"
          + "<button type=\"button\" class=\"vb-btn\" data-copy-idx=\"" + globalIdx + "\">Copiar citação</button>"
          + lattesAction
          + "</div>"
          + "</div>"
          + "</article>";
      }).join("");
    }
    function renderPagination(totalPages) {
      if (totalPages <= 1) {
        pagEl.innerHTML = "";
        return;
      }
      const parts = [];
      parts.push("<button type=\"button\" class=\"vb-page-btn\" data-page=\"" + (currentPage - 1) + "\" " + (currentPage === 1 ? "disabled" : "") + ">&laquo; Anterior</button>");
      const win = 2;
      for (let p = 1; p <= totalPages; p += 1) {
        if (p === 1 || p === totalPages || (p >= currentPage - win && p <= currentPage + win)) {
          parts.push("<button type=\"button\" class=\"vb-page-btn " + (p === currentPage ? "is-active" : "") + "\" data-page=\"" + p + "\" " + (p === currentPage ? "aria-current=\"page\"" : "") + ">" + p + "</button>");
        } else if (p === currentPage - win - 1 || p === currentPage + win + 1) {
          parts.push("<span class=\"vb-pagination-ellipsis\">...</span>");
        }
      }
      parts.push("<button type=\"button\" class=\"vb-page-btn\" data-page=\"" + (currentPage + 1) + "\" " + (currentPage === totalPages ? "disabled" : "") + ">Próxima &raquo;</button>");
      pagEl.innerHTML = parts.join("");
    }
    function render() {
      const total = filteredData.length;
      const totalPages = Math.ceil(total / ITEMS_PER_PAGE);
      if (currentPage > totalPages && totalPages > 0) currentPage = 1;
      const start = (currentPage - 1) * ITEMS_PER_PAGE;
      const slice = filteredData.slice(start, start + ITEMS_PER_PAGE);
      statsEl.innerHTML = "Exibindo <strong>" + slice.length + "</strong> de <strong>" + total + "</strong> referências encontradas.";
      renderCards(slice);
      renderPagination(totalPages);
    }
    function applyFilters() {
      const q = normalizeText(searchEl.value);
      const cat = catEl.value;
      const ano = anoEl.value;
      const onlyAvail = onlyAvailEl ? onlyAvailEl.checked : false;
      filteredData = allData.filter(function (item) {
        if (cat && item.categoria !== cat) return false;
        if (ano && String(item.ano) !== ano) return false;
        if (onlyAvail && !safeUrl(item.link_obra)) return false;
        if (q) {
          const hay = item.texto_busca || normalizeText((item.titulo || "") + " " + (item.autor || "") + " " + (item.veiculo_ou_ies || "") + " " + (item.citacao_original || ""));
          if (!hay.includes(q)) return false;
        }
        return true;
      });
      currentPage = 1;
      render();
    }
    function resetFilters() {
      searchEl.value = "";
      catEl.value = "";
      anoEl.value = "";
      if (onlyAvailEl) onlyAvailEl.checked = false;
      applyFilters();
    }
    function loadData() {
      const url = syncHeaderConfig();
      if (!url) {
        statsEl.textContent = "URL da base bibliográfica não configurada.";
        gridEl.innerHTML = "<div class=\"vb-empty\"><p>Configure o atributo data-json-url no container.</p></div>";
        return;
      }
      statsEl.textContent = "Carregando acervo...";
      fetch(url)
        .then(function (resp) {
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          return resp.json();
        })
        .then(function (payload) {
          rawPayload = payload;
          const list = Array.isArray(payload) ? payload : (payload && Array.isArray(payload.registros) ? payload.registros : []);
          if (!rootEl.getAttribute("data-titulo") && payload && payload.titulo && titleEl) {
            titleEl.textContent = payload.titulo;
          }
          allData = list.slice().sort(function (a, b) {
            return (b.ano || 0) - (a.ano || 0) || String(a.titulo || "").localeCompare(String(b.titulo || ""));
          });
          filteredData = allData.slice();
          populateFilters(allData);
          render();
        })
        .catch(function (err) {
          console.error(err);
          statsEl.textContent = "Não foi possível carregar a base de referências.";
          gridEl.innerHTML = "<div class=\"vb-empty\"><p>Falha de rede ao carregar o acervo. Tente novamente em instantes.</p><button type=\"button\" class=\"vb-btn\" data-vb-retry=\"1\">Tentar novamente</button></div>";
        });
    }
    searchEl.addEventListener("input", function () {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(applyFilters, 180);
    });
    catEl.addEventListener("change", applyFilters);
    anoEl.addEventListener("change", applyFilters);
    if (onlyAvailEl) onlyAvailEl.addEventListener("change", applyFilters);
    if (clearEl) clearEl.addEventListener("click", resetFilters);
    if (pagEl) {
      pagEl.addEventListener("click", function (e) {
        const btn = e.target.closest("button[data-page]");
        if (!btn || btn.disabled) return;
        currentPage = Number(btn.getAttribute("data-page")) || 1;
        render();
        rootEl.scrollIntoView({ behavior: "smooth" });
      });
    }
    gridEl.addEventListener("click", function (e) {
      const resetBtn = e.target.closest("button[data-vb-reset]");
      if (resetBtn) {
        resetFilters();
        return;
      }
      const retryBtn = e.target.closest("button[data-vb-retry]");
      if (retryBtn) {
        loadData();
        return;
      }
      const copyBtn = e.target.closest("button[data-copy-idx]");
      if (!copyBtn) return;
      const item = filteredData[Number(copyBtn.getAttribute("data-copy-idx"))];
      if (!item) return;
      const citacao = item.citacao_original || (String(item.autor || "") + ". " + String(item.titulo || "") + ".");
      const markCopied = function () {
        const orig = copyBtn.textContent;
        copyBtn.textContent = "Copiado!";
        copyBtn.classList.add("is-copied");
        announce("Citação copiada para a área de transferência.");
        window.setTimeout(function () {
          copyBtn.textContent = orig;
          copyBtn.classList.remove("is-copied");
        }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(citacao).then(markCopied).catch(function () {
          markCopied();
        });
      } else {
        markCopied();
      }
    });
    if (downloadJsonEl) {
      downloadJsonEl.addEventListener("click", function (e) {
        if (!rawPayload) return;
        e.preventDefault();
        const blob = new Blob([JSON.stringify(rawPayload, null, 2)], { type: "application/json;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = (rawPayload.lista_id || "vitrine-bibliografica") + ".json";
        a.click();
        URL.revokeObjectURL(url);
      });
    }
    if (downloadCsvEl) {
      downloadCsvEl.addEventListener("click", function () {
        if (!filteredData.length) return;
        const headers = ["id", "autor", "titulo", "ano", "categoria", "veiculo_ou_ies", "link_obra", "link_lattes"];
        const rows = [headers.join(";")].concat(
          filteredData.map(function (r) {
            return headers.map(function (h) { return escapeCsvCell(r[h]); }).join(";");
          })
        );
        const blob = new Blob(["\uFEFF" + rows.join("\n")], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "referencias-" + filteredData.length + ".csv";
        a.click();
        URL.revokeObjectURL(url);
      });
    }
    rootEl.__vbReload = function () {
      allData = [];
      filteredData = [];
      currentPage = 1;
      loadData();
    };
    if (tabsEl) {
      if (rootEl.getAttribute("data-mostrar-seletor") === "false") {
        tabsEl.hidden = true;
      } else {
        tabsEl.hidden = false;
        tabsEl.addEventListener("click", function (e) {
          const btn = e.target.closest("button[data-vb-lista]");
          if (!btn) return;
          tabsEl.querySelectorAll("button[data-vb-lista]").forEach(function (b) {
            b.setAttribute("aria-pressed", b === btn ? "true" : "false");
          });
          ["data-json-url", "data-json-url-local", "data-titulo", "data-categoria-label"].forEach(function (attr) {
            const val = btn.getAttribute(attr);
            if (val) rootEl.setAttribute(attr, val);
          });
          searchEl.value = "";
          catEl.value = "";
          anoEl.value = "";
          if (onlyAvailEl) onlyAvailEl.checked = false;
          rootEl.__vbReload();
        });
      }
    }
    loadData();
  }
  const container = document.getElementById("vitrine-bib");
  if (container) {
    initVitrine(container);
  }
})();
