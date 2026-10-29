/* TraceRAG frontend.
 *
 * Every piece of document-derived text reaches the DOM through textContent or
 * through esc() into a template. Document content is never injected as HTML:
 * the corpus is user-supplied data and is treated as such.
 */

(function () {
  "use strict";

  var state = {
    methods: [],
    status: null,
    lastAnswer: null,
    chunkCache: {},
  };

  // --- helpers -----------------------------------------------------------

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function el(id) {
    return document.getElementById(id);
  }

  function show(node, visible) {
    node.hidden = !visible;
  }

  function notice(node, kind, message) {
    node.className = "notice " + kind;
    node.textContent = message;
    show(node, true);
  }

  function loading(node, message) {
    node.innerHTML =
      '<p class="muted"><span class="spinner"></span>' + esc(message) + "</p>";
  }

  async function api(path, options) {
    var response = await fetch(path, options);
    var body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
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
    var cls = status === "current" ? "current" : status === "superseded" ? "superseded" : "neutral";
    return '<span class="badge ' + cls + '">' + esc(status) + "</span>";
  }

  // --- status ------------------------------------------------------------

  async function loadStatus() {
    try {
      var status = await api("/api/status");
      state.status = status;
      state.methods = status.methods;

      el("stat-corpus").textContent =
        status.document_count + " docs / " + status.chunk_count + " chunks";

      var methodHtml = status.methods
        .map(function (m) {
          return m.available
            ? '<span class="badge current">' + esc(m.name) + "</span>"
            : '<span class="badge off" title="' + esc(m.reason || "unavailable") + '">' +
                esc(m.name) + " off</span>";
        })
        .join(" ");
      el("stat-methods").innerHTML = methodHtml;

      el("stat-llm").innerHTML = status.llm_configured
        ? '<span class="badge current">extractive + llm</span>'
        : '<span class="badge neutral">extractive only</span>';

      el("max-size").textContent = fmtBytes(status.max_upload_bytes);

      var methodSelect = el("method");
      methodSelect.innerHTML = status.methods
        .map(function (m) {
          var label = m.name.charAt(0).toUpperCase() + m.name.slice(1);
          if (!m.available) label += " - unavailable";
          return (
            '<option value="' + esc(m.name) + '"' +
            (m.available ? "" : " disabled") +
            (m.available && m.name === "hybrid" ? " selected" : "") +
            ">" + esc(label) + "</option>"
          );
        })
        .join("");
      if (!methodSelect.value) {
        var firstAvailable = status.methods.filter(function (m) { return m.available; })[0];
        if (firstAvailable) methodSelect.value = firstAvailable.name;
      }

      var modeSelect = el("mode");
      var llmOption = modeSelect.querySelector('option[value="llm"]');
      if (llmOption) {
        llmOption.disabled = !status.llm_configured;
        llmOption.textContent = status.llm_configured
          ? "LLM (" + (status.llm_model || "configured") + ")"
          : "LLM - not configured on this server";
      }

      var unavailable = status.methods.filter(function (m) { return !m.available; });
      if (unavailable.length) {
        var box = el("corpus-status");
        notice(
          box,
          "warn",
          unavailable
            .map(function (m) { return m.name + ": " + (m.reason || "unavailable"); })
            .join(" | ")
        );
      }
    } catch (err) {
      el("stat-corpus").textContent = "unavailable";
      el("stat-methods").textContent = "-";
      el("stat-llm").textContent = "-";
    }
  }

  // --- examples ----------------------------------------------------------

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
          '<span class="chip-tag">' + esc(example.label) + "</span> " + esc(example.question);
        button.addEventListener("click", function () {
          el("question").value = example.question;
          el("question").focus();
        });
        container.appendChild(button);
      });
    } catch (err) {
      el("examples").textContent = "";
    }
  }

  // --- documents ---------------------------------------------------------

  async function loadDocuments() {
    var container = el("documents");
    loading(container, "Loading documents");
    try {
      var documents = await api("/api/documents");
      if (!documents.length) {
        container.innerHTML =
          '<p class="muted">No documents yet. Use <b>Load sample corpus</b> to ingest the ' +
          "18 synthetic NimbusDesk documents.</p>";
        return;
      }
      container.innerHTML = documents
        .map(function (doc) {
          var meta = [];
          if (doc.version) meta.push("v" + esc(doc.version));
          meta.push(doc.chunk_count + " chunks");
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
    } catch (err) {
      container.innerHTML = '<p class="notice error">' + esc(err.message) + "</p>";
    }
  }

  // --- answering ---------------------------------------------------------

  function renderAnswerText(text, citations) {
    /* Escape first, then linkify [chunk-id] spans that are real citations. */
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
      .join(" ");

    return (
      '<details class="diagnostic"><summary>Why this was or was not answered</summary>' +
      '<div class="diagnostic-body">' +
      "<p>" + esc(abstention.reason) + "</p>" +
      "<p>Question terms: " + terms + "</p>" +
      "<p>" + esc(abstention.heuristic) + "</p>" +
      "</div></details>"
    );
  }

  function renderAnswer(result) {
    state.lastAnswer = result;
    var panel = el("answer-panel");
    var body = el("answer-body");
    show(panel, true);

    var bannerClass = result.insufficient_evidence
      ? "abstain"
      : result.mode === "llm"
      ? "llm"
      : "extractive";

    var bannerText = result.insufficient_evidence
      ? "Insufficient evidence - TraceRAG declined to answer. " + result.mode_label
      : result.mode_label;

    var html = '<div class="mode-banner ' + bannerClass + '">' + esc(bannerText) + "</div>";

    (result.warnings || []).forEach(function (warning) {
      html += '<div class="notice warn">' + esc(warning) + "</div>";
    });
    if (result.provider_error) {
      html += '<div class="notice error">Provider error: ' + esc(result.provider_error) + "</div>";
    }
    if ((result.rejected_citations || []).length) {
      html +=
        '<div class="notice error">Rejected invalid citation IDs: ' +
        esc(result.rejected_citations.join(", ")) +
        "</div>";
    }

    html += '<p class="answer-text">' + renderAnswerText(result.answer, result.citations) + "</p>";

    if ((result.citations || []).length) {
      html +=
        '<div class="meta-row"><span><b>Citations:</b> ' +
        result.citations
          .map(function (id) {
            return '<button type="button" class="cite" data-chunk="' + esc(id) + '">' + esc(id) + "</button>";
          })
          .join(" ") +
        "</span></div>";
    }

    html +=
      '<div class="meta-row">' +
      "<span><b>Method:</b> " + esc(result.retrieval.method) + "</span>" +
      "<span><b>Retrieval:</b> " + esc(result.retrieval.elapsed_ms) + " ms</span>" +
      "<span><b>Passages:</b> " + result.retrieval.chunks.length + "</span>" +
      "<span><b>Term coverage:</b> " + esc(result.abstention.coverage) + "</span>" +
      (result.llm_model ? "<span><b>Model:</b> " + esc(result.llm_model) + "</span>" : "") +
      "</div>";

    html += renderAbstention(result.abstention);

    body.innerHTML = html;
    renderChunks(result.retrieval);
  }

  function renderChunks(retrieval) {
    var panel = el("chunks-panel");
    var body = el("chunks-body");
    show(panel, true);
    el("score-semantics").textContent = retrieval.score_semantics;

    if (!retrieval.chunks.length) {
      body.innerHTML = '<p class="muted">No passages were retrieved for this query.</p>';
      return;
    }

    body.innerHTML = retrieval.chunks
      .map(function (chunk) {
        var source =
          esc(chunk.filename) +
          " lines " + Number(chunk.start_line) + "-" + Number(chunk.end_line) +
          (chunk.heading ? " &middot; " + esc(chunk.heading) : "");
        return (
          '<div class="chunk">' +
          '<div class="chunk-head">' +
          '<span class="chunk-rank">#' + chunk.rank + "</span>" +
          '<span class="chunk-title">' + esc(chunk.doc_title) + "</span>" +
          statusBadge(chunk.doc_status) +
          '<span class="chunk-id">' + esc(chunk.chunk_id) + "</span>" +
          '<span class="chunk-score">' + chunk.score + "</span>" +
          "</div>" +
          '<div class="chunk-source">' + source + "</div>" +
          '<div class="chunk-text">' + esc(chunk.text) + "</div>" +
          '<button type="button" class="chunk-toggle">Show full passage</button>' +
          "</div>"
        );
      })
      .join("");

    Array.prototype.forEach.call(body.querySelectorAll(".chunk-toggle"), function (button) {
      button.addEventListener("click", function () {
        var text = button.previousElementSibling;
        var expanded = text.classList.toggle("expanded");
        button.textContent = expanded ? "Collapse passage" : "Show full passage";
      });
    });
  }

  // --- citation dialog ---------------------------------------------------

  async function openChunk(chunkId) {
    var dialog = el("chunk-dialog");
    var body = el("dialog-body");
    show(dialog, true);
    el("dialog-title").textContent = chunkId;
    loading(body, "Loading passage");

    try {
      var chunk = state.chunkCache[chunkId];
      if (!chunk) {
        chunk = await api("/api/chunks/" + encodeURIComponent(chunkId));
        state.chunkCache[chunkId] = chunk;
      }
      body.innerHTML =
        '<div class="meta-row" style="border-top:none;padding-top:0">' +
        "<span><b>Document:</b> " + esc(chunk.doc_title || chunk.doc_id) + "</span>" +
        "<span><b>File:</b> " + esc(chunk.filename || "-") + "</span>" +
        "<span><b>Lines:</b> " + chunk.start_line + "-" + chunk.end_line + "</span>" +
        (chunk.heading ? "<span><b>Section:</b> " + esc(chunk.heading) + "</span>" : "") +
        "</div>" +
        '<div class="dialog-text">' + esc(chunk.text) + "</div>";
    } catch (err) {
      body.innerHTML = '<p class="notice error">' + esc(err.message) + "</p>";
    }
  }

  function closeDialog() {
    show(el("chunk-dialog"), false);
  }

  // --- benchmark ---------------------------------------------------------

  function metric(value, digits) {
    if (value === null || value === undefined) return "-";
    return Number(value).toFixed(digits === undefined ? 3 : digits);
  }

  async function loadBenchmark() {
    var container = el("benchmark-body");
    loading(container, "Loading benchmark");
    try {
      var payload = await api("/api/benchmark");
      if (!payload.available) {
        container.innerHTML =
          '<p class="muted">' + esc(payload.message || "No benchmark available.") + "</p>";
        return;
      }
      var report = payload.report;
      var rows = Object.keys(report.methods || {})
        .map(function (name) {
          var m = report.methods[name];
          if (!m.available) {
            return (
              "<tr><td>" + esc(name) + '</td><td colspan="5" class="unavailable">' +
              esc(m.reason || "unavailable") + "</td></tr>"
            );
          }
          return (
            "<tr><td>" + esc(name) + "</td>" +
            "<td>" + metric(m.doc_recall_at_5) + "</td>" +
            "<td>" + metric(m.mrr_at_10) + "</td>" +
            "<td>" + metric(m.abstention_rate_unanswerable, 2) + "</td>" +
            "<td>" + metric(m.latency_ms_median, 1) + "</td>" +
            "<td>" + metric(m.latency_ms_p95, 1) + "</td></tr>"
          );
        })
        .join("");

      container.innerHTML =
        '<table class="bench"><thead><tr>' +
        "<th>Method</th><th>Doc Recall@5</th><th>MRR@10</th>" +
        "<th>Abstain (no-answer)</th><th>Median ms</th><th>p95 ms</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table>" +
        '<p class="bench-meta">' +
        "Split: <b>" + esc(report.split) + "</b> &middot; " +
        esc(report.question_count) + " questions &middot; run " +
        esc(report.run_timestamp) + "<br>" +
        "Corpus " + esc(report.document_count) + " docs / " + esc(report.chunk_count) +
        " chunks &middot; fingerprint <code>" +
        esc(String(report.corpus_fingerprint).slice(0, 12)) + "</code><br>" +
        "Model: <code>" + esc(report.embedding_model) + "</code>" +
        "</p>" +
        '<p class="bench-meta">Synthetic, author-reviewed fixtures - not an ' +
        "independently validated benchmark. Latency measured on one machine " +
        "after warm-up; treat as indicative only.</p>";
    } catch (err) {
      container.innerHTML = '<p class="notice error">' + esc(err.message) + "</p>";
    }
  }

  // --- wiring ------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    loadStatus();
    loadExamples();
    loadDocuments();
    loadBenchmark();

    el("ask-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var question = el("question").value.trim();
      if (!question) return;

      var button = el("ask-button");
      button.disabled = true;
      button.textContent = "Asking...";
      show(el("answer-panel"), true);
      loading(el("answer-body"), "Retrieving passages and building an answer");
      show(el("chunks-panel"), false);

      try {
        var result = await api("/api/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: question,
            method: el("method").value,
            mode: el("mode").value,
            top_k: Number(el("topk").value) || 5,
          }),
        });
        renderAnswer(result);
      } catch (err) {
        el("answer-body").innerHTML = '<div class="notice error">' + esc(err.message) + "</div>";
        show(el("chunks-panel"), false);
      } finally {
        button.disabled = false;
        button.textContent = "Ask";
      }
    });

    document.addEventListener("click", function (event) {
      var target = event.target;
      if (target && target.classList && target.classList.contains("cite")) {
        openChunk(target.getAttribute("data-chunk"));
      }
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
      notice(box, "info", "Loading sample corpus...");
      try {
        var result = await api("/api/sample-corpus", { method: "POST" });
        notice(
          box,
          "ok",
          result.ingested + " ingested, " + result.duplicates + " already present. " +
            "Corpus now " + result.document_count + " docs / " + result.chunk_count + " chunks." +
            (result.reindexed ? " Index rebuilt." : "")
        );
        loadDocuments();
        loadStatus();
      } catch (err) {
        notice(box, "error", err.message);
      } finally {
        button.disabled = false;
      }
    });

    el("upload-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      var input = el("file");
      var box = el("upload-status");
      if (!input.files.length) return;

      var button = el("upload-button");
      button.disabled = true;
      notice(box, "info", "Uploading " + input.files[0].name + "...");

      var form = new FormData();
      form.append("file", input.files[0]);
      try {
        var result = await api("/api/documents", { method: "POST", body: form });
        if (result.status === "duplicate") {
          notice(box, "warn", result.message || "Identical content is already stored.");
        } else {
          notice(
            box,
            "ok",
            "Ingested as " + result.doc_id + " (" + result.chunk_count + " chunks)."
          );
        }
        input.value = "";
        loadDocuments();
        loadStatus();
      } catch (err) {
        notice(box, "error", err.message);
      } finally {
        button.disabled = false;
      }
    });
  });
})();
