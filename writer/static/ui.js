/* Assistant de rédaction — editor UI (owner: P3)
 *
 * Builds the page inside a root element and draws the suggestions:
 * a transparent <textarea> on top of a "backdrop" <div> that mirrors the
 * text and wraps each issue in a <mark>. The textarea keeps normal cursor,
 * selection and undo; the backdrop only paints the underlines.
 *
 * Public API (see writer/CONTRACT.md):
 *   Decadre.ui.init(root, handlers)   handlers: { onInput, onReplace, onIgnore,
 *                                               onSample, onDeepCheck }
 *   Decadre.ui.render(text, issues)   issues sorted by start, non-overlapping
 *   Decadre.ui.getText() / setText(text)
 *   Decadre.ui.replaceRange(start, end, text)
 *   Decadre.ui.select(start, end)     select + scroll to characters start..end (end optional)
 *   Decadre.ui.setAiState(state, info) state: "idle" | "loading" | "done" | "error"
 *   Decadre.ui.renderUnlocated(items)
 *   Decadre.ui.checklistEl            container that Decadre.checklist.render fills
 */
(function () {
  "use strict";
  const D = (window.Decadre = window.Decadre || {});

  // All user-facing text in one place (final wording: "Textes interface" tab).
  const STRINGS = {
    title: "Assistant de rédaction",
    subtitle: "Des suggestions basées sur les recommandations de décadréE, pendant que vous écrivez.",
    placeholder: "Collez ou écrivez votre article ici…",
    loadSample: "Charger un exemple",
    clear: "Effacer",
    editorLabel: "Texte de l'article",
    disclaimer:
      "C'est votre responsabilité. " +
      "Suggestions basées sur les recommandations de l'institut décadréE (livret 2023). " +
      "Elles ne remplacent pas votre jugement : c'est vous qui décidez.",
    suggestions: "Suggestions",
    checklist: "Points à considérer",
    howTitle: "Comment ça marche",
    how:
      "Collez ou écrivez votre texte. Les passages concernés par les recommandations sont " +
      "soulignés : cliquez dessus pour voir l'explication et une suggestion. " +
      "Votre texte reste dans votre navigateur et n'est envoyé nulle part.",
    legend: "Légende",
    aiButton: "Analyse approfondie (IA)",
    aiLoading: "Analyse en cours…",
    aiNote: "Envoie le texte à un serveur pour une analyse plus fine. Suggestions indicatives.",
    aiDone: (n) => (n === 0 ? "Aucune suggestion IA supplémentaire." : `${n} suggestion${n > 1 ? "s" : ""} IA ajoutée${n > 1 ? "s" : ""}.`),
    aiError: "L'analyse IA n'a pas pu aboutir. Les suggestions du livret restent disponibles.",
    aiUnlocated: "Remarques IA sur l'ensemble du texte",
    replaceWith: "Remplacer par",
    noReplacement: "Pas de remplacement automatique : à reformuler selon le contexte.",
    quoteNote: "Citation : à contextualiser plutôt qu'à modifier.",
    ignore: "Ignorer",
    close: "Fermer",
    empty: "Collez un texte pour commencer.",
    allClear: "Aucune suggestion restante. Pensez à relire les points ci-dessous.",
    counterLabel: (n) => (n > 1 ? "suggestions à regarder" : "suggestion à regarder"),
    words: (n) => `${n} mot${n > 1 ? "s" : ""}`,
  };

  // Each kind has a colour AND an icon AND a line style, so colour is never the only cue.
  const KINDS = {
    strong: { label: "À revoir", icon: "●", cls: "dw-strong" },
    hint: { label: "À vérifier selon le contexte", icon: "◐", cls: "dw-hint" },
    quote: { label: "Dans une citation", icon: "❝", cls: "dw-quote" },
    ai: { label: "Suggestion IA", icon: "✦", cls: "dw-ai" },
  };

  function kindOf(issue) {
    if (issue.origin === "ai") return "ai";
    if (issue.inQuote) return "quote";
    return issue.severity === "strong" ? "strong" : "hint";
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Keep the capitalisation of the original word ("Drame" -> "Féminicide").
  function matchCase(original, replacement) {
    if (!original || !replacement) return replacement;
    if (original.length > 1 && original === original.toUpperCase() && original !== original.toLowerCase()) {
      return replacement.toUpperCase();
    }
    const first = original[0];
    if (first !== first.toLowerCase()) return replacement[0].toUpperCase() + replacement.slice(1);
    return replacement;
  }

  const TEMPLATE = `
    <div class="dw" lang="fr">
      <header class="dw-head">
        <h1 class="dw-title">${esc(STRINGS.title)}</h1>
        <p class="dw-sub">${esc(STRINGS.subtitle)}</p>
      </header>
      <div class="dw-grid">
        <section class="dw-main">
          <div class="dw-toolbar">
            <button type="button" class="dw-btn" data-act="sample">${esc(STRINGS.loadSample)}</button>
            <button type="button" class="dw-btn dw-btn-quiet" data-act="clear">${esc(STRINGS.clear)}</button>
            <span class="dw-wordcount"></span>
          </div>
          <div class="dw-editor">
            <div class="dw-backdrop" aria-hidden="true"></div>
            <textarea class="dw-input" spellcheck="false" aria-label="${esc(STRINGS.editorLabel)}"
              aria-describedby="dw-disclaimer" placeholder="${esc(STRINGS.placeholder)}"></textarea>
            <div class="dw-card" role="dialog" aria-label="Suggestion" hidden></div>
          </div>
          <p class="dw-disclaimer" id="dw-disclaimer">${esc(STRINGS.disclaimer)}</p>
        </section>

        <aside class="dw-side">
          <section class="dw-panel dw-counter" aria-live="polite"></section>

          <section class="dw-panel">
            <h2 class="dw-h2">${esc(STRINGS.suggestions)}</h2>
            <ol class="dw-list"></ol>
          </section>

          <section class="dw-panel">
            <h2 class="dw-h2">${esc(STRINGS.checklist)}</h2>
            <div class="dw-checklist" id="dw-checklist"></div>
          </section>

          <section class="dw-panel dw-ai-panel" hidden>
            <button type="button" class="dw-btn dw-btn-ai" data-act="deepcheck">✦ ${esc(STRINGS.aiButton)}</button>
            <p class="dw-small">${esc(STRINGS.aiNote)}</p>
            <p class="dw-ai-status" aria-live="polite"></p>
            <div class="dw-unlocated"></div>
          </section>

          <section class="dw-panel dw-how">
            <h2 class="dw-h2">${esc(STRINGS.howTitle)}</h2>
            <p>${esc(STRINGS.how)}</p>
            <h3 class="dw-h3">${esc(STRINGS.legend)}</h3>
            <ul class="dw-legend">
              ${Object.values(KINDS)
                .map((k) => `<li><span class="dw-sample ${k.cls}">exemple</span> <span class="dw-icon ${k.cls}">${k.icon}</span> ${esc(k.label)}</li>`)
                .join("")}
            </ul>
          </section>
        </aside>
      </div>
    </div>`;

  let els = {};
  let handlers = {};
  let issues = [];
  let activeKey = null;
  let returnFocusTo = null;

  function init(root, h) {
    handlers = h || {};
    root.innerHTML = TEMPLATE;
    els = {
      editor: root.querySelector(".dw-editor"),
      backdrop: root.querySelector(".dw-backdrop"),
      input: root.querySelector(".dw-input"),
      card: root.querySelector(".dw-card"),
      list: root.querySelector(".dw-list"),
      counter: root.querySelector(".dw-counter"),
      words: root.querySelector(".dw-wordcount"),
      aiPanel: root.querySelector(".dw-ai-panel"),
      aiButton: root.querySelector('[data-act="deepcheck"]'),
      aiStatus: root.querySelector(".dw-ai-status"),
      unlocated: root.querySelector(".dw-unlocated"),
    };
    api.checklistEl = root.querySelector("#dw-checklist");
    els.aiPanel.hidden = !handlers.onDeepCheck;

    els.input.addEventListener("input", () => {
      autosize();
      if (handlers.onInput) handlers.onInput(getText());
    });
    els.input.addEventListener("click", onEditorClick);
    window.addEventListener("resize", () => {
      autosize();
      if (activeKey) placeCard(activeKey);
    });

    root.querySelector('[data-act="sample"]').addEventListener("click", () => handlers.onSample && handlers.onSample());
    root.querySelector('[data-act="clear"]').addEventListener("click", clearText);
    els.aiButton.addEventListener("click", () => handlers.onDeepCheck && handlers.onDeepCheck(getText()));

    els.list.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-key]");
      if (!btn) return;
      returnFocusTo = btn;
      openCard(btn.dataset.key, { focus: true, scroll: true });
    });

    els.card.addEventListener("click", onCardClick);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && activeKey) {
        closeCard();
        if (returnFocusTo) returnFocusTo.focus();
      }
    });
    document.addEventListener("mousedown", (e) => {
      if (activeKey && !els.card.contains(e.target) && e.target !== els.input && !els.list.contains(e.target)) {
        closeCard();
      }
    });

    autosize();
    render("", []);
  }

  function getText() {
    return els.input.value;
  }

  function setText(text) {
    els.input.value = text;
    autosize();
    closeCard();
    if (handlers.onInput) handlers.onInput(text);
  }

  // Goes through execCommand so the browser's undo (Ctrl/Cmd+Z) still works.
  function replaceRange(start, end, text) {
    const ta = els.input;
    ta.focus();
    ta.setSelectionRange(start, end);
    const ok = document.execCommand && document.execCommand("insertText", false, text);
    if (!ok) {
      ta.setRangeText(text, start, end, "end");
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  // Selects characters start..end in the editor and scrolls the page to them.
  // For P4's checklist "Voir dans le texte". start === end places the cursor there.
  function select(start, end) {
    const ta = els.input;
    const len = ta.value.length;
    start = Math.max(0, Math.min(start, len));
    end = Math.max(start, Math.min(end == null ? start : end, len));
    closeCard();
    ta.focus({ preventScroll: true });
    ta.setSelectionRange(start, end);
    // A collapsed range has no size on screen; measure one character to find the spot.
    const r = rangeRect(start, end > start ? end : Math.min(start + 1, len));
    if (r) window.scrollTo({ top: window.scrollY + r.top - window.innerHeight / 3, behavior: "smooth" });
  }

  // Where characters start..end are on screen. The backdrop holds exactly the same text as the
  // textarea (split across text nodes by the <mark>s), so walk its text nodes to find them.
  function rangeRect(start, end) {
    const walker = document.createTreeWalker(els.backdrop, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let pos = 0;
    let started = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const n = node.data.length;
      if (!started && start <= pos + n) {
        range.setStart(node, start - pos);
        started = true;
      }
      if (started && end <= pos + n) {
        range.setEnd(node, end - pos);
        return range.getClientRects()[0] || range.getBoundingClientRect();
      }
      pos += n;
    }
    return null;
  }

  function clearText() {
    if (!getText()) return;
    els.input.focus();
    els.input.select();
    const ok = document.execCommand && document.execCommand("delete");
    if (!ok) setText("");
  }

  function autosize() {
    const ta = els.input;
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
  }

  // ---------------------------------------------------------------- rendering

  function render(text, newIssues) {
    issues = newIssues || [];
    els.backdrop.innerHTML = buildHighlights(text, issues);
    renderList();
    renderCounter(text);
    const n = text.trim() ? text.trim().split(/\s+/).length : 0;
    els.words.textContent = STRINGS.words(n);

    if (activeKey) {
      if (issues.some((is) => is.key === activeKey)) placeCard(activeKey);
      else closeCard();
    }
  }

  function buildHighlights(text, list) {
    let out = "";
    let pos = 0;
    for (const is of list) {
      if (is.start < pos || is.end > text.length || is.end <= is.start) continue; // skip overlaps / stale
      const k = KINDS[kindOf(is)];
      out += esc(text.slice(pos, is.start));
      out += `<mark class="dw-mark ${k.cls}${is.key === activeKey ? " is-active" : ""}" data-key="${esc(is.key)}">${esc(text.slice(is.start, is.end))}</mark>`;
      pos = is.end;
    }
    out += esc(text.slice(pos));
    // A trailing newline has no height in a <div>; add a space so both layers stay aligned.
    if (text === "" || text.endsWith("\n")) out += " ";
    return out;
  }

  function renderList() {
    els.list.innerHTML = issues
      .map((is) => {
        const k = KINDS[kindOf(is)];
        const rep = is.replacements && is.replacements.length ? `<span class="dw-item-rep">→ ${esc(is.replacements[0])}</span>` : "";
        return `<li><button type="button" class="dw-item" data-key="${esc(is.key)}"
                  aria-label="${esc(k.label)} : ${esc(is.match)}">
                  <span class="dw-icon ${k.cls}" aria-hidden="true">${k.icon}</span>
                  <span class="dw-item-match">${esc(is.match)}</span>${rep}
                </button></li>`;
      })
      .join("");
  }

  function renderCounter(text) {
    if (!text.trim()) {
      els.counter.innerHTML = `<p class="dw-count-empty">${esc(STRINGS.empty)}</p>`;
      return;
    }
    const n = issues.length;
    if (n === 0) {
      els.counter.innerHTML = `<div class="dw-count-num dw-count-zero">0</div><p class="dw-count-label">${esc(STRINGS.allClear)}</p>`;
      return;
    }
    const counts = { strong: 0, hint: 0, quote: 0, ai: 0 };
    for (const is of issues) counts[kindOf(is)]++;
    const chips = Object.entries(counts)
      .filter(([, c]) => c > 0)
      .map(([kind, c]) => `<li><span class="dw-icon ${KINDS[kind].cls}" aria-hidden="true">${KINDS[kind].icon}</span> ${c} ${esc(KINDS[kind].label.toLowerCase())}</li>`)
      .join("");
    els.counter.innerHTML = `<div class="dw-count-num">${n}</div>
      <p class="dw-count-label">${esc(STRINGS.counterLabel(n))}</p>
      <ul class="dw-count-break">${chips}</ul>`;
  }

  // ---------------------------------------------------------------- card

  function onEditorClick() {
    const ta = els.input;
    if (ta.selectionStart !== ta.selectionEnd) return;
    const pos = ta.selectionStart;
    const hit = issues.find((is) => is.start <= pos && pos <= is.end);
    if (hit) {
      returnFocusTo = ta;
      openCard(hit.key, { focus: false });
    } else {
      closeCard();
    }
  }

  function openCard(key, opts) {
    const is = issues.find((x) => x.key === key);
    if (!is) return;
    activeKey = key;
    const k = KINDS[kindOf(is)];
    const reps = is.replacements || [];

    els.card.innerHTML = `
      <div class="dw-card-head">
        <span class="dw-tag ${k.cls}"><span aria-hidden="true">${k.icon}</span> ${esc(k.label)}</span>
        <button type="button" class="dw-x" data-card="close" aria-label="${esc(STRINGS.close)}">×</button>
      </div>
      <p class="dw-card-match">« ${esc(is.match)} »</p>
      ${is.reason ? `<p class="dw-card-reason">${esc(is.reason)}</p>` : ""}
      ${is.inQuote ? `<p class="dw-card-note">${esc(STRINGS.quoteNote)}</p>` : ""}
      ${
        reps.length
          ? `<p class="dw-card-label">${esc(STRINGS.replaceWith)}</p>
             <div class="dw-card-reps">${reps
               .map(
                 (r, i) =>
                   `<button type="button" class="dw-rep" data-card="replace" data-index="${i}"
                      aria-label="Remplacer « ${esc(is.match)} » par « ${esc(matchCase(is.match, r))} »">${esc(matchCase(is.match, r))}</button>`
               )
               .join("")}</div>`
          : `<p class="dw-card-note">${esc(STRINGS.noReplacement)}</p>`
      }
      <div class="dw-card-foot">
        <button type="button" class="dw-btn dw-btn-quiet" data-card="ignore">${esc(STRINGS.ignore)}</button>
        ${is.source ? `<span class="dw-source">${esc(is.source)}</span>` : ""}
      </div>`;

    els.card.hidden = false;
    for (const m of els.backdrop.querySelectorAll("mark")) m.classList.toggle("is-active", m.dataset.key === key);
    placeCard(key, opts && opts.scroll);
    if (opts && opts.focus) {
      const first = els.card.querySelector(".dw-rep, [data-card='ignore']");
      if (first) first.focus({ preventScroll: true });
    }
  }

  function placeCard(key, scroll) {
    const mark = Array.from(els.backdrop.querySelectorAll("mark")).find((m) => m.dataset.key === key);
    if (!mark) return;
    if (scroll) mark.scrollIntoView({ block: "center", behavior: "smooth" });
    const wrap = els.editor.getBoundingClientRect();
    const r = mark.getClientRects()[0] || mark.getBoundingClientRect();
    const maxLeft = els.editor.clientWidth - els.card.offsetWidth - 8;
    els.card.style.top = `${r.bottom - wrap.top + 8}px`;
    els.card.style.left = `${Math.max(8, Math.min(r.left - wrap.left, maxLeft))}px`;
  }

  function closeCard() {
    activeKey = null;
    els.card.hidden = true;
    for (const m of els.backdrop.querySelectorAll("mark.is-active")) m.classList.remove("is-active");
  }

  function onCardClick(e) {
    const btn = e.target.closest("[data-card]");
    if (!btn) return;
    const is = issues.find((x) => x.key === activeKey);
    const action = btn.dataset.card;
    if (action === "close" || !is) {
      closeCard();
      if (returnFocusTo) returnFocusTo.focus();
      return;
    }
    if (action === "replace") {
      const rep = matchCase(is.match, is.replacements[Number(btn.dataset.index)]);
      closeCard();
      if (handlers.onReplace) handlers.onReplace(is, rep);
      else replaceRange(is.start, is.end, rep);
    } else if (action === "ignore") {
      closeCard();
      if (handlers.onIgnore) handlers.onIgnore(is);
      els.input.focus();
    }
  }

  // ---------------------------------------------------------------- AI panel

  function setAiState(state, info) {
    els.aiButton.disabled = state === "loading";
    els.aiButton.textContent = state === "loading" ? STRINGS.aiLoading : `✦ ${STRINGS.aiButton}`;
    els.aiStatus.className = "dw-ai-status" + (state === "error" ? " is-error" : "");
    if (state === "done") els.aiStatus.textContent = STRINGS.aiDone(info || 0);
    else if (state === "error") els.aiStatus.textContent = STRINGS.aiError;
    else els.aiStatus.textContent = "";
  }

  function renderUnlocated(items) {
    if (!items || !items.length) {
      els.unlocated.innerHTML = "";
      return;
    }
    els.unlocated.innerHTML = `<h3 class="dw-h3">${esc(STRINGS.aiUnlocated)}</h3><ul class="dw-unlocated-list">${items
      .map(
        (u) => `<li><span class="dw-icon dw-ai" aria-hidden="true">✦</span>
          ${u.extrait ? `<q>${esc(u.extrait)}</q> ` : ""}${esc(u.reason || u.raison || "")}
          ${u.suggestion ? `<br><span class="dw-item-rep">→ ${esc(u.suggestion)}</span>` : ""}</li>`
      )
      .join("")}</ul>`;
  }

  const api = { init, render, getText, setText, replaceRange, select, setAiState, renderUnlocated, checklistEl: null, STRINGS };
  D.ui = api;
})();
