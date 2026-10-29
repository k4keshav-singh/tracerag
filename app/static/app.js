/* TraceRAG frontend.
 *
 * SECURITY: every piece of document-derived text reaches the DOM through esc()
 * before it is placed in an innerHTML template, or through textContent. The
 * corpus is user-supplied data and is treated as untrusted throughout. esc() is
 * the single sink; if you add a new template, run values through it.
 */

(function () {
  "use strict";

  var state = {
    status: null,
    chunkCache: {},
    reduceMotion:
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };

  // ------------------------------------------------------------------ utils

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function el(id) { return document.getElementById(id); }
  function show(node, visible) { if (node) node.hidden = !visible; }

  function note(node, kind, message) {
    node.className = "note " + kind;
    node.textContent = message;
    show(node, true);
  }

  function skeleton(node, rows) {
    var html = "";
    for (var i = 0; i < (rows || 3); i++) {
      var w = i % 3 === 0 ? "" : i % 3 === 1 ? " w70" : " w45";
      html += '<div class="skeleton' + w + '"></div>';
    }
    node.innerHTML = html;
  }

  function emptyState(node, message) {
    node.innerHTML =
      '<div class="empty">' +
      '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.6">' +
      '<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21" stroke-linecap="round"/></svg>' +
      "<div>" + esc(message) + "</div></div>";
  }

  function toast(kind, message) {
    var stack = el("toasts");
    var node = document.createElement("div");
    node.className = "toast " + kind;
    node.textContent = message;
    stack.appendChild(node);
    setTimeout(function () {
      node.classList.add("is-out");
      setTimeout(function () { node.remove(); }, 320);
    }, 4200);
  }

  async function api(path, options) {
    var response = await fetch(path, options);
    var body = null;
    try { body = await response.json(); } catch (err) { body = null; }
    if (!response.ok) {
      var message =
        (body && (body.error || body.detail)) ||
        "Request failed with HTTP " + response.status + ".";
      if (typeof message !== "string") message = JSON.stringify(message);
      throw new Error(message);
    }
    return body;
  }

  function fmtBytes(bytes) {
    if (!bytes) return "1 MB";
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(0) + " MB";
    return (bytes / 1024).toFixed(0) + " KB";
  }

  function statusBadge(status) {
    if (!status) return '<span class="badge neutral">no status</span>';
    var cls = status === "current" ? "current"
            : status === "superseded" ? "superseded" : "neutral";
    return '<span class="badge ' + cls + '">' + esc(status) + "</span>";
  }

  // ------------------------------------------------------------ motion bits

  /* Count a number up. Purely decorative, so it snaps when motion is reduced. */
  function countTo(node, target) {
    target = Number(target) || 0;
    if (state.reduceMotion) { node.textContent = String(target); return; }
    var start = performance.now();
    var from = Number(node.textContent.replace(/\D/g, "")) || 0;
    var duration = 820;
    function step(now) {
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      node.textContent = String(Math.round(from + (target - from) * eased));
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  var revealObserver = null;
  function initReveal() {
    if (!("IntersectionObserver" in window) || state.reduceMotion) {
      document.querySelectorAll("[data-reveal]").forEach(function (n) {
        n.classList.add("is-in");
      });
      return;
    }
    revealObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
    );
    document.querySelectorAll("[data-reveal]").forEach(function (n) {
      revealObserver.observe(n);
    });
  }

  function observeReveal(node) {
    if (!node) return;
    if (revealObserver) { node.setAttribute("data-reveal", ""); revealObserver.observe(node); }
    else node.classList.add("is-in");
  }

  /* Stagger entry of freshly rendered list items. */
  function stagger(nodes, stepMs) {
    if (state.reduceMotion) return;
    Array.prototype.forEach.call(nodes, function (node, index) {
      node.style.animationDelay = Math.min(index * (stepMs || 45), 420) + "ms";
    });
  }

  function initScrollChrome() {
    var nav = el("nav");
    var bar = el("scroll-bar");
    var ticking = false;
    function update() {
      var y = window.scrollY || 0;
      nav.classList.toggle("is-stuck", y > 12);
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (max > 0 ? (y / max) * 100 : 0) + "%";
      ticking = false;
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* Grow the question field to fit its content.
   *
   * The empty field is sized by CSS alone (rows=1 plus min-height). Measuring
   * scrollHeight at load proved unreliable - it reads a stale or pre-layout
   * value and the field opened at its maximum height - so this runs only in
   * response to content changing, and clears the inline height when the field
   * is empty so CSS takes over again. Scripting only what CSS cannot do makes
   * the load path deterministic.
   *
   * The reset to "auto" before reading scrollHeight is required: otherwise the
   * previous explicit height is what gets measured, and the field could only
   * ever grow. */
  var MAX_QUESTION_HEIGHT = 200;

  function autoGrow(textarea) {
    if (!textarea.value) {
      textarea.style.height = "";
      textarea.style.overflowY = "hidden";
      return;
    }
    textarea.style.height = "auto";
    var content = textarea.scrollHeight;
    textarea.style.height = Math.min(content, MAX_QUESTION_HEIGHT) + "px";
    textarea.style.overflowY = content > MAX_QUESTION_HEIGHT ? "auto" : "hidden";
  }

  // ---------------------------------------------------------------- theming

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("tracerag-theme", theme); } catch (err) { /* private mode */ }
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("tracerag-theme"); } catch (err) { /* ignore */ }
    if (!saved) {
      saved = window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    applyTheme(saved);
    el("theme-toggle").addEventListener("click", function () {
      var next =
        document.documentElement.getAttribute("data-theme") === "dark"
          ? "light" : "dark";
      applyTheme(next);
    });
  }

  // ----------------------------------------------------------------- status

  async function loadStatus() {
    try {
      var status = await api("/api/status");
      state.status = status;

      countTo(el("stat-docs"), status.document_count);
      countTo(el("stat-chunks"), status.chunk_count);

      el("stat-methods").innerHTML = status.methods
        .map(function (m) {
          return m.available
            ? '<span class="badge on">' + esc(m.name) + "</span>"
            : '<span class="badge off" title="' + esc(m.reason || "unavailable") +
              '">' + esc(m.name) + "</span>";
        })
        .join("");

      el("stat-modes").innerHTML = status.llm_configured
        ? '<span class="badge on">extractive</span><span class="badge on">llm</span>'
        : '<span class="badge on">extractive</span><span class="badge neutral">llm off</span>';

      el("pill-corpus").className = "pill";
      el("pill-corpus").innerHTML =
        '<i class="dot dot-live"></i>' +
        esc(status.document_count) + " docs &middot; " +
        esc(status.chunk_count) + " chunks";

      el("max-size").textContent = fmtBytes(status.max_upload_bytes);

      // Method selector, disabling anything the server reports as unavailable.
      var methodSelect = el("method");
      methodSelect.innerHTML = status.methods
        .map(function (m) {
          var label = m.name.charAt(0).toUpperCase() + m.name.slice(1);
          if (!m.available) label += " — unavailable";
          return '<option value="' + esc(m.name) + '"' +
            (m.available ? "" : " disabled") + ">" + esc(label) + "</option>";
        })
        .join("");
      var preferred = status.methods.filter(function (m) {
        return m.available && m.name === "hybrid";
      })[0];
      var firstOk = status.methods.filter(function (m) { return m.available; })[0];
      methodSelect.value = (preferred || firstOk || {}).name || "";

      var llmOption = el("mode").querySelector('option[value="llm"]');
      if (llmOption) {
        llmOption.disabled = !status.llm_configured;
        llmOption.textContent = status.llm_configured
          ? "LLM — " + (status.llm_model || "configured")
          : "LLM — not configured on this server";
      }

      var unavailable = status.methods.filter(function (m) { return !m.available; });
      if (unavailable.length) {
        note(el("corpus-status"), "warn",
          unavailable.map(function (m) {
            return m.name + ": " + (m.reason || "unavailable");
          }).join(" | "));
      }
    } catch (err) {
      el("pill-corpus").className = "pill pill-muted";
      el("pill-corpus").textContent = "server unavailable";
      toast("error", err.message);
    }
  }

  // --------------------------------------------------------------- examples

  async function loadExamples() {
    try {
      var data = await api("/api/examples");
      var container = el("examples");
      container.innerHTML = "";
      data.examples.forEach(function (example) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "chip";
        button.title = example.note;
        button.innerHTML =
          '<span class="chip-tag">' + esc(example.label) + "</span>" +
          "<span>" + esc(example.question) + "</span>";
        button.addEventListener("click", function () {
          var field = el("question");
          field.value = example.question;
          autoGrow(field);
          field.focus();
        });
        container.appendChild(button);
      });
    } catch (err) {
      el("examples").textContent = "";
    }
  }

  // -------------------------------------------------------------- documents

  async function loadDocuments() {
    var container = el("documents");
    skeleton(container, 5);
    try {
      var documents = await api("/api/documents");
      if (!documents.length) {
        emptyState(container, "No documents yet — use Load corpus.");
        return;
      }
      container.innerHTML = documents
        .map(function (doc) {
          var meta = [];
          if (doc.version) meta.push("v" + esc(doc.version));
          meta.push(esc(doc.chunk_count) + " chunks");
          if (doc.superseded_by) meta.push("replaced by " + esc(doc.superseded_by));
          return (
            '<div class="doc">' +
            '<span class="doc-title">' + esc(doc.title) + "</span>" +
            '<span class="doc-id">' + esc(doc.doc_id) + "</span>" +
            statusBadge(doc.status) +
            '<span class="doc-meta">' + meta.join(" &middot; ") + "</span>" +
            "</div>"
          );
        })
        .join("");
      stagger(container.querySelectorAll(".doc"), 28);
    } catch (err) {
      container.innerHTML = '<div class="note error">' + esc(err.message) + "</div>";
    }
  }

  // --------------------------------------------------------------- answering

  /* Escape first, then upgrade bracketed IDs that are genuine citations into
     buttons. The character class and the allow-list both keep this safe. */
  function renderAnswerText(text, citations) {
    var escaped = esc(text);
    var known = {};
    (citations || []).forEach(function (id) { known[esc(id)] = true; });
    return escaped.replace(/\[([A-Za-z0-9._:-]+)\]/g, function (match, id) {
      if (!known[id]) return match;
      return '<button type="button" class="cite" data-chunk="' + id + '">' + id + "</button>";
    });
  }

  function renderAbstention(abstention) {
    var terms = (abstention.query_terms || [])
      .map(function (term) {
        var hit = (abstention.matched_terms || []).indexOf(term) !== -1;
        return '<span class="term ' + (hit ? "hit" : "miss") + '">' + esc(term) + "</span>";
      })
      .join("");

    return (
      '<details class="diag"><summary>Why this was or was not answered</summary>' +
      '<div class="diag-body">' +
      "<p>" + esc(abstention.reason) + "</p>" +
      "<p>" + terms + "</p>" +
      "<p>" + esc(abstention.heuristic) + "</p>" +
      "</div></details>"
    );
  }

  function bannerIcon(kind) {
    if (kind === "abstain") {
      return '<svg class="banner-ico" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8">' +
        '<circle cx="10" cy="10" r="7.4"/><path d="M10 6.2v4.4" stroke-linecap="round"/>' +
        '<circle cx="10" cy="13.7" r=".9" fill="currentColor" stroke="none"/></svg>';
    }
    return '<svg class="banner-ico" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8">' +
      '<path d="M4 10.6l3.7 3.6L16 6.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  function renderAnswer(result) {
    var panel = el("answer-panel");
    var body = el("answer-body");
    show(panel, true);

    var kind = result.insufficient_evidence ? "abstain"
             : result.mode === "llm" ? "llm" : "extractive";

    el("answer-tag").textContent = result.insufficient_evidence
      ? "declined" : result.mode;

    var bannerText = result.insufficient_evidence
      ? "Insufficient evidence — TraceRAG declined to answer. " + result.mode_label
      : result.mode_label;

    var html =
      '<div class="mode-banner ' + kind + '">' + bannerIcon(kind) +
      "<span>" + esc(bannerText) + "</span></div>";

    (result.warnings || []).forEach(function (warning) {
      html += '<div class="note warn">' + esc(warning) + "</div>";
    });
    if (result.provider_error) {
      html += '<div class="note error">Provider error: ' + esc(result.provider_error) + "</div>";
    }
    if ((result.rejected_citations || []).length) {
      html += '<div class="note error">Rejected invalid citation IDs: ' +
        esc(result.rejected_citations.join(", ")) + "</div>";
    }

    html += '<p class="answer-text">' +
      renderAnswerText(result.answer, result.citations) + "</p>";

    if ((result.citations || []).length) {
      html += '<div class="meta-row"><span><b>Citations</b></span> ' +
        result.citations.map(function (id) {
          return '<button type="button" class="cite" data-chunk="' + esc(id) + '">' +
            esc(id) + "</button>";
        }).join(" ") + "</div>";
    }

    var coverage = Number(result.abstention.coverage) || 0;
    var threshold = Number(result.abstention.threshold) || 0;

    html +=
      '<div class="meta-row">' +
      "<span><b>Method:</b> " + esc(result.retrieval.method) + "</span>" +
      "<span><b>Retrieval:</b> " + esc(result.retrieval.elapsed_ms) + " ms</span>" +
      "<span><b>Passages:</b> " + esc(result.retrieval.chunks.length) + "</span>" +
      '<span><b>Coverage:</b> ' + esc(coverage.toFixed(2)) + "</span>" +
      '<span class="meter' + (result.insufficient_evidence ? " is-low" : "") +
        '" title="term coverage against the abstention threshold">' +
        '<i data-width="' + esc((coverage * 100).toFixed(1)) + '"></i>' +
        '<span class="meter-mark" style="left:' + esc((threshold * 100).toFixed(1)) + '%"></span>' +
      "</span>" +
      (result.llm_model ? "<span><b>Model:</b> " + esc(result.llm_model) + "</span>" : "") +
      "</div>";

    html += renderAbstention(result.abstention);

    body.innerHTML = html;

    // Animate the coverage meter after layout so the transition runs.
    requestAnimationFrame(function () {
      var fill = body.querySelector(".meter i");
      if (fill) fill.style.width = fill.getAttribute("data-width") + "%";
    });

    renderChunks(result.retrieval);
  }

  function renderChunks(retrieval) {
    var panel = el("chunks-panel");
    var body = el("chunks-body");
    show(panel, true);

    el("score-semantics").textContent = retrieval.score_semantics;
    el("chunks-count").textContent =
      retrieval.chunks.length + " · " + retrieval.method;

    if (!retrieval.chunks.length) {
      emptyState(body, "No passages were retrieved for this query.");
      return;
    }

    // Scores are only comparable within one query and one method, so the bar is
    // scaled against this result set's own maximum and never across methods.
    var scores = retrieval.chunks.map(function (c) { return Number(c.score) || 0; });
    var max = Math.max.apply(null, scores);
    var min = Math.min.apply(null, scores);
    var span = max - min || 1;

    body.innerHTML = retrieval.chunks
      .map(function (chunk) {
        var relative = ((Number(chunk.score) - min) / span) * 82 + 18;
        var source =
          esc(chunk.filename) +
          " lines " + Number(chunk.start_line) + "–" + Number(chunk.end_line) +
          (chunk.heading ? " &middot; " + esc(chunk.heading) : "");
        return (
          '<div class="chunk">' +
          '<div class="chunk-head">' +
          '<span class="chunk-rank">' + Number(chunk.rank) + "</span>" +
          '<span class="chunk-title">' + esc(chunk.doc_title) + "</span>" +
          statusBadge(chunk.doc_status) +
          '<span class="chunk-id">' + esc(chunk.chunk_id) + "</span>" +
          '<span class="chunk-score">' +
            '<span class="score-bar"><i data-width="' + esc(relative.toFixed(1)) + '"></i></span>' +
            esc(chunk.score) +
          "</span>" +
          "</div>" +
          '<div class="chunk-source">' + source + "</div>" +
          '<div class="chunk-text">' + esc(chunk.text) + "</div>" +
          '<button type="button" class="chunk-toggle">Show full passage</button>' +
          "</div>"
        );
      })
      .join("");

    stagger(body.querySelectorAll(".chunk"), 50);

    requestAnimationFrame(function () {
      body.querySelectorAll(".score-bar i").forEach(function (fill) {
        fill.style.width = fill.getAttribute("data-width") + "%";
      });
    });

    body.querySelectorAll(".chunk-toggle").forEach(function (button) {
      button.addEventListener("click", function () {
        var text = button.previousElementSibling;
        var expanded = text.classList.toggle("expanded");
        button.textContent = expanded ? "Collapse passage" : "Show full passage";
      });
    });
  }

  // ----------------------------------------------------------------- dialog

  async function openChunk(chunkId, sourceButton) {
    if (sourceButton) {
      sourceButton.classList.add("is-hit");
      setTimeout(function () { sourceButton.classList.remove("is-hit"); }, 460);
    }

    var dialog = el("chunk-dialog");
    var body = el("dialog-body");
    show(dialog, true);
    el("dialog-title").textContent = chunkId;
    skeleton(body, 4);

    try {
      var chunk = state.chunkCache[chunkId];
      if (!chunk) {
        chunk = await api("/api/chunks/" + encodeURIComponent(chunkId));
        state.chunkCache[chunkId] = chunk;
      }
      body.innerHTML =
        '<div class="meta-row" style="border-top:0;padding-top:0;margin-bottom:13px">' +
        "<span><b>Document:</b> " + esc(chunk.doc_title || chunk.doc_id) + "</span>" +
        "<span><b>File:</b> " + esc(chunk.filename || "—") + "</span>" +
        "<span><b>Lines:</b> " + Number(chunk.start_line) + "–" + Number(chunk.end_line) + "</span>" +
        (chunk.heading ? "<span><b>Section:</b> " + esc(chunk.heading) + "</span>" : "") +
        "</div>" +
        '<div class="dialog-text">' + esc(chunk.text) + "</div>";
    } catch (err) {
      body.innerHTML = '<div class="note error">' + esc(err.message) + "</div>";
    }
  }

  function closeDialog() { show(el("chunk-dialog"), false); }

  // -------------------------------------------------------------- benchmark

  function metric(value, digits) {
    if (value === null || value === undefined) return "—";
    return Number(value).toFixed(digits === undefined ? 3 : digits);
  }

  async function loadBenchmark() {
    var container = el("benchmark-body");
    skeleton(container, 4);
    try {
      var payload = await api("/api/benchmark");
      if (!payload.available) {
        emptyState(container, payload.message || "No benchmark available.");
        return;
      }
      var report = payload.report;
      var names = Object.keys(report.methods || {});

      // Highlight the best available value per column, so the table is readable
      // at a glance without implying the differences are significant.
      var best = {};
      ["doc_recall_at_5", "mrr_at_10"].forEach(function (key) {
        var values = names
          .filter(function (n) { return report.methods[n].available; })
          .map(function (n) { return report.methods[n][key]; })
          .filter(function (v) { return typeof v === "number"; });
        if (values.length) best[key] = Math.max.apply(null, values);
      });

      var rows = names.map(function (name) {
        var m = report.methods[name];
        if (!m.available) {
          return "<tr><td>" + esc(name) +
            '</td><td colspan="5" class="unavailable">' +
            esc(m.reason || "unavailable") + "</td></tr>";
        }
        function cell(key, digits) {
          var value = m[key];
          var cls = best[key] !== undefined && value === best[key] ? ' class="bench-best"' : "";
          return "<td" + cls + ">" + metric(value, digits) + "</td>";
        }
        return "<tr>" +
          '<td><span class="bench-method">' + esc(name) + "</span></td>" +
          cell("doc_recall_at_5") +
          cell("mrr_at_10") +
          "<td>" + metric(m.abstention_rate_unanswerable, 2) + "</td>" +
          "<td>" + metric(m.latency_ms_median, 1) + "</td>" +
          "<td>" + metric(m.latency_ms_p95, 1) + "</td>" +
          "</tr>";
      }).join("");

      container.innerHTML =
        '<table class="bench-table"><thead><tr>' +
        "<th>Method</th><th>Recall@5</th><th>MRR@10</th>" +
        "<th>Abstain</th><th>Median ms</th><th>p95 ms</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table>" +
        '<p class="bench-meta">' +
        "Split <b>" + esc(report.split) + "</b> &middot; " +
        esc(report.question_count) + " questions &middot; run " +
        esc(report.run_timestamp) + "<br>" +
        esc(report.document_count) + " docs / " + esc(report.chunk_count) +
        " chunks &middot; fingerprint <code>" +
        esc(String(report.corpus_fingerprint).slice(0, 12)) + "</code> &middot; " +
        "model <code>" + esc(report.embedding_model) + "</code>" +
        "</p>" +
        '<p class="bench-meta">Synthetic, author-reviewed fixtures — not an ' +
        "independently validated benchmark. Latency is from one machine after " +
        "warm-up; read the ratio, not the third digit.</p>";
    } catch (err) {
      container.innerHTML = '<div class="note error">' + esc(err.message) + "</div>";
    }
  }

  // ----------------------------------------------------------------- wiring

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initReveal();
    initScrollChrome();

    loadStatus();
    loadExamples();
    loadDocuments();
    loadBenchmark();

    var question = el("question");
    question.addEventListener("input", function () { autoGrow(question); });

    // Enter submits, Shift+Enter inserts a newline.
    question.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        el("ask-form").requestSubmit();
      }
    });

    el("ask-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var text = question.value.trim();
      if (!text) { question.focus(); return; }

      var button = el("ask-button");
      var label = button.querySelector(".cta-label");
      button.disabled = true;
      label.textContent = "Asking";

      show(el("answer-panel"), true);
      el("answer-tag").textContent = "";
      skeleton(el("answer-body"), 4);
      show(el("chunks-panel"), false);

      try {
        var result = await api("/api/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: text,
            method: el("method").value,
            mode: el("mode").value,
            top_k: Number(el("topk").value) || 5,
          }),
        });
        renderAnswer(result);
      } catch (err) {
        el("answer-body").innerHTML =
          '<div class="note error">' + esc(err.message) + "</div>";
        el("answer-tag").textContent = "error";
        show(el("chunks-panel"), false);
        toast("error", err.message);
      } finally {
        button.disabled = false;
        label.textContent = "Ask";
      }
    });

    // Citation buttons are created dynamically, so delegate.
    document.addEventListener("click", function (event) {
      var target = event.target.closest ? event.target.closest(".cite") : null;
      if (target) openChunk(target.getAttribute("data-chunk"), target);
    });

    el("dialog-close").addEventListener("click", closeDialog);
    el("chunk-dialog").addEventListener("click", function (event) {
      if (event.target === el("chunk-dialog")) closeDialog();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDialog();
    });

    el("load-sample").addEventListener("click", async function () {
      var button = el("load-sample");
      var box = el("corpus-status");
      button.disabled = true;
      note(box, "info", "Loading sample corpus…");
      try {
        var result = await api("/api/sample-corpus", { method: "POST" });
        note(box, "ok",
          result.ingested + " ingested, " + result.duplicates + " already present. " +
          "Corpus is now " + result.document_count + " docs / " +
          result.chunk_count + " chunks." + (result.reindexed ? " Index rebuilt." : ""));
        toast("ok", "Corpus loaded: " + result.document_count + " documents.");
        loadDocuments();
        loadStatus();
      } catch (err) {
        note(box, "error", err.message);
        toast("error", err.message);
      } finally {
        button.disabled = false;
      }
    });

    // --- upload, with drag and drop ------------------------------------
    var drop = el("drop-zone");
    var fileInput = el("file");
    var dropText = el("drop-text");

    fileInput.addEventListener("change", function () {
      dropText.textContent = fileInput.files.length
        ? fileInput.files[0].name
        : "Choose a file or drop it here";
    });

    ["dragenter", "dragover"].forEach(function (name) {
      drop.addEventListener(name, function (event) {
        event.preventDefault();
        drop.classList.add("is-over");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      drop.addEventListener(name, function (event) {
        event.preventDefault();
        drop.classList.remove("is-over");
      });
    });
    drop.addEventListener("drop", function (event) {
      var files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length) {
        fileInput.files = files;
        dropText.textContent = files[0].name;
      }
    });

    el("upload-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var box = el("upload-status");
      if (!fileInput.files.length) { toast("warn", "Choose a file first."); return; }

      var button = el("upload-button");
      button.disabled = true;
      note(box, "info", "Uploading " + fileInput.files[0].name + "…");

      var form = new FormData();
      form.append("file", fileInput.files[0]);
      try {
        var result = await api("/api/documents", { method: "POST", body: form });
        if (result.status === "duplicate") {
          note(box, "warn", result.message || "Identical content is already stored.");
          toast("warn", "Duplicate content — nothing ingested.");
        } else {
          note(box, "ok",
            "Ingested as " + result.doc_id + " (" + result.chunk_count + " chunks).");
          toast("ok", "Ingested " + result.doc_id + ".");
        }
        fileInput.value = "";
        dropText.textContent = "Choose a file or drop it here";
        loadDocuments();
        loadStatus();
      } catch (err) {
        note(box, "error", err.message);
        toast("error", err.message);
      } finally {
        button.disabled = false;
      }
    });
  });
})();
