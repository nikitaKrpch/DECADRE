/* décadréE — panel inside the WordPress block editor (owner: P4). Nothing is sent anywhere. */
(function () {
  "use strict";
  const D = window.Decadre;
  const TEXT_BLOCKS = new Set(["core/paragraph", "core/heading", "core/list-item"]);
  const DISCLAIMER =
    "Suggestions indicatives, inspirées du livret décadréE 2023 ; elles n'engagent pas décadréE. " +
    "La rédaction reste seule responsable du contenu publié.";

  // WordPress loads the editor after our script: wait until its data stores exist.
  function whenEditorReady(cb, tries = 0) {
    const wp = window.wp;
    if (wp && wp.data && wp.data.select("core/block-editor") && wp.data.select("core/editor")) return cb(wp);
    if (tries < 120) setTimeout(() => whenEditorReady(cb, tries + 1), 500);
  }

  // Block content is HTML; the engine needs plain text. map[i] = index in the HTML of plain-text
  // character i, so a word can later be replaced without breaking bold or links.
  const decoder = document.createElement("textarea");
  function htmlToText(html) {
    let text = "";
    const map = [];
    for (let i = 0; i < html.length; ) {
      if (html[i] === "<") {
        const j = html.indexOf(">", i);
        if (/^<br\b/i.test(html.slice(i, i + 4))) { text += "\n"; map.push(i); }
        i = j === -1 ? html.length : j + 1;
        continue;
      }
      const ent = html[i] === "&" && /^&(#\d+|#x[0-9a-f]+|\w+);/i.exec(html.slice(i, i + 12));
      if (ent) {
        decoder.innerHTML = ent[0];
        for (const ch of decoder.value.split("")) { text += ch; map.push(i); }
        i += ent[0].length;
        continue;
      }
      text += html[i];
      map.push(i++);
    }
    map.push(html.length);
    return { text, map };
  }

  function readPost(wp) {
    const units = [{ id: "title", label: "Titre", text: wp.data.select("core/editor").getEditedPostAttribute("title") || "" }];
    const walk = (blocks) => blocks.forEach((b) => {
      const c = b.attributes && b.attributes.content;
      if (TEXT_BLOCKS.has(b.name) && c != null) {
        const html = String(c); // RichTextData (WP ≥ 6.5) or string
        units.push({ id: b.clientId, label: b.name === "core/heading" ? "Intertitre" : "Paragraphe", html, ...htmlToText(html) });
      }
      if (b.innerBlocks && b.innerBlocks.length) walk(b.innerBlocks);
    });
    walk(wp.data.select("core/block-editor").getBlocks());
    return units;
  }

  function analyse(units) {
    const issues = [];
    units.forEach((u, n) => {
      for (const is of D.engine.findIssues(u.text, D.rules)) {
        if (is.inQuote) continue; // quoted words are someone's words: never suggest changing them
        // Suggestions fitted to the form found ("drames" -> "féminicides"); null if they can't fit
        // the word itself or the words before it ("d'une violente dispute").
        const fitted = is.replacements.map((r) => {
          const a = D.engine.adapt(is, r);
          return a && D.engine.agree(u.text, is.start, is.end, a) ? a : null;
        });
        issues.push({ ...is, unit: u, n, fitted });
      }
    });
    const checklist = D.checklist.evaluate(units.map((u) => u.text).join("\n"));
    return { issues, checklist };
  }

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  // HTML indexes of a plain-text range; null if it crosses a tag (bold, link…).
  function htmlRange(u, start, end) {
    const hs = u.map[start], last = u.map[end - 1];
    const he = last + (u.html[last] === "&" ? u.html.indexOf(";", last) - last + 1 : 1);
    return u.html.slice(hs, he).includes("<") ? null : [hs, he];
  }

  const canReplace = (is) => (is.unit.id === "title" || htmlRange(is.unit, is.start, is.end) !== null);

  // Edits the block HTML in place so bold/links around the words are kept. Returns false if the
  // text changed since the analysis (typing during the debounce), so positions can't be trusted.
  function replaceIssue(wp, is, word) {
    const u = is.unit;
    const cased = /^\p{Lu}/u.test(is.match) ? word[0].toUpperCase() + word.slice(1) : word;
    let a = D.engine.agree(u.text, is.start, is.end, cased); // "une dispute" → "des violences sexistes"
    if (!a) return false;
    if (u.id === "title") {
      const title = wp.data.select("core/editor").getEditedPostAttribute("title") || "";
      if (title !== u.text) return false;
      wp.data.dispatch("core/editor").editPost({ title: title.slice(0, a.start) + a.text + title.slice(a.end) });
      return true;
    }
    const current = String(wp.data.select("core/block-editor").getBlockAttributes(u.id)?.content ?? "");
    let range = htmlRange(u, a.start, a.end);
    if (!range) { a = { start: is.start, end: is.end, text: cased }; range = htmlRange(u, a.start, a.end); }
    if (current !== u.html || !range) return false;
    const [hs, he] = range;
    wp.data.dispatch("core/block-editor").updateBlockAttributes(u.id, { content: u.html.slice(0, hs) + esc(a.text) + u.html.slice(he) });
    wp.data.dispatch("core/block-editor").selectionChange(u.id, "content", a.start, a.start + a.text.length);
    return true;
  }

  // Checklist texts are plain lines ("\n\nBesoin d'aide ?\n…"): turn them into real blocks.
  function insertFromChecklist(wp, it) {
    const { createBlock } = wp.blocks;
    const ed = wp.data.dispatch("core/block-editor");
    const lines = it.insert.text.trim().split("\n").filter(Boolean);
    if (it.insert.place === "end") {
      const [title, intro, ...services] = lines;
      ed.insertBlocks(createBlock("core/group", {}, [
        createBlock("core/heading", { level: 3, content: esc(title) }),
        createBlock("core/paragraph", { content: esc(intro) }),
        createBlock("core/list", {}, services.map((s) => createBlock("core/list-item", { content: esc(s) }))),
      ]));
    } else {
      ed.insertBlocks(lines.map((l) => createBlock("core/paragraph", { content: esc(l) })), afterFactsIndex(wp));
    }
  }

  // After the lead and the first facts paragraph, like the web app.
  function afterFactsIndex(wp) {
    const blocks = wp.data.select("core/block-editor").getBlocks();
    const paras = blocks.map((b, i) => (b.name === "core/paragraph" ? i : -1)).filter((i) => i >= 0);
    return paras.length >= 2 ? paras[1] + 1 : blocks.length;
  }

  // The title isn't a block: find it in the editor (inside an iframe in recent WordPress).
  function focusTitle() {
    const canvas = document.querySelector('iframe[name="editor-canvas"]');
    const el = ((canvas && canvas.contentDocument) || document).querySelector(".editor-post-title");
    if (el) { el.scrollIntoView({ block: "center" }); el.focus(); }
  }

  // Shadow DOM: WordPress's CSS and ours can't affect each other.
  const host = document.createElement("div");
  host.id = "decadre-wp-panel";
  const root = host.attachShadow({ mode: "open" });

  function render(state) {
    const { issues, checklist } = state;
    const todo = checklist.filter((it) => !it.done);
    root.innerHTML = `<style>${CSS}</style>
      <aside class="${panelOpen ? "" : "closed"}">
        <header><strong>décadréE</strong>
          <span class="count">${issues.length} à revoir · ${todo.length} à compléter</span>
          <button class="toggle" aria-expanded="${panelOpen}">${panelOpen ? "—" : "+"}</button></header>
        <div class="body">
          <h3>À revoir</h3>
          ${issues.length ? `<ul>${issues.map((is, i) => `
            <li class="issue ${is.severity}" data-i="${i}" tabindex="0">
              <span class="where">${esc(is.unit.label)}</span>
              <span class="match">« ${esc(is.match)} »</span>
              ${!is.replacements.length ? "" : !is.fitted.some(Boolean)
                  ? `<span class="note">À reformuler : « ${esc(is.match)} » ne peut pas être remplacé mot pour mot. Piste : ${is.replacements.map(esc).join(" / ")}</span>`
                  : canReplace(is)
                    ? `<span class="repls">${is.fitted.map((r, k) => r ? `<button class="repl" data-repl="${k}">${esc(r)}</button>` : "").join("")}</span>`
                    : `<span class="note">À modifier à la main (mise en forme) → ${is.fitted.filter(Boolean).map(esc).join(" / ")}</span>`}
              ${is.reason ? `<span class="reason">${esc(is.reason)}</span>` : ""}
              ${is.source ? `<span class="source">Source : ${esc(is.source)}</span>` : ""}
            </li>`).join("")}</ul>` : `<p class="empty">Aucune formulation repérée.</p>`}
          <h3>Ce qui manque</h3>
          <ul>${checklist.map((it) => `
            <li class="check ${it.done ? "done" : "todo"}"><span class="mark">${it.done ? "✓" : "○"}</span>
              <span><span class="label">${esc(it.label)}</span>
              ${!it.done && it.hint ? `<span class="reason">${esc(it.hint)}</span>` : ""}
              ${!it.done && it.source ? `<span class="source">Source : ${esc(it.source)}</span>` : ""}
              ${!it.done && it.where ? `<span class="reason">${esc(it.where)}</span>` : ""}
              ${!it.done && it.at ? `<button class="repl" data-goto="${esc(it.id)}">${esc(it.goto)}</button>` : ""}
              ${!it.done && it.insert ? `<button class="repl" data-insert="${esc(it.id)}">${esc(it.insert.button)}</button>` : ""}</span>
            </li>`).join("")}</ul>
          <p class="disclaimer">${esc(DISCLAIMER)}</p>
        </div>
      </aside>`;
  }

  const CSS = `
    aside { position: fixed; right: 16px; bottom: 16px; z-index: 100000; width: 340px; max-height: 70vh;
      display: flex; flex-direction: column; background: #fff; color: #1e1e1e; border: 1px solid #ccc;
      border-radius: 8px; box-shadow: 0 6px 24px rgba(0,0,0,.18); font: 13px/1.45 -apple-system, system-ui, sans-serif; }
    aside.closed .body { display: none; }
    header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #eee; }
    header strong { color: #6b2a8a; } .count { flex: 1; color: #555; font-size: 12px; }
    .toggle { border: 0; background: none; font-size: 16px; cursor: pointer; }
    .body { overflow-y: auto; padding: 4px 12px 12px; }
    h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #555; margin: 12px 0 6px; }
    ul { list-style: none; margin: 0; padding: 0; }
    li { padding: 8px; border-radius: 6px; margin-bottom: 6px; }
    .issue { border-left: 3px solid #d63638; background: #fcf0f1; cursor: pointer; }
    .issue.hint { border-left-color: #dba617; background: #fcf9e8; }
    .issue:hover, .issue:focus { outline: 2px solid #6b2a8a; }
    .where, .source { display: block; font-size: 11px; color: #757575; }
    .match { font-weight: 600; }
    .repls { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0; }
    .repl { border: 1px solid #00701a; background: #fff; color: #00701a; border-radius: 4px;
      padding: 2px 8px; font: inherit; cursor: pointer; }
    .repl:hover, .repl:focus { background: #00701a; color: #fff; }
    .check .repl { display: inline-block; margin-top: 4px; }
    .note { display: block; color: #555; font-style: italic; }
    .reason { display: block; margin-top: 2px; }
    .check { display: flex; gap: 8px; } .check.done { color: #00701a; } .mark { width: 14px; }
    .empty, .disclaimer { color: #757575; font-size: 12px; }
  `;

  // Underlines in the editor with the CSS Custom Highlight API: Chrome draws them over the text,
  // nothing is added to the content, so WordPress's editing and saving aren't affected.
  const HL_CSS = `
    ::highlight(decadre-strong) { text-decoration: underline wavy #d63638; text-decoration-thickness: 1.5px; }
    ::highlight(decadre-hint) { text-decoration: underline dotted #dba617; text-decoration-thickness: 2px; }
    ::highlight(decadre-active) { background-color: rgba(107, 42, 138, .18); }`;

  // Recent WordPress shows the post inside an iframe; older versions in the page itself.
  function editorDoc() {
    const canvas = document.querySelector('iframe[name="editor-canvas"]');
    return canvas && canvas.contentDocument && canvas.contentDocument.body ? canvas.contentDocument : document;
  }

  function unitElement(doc, u) {
    return u.id === "title"
      ? doc.querySelector(".editor-post-title")
      : doc.querySelector(`[data-block="${doc.defaultView.CSS.escape(u.id)}"]`);
  }

  // DOM range for plain-text offsets [start, end) of a block. Bold/links split the text into
  // several nodes; <br> counts as one character ("\n" in htmlToText); nested blocks (a sub-list
  // inside a list item) are skipped.
  function rangeFor(doc, el, start, end) {
    const NF = doc.defaultView.NodeFilter;
    const walker = doc.createTreeWalker(el, NF.SHOW_TEXT | NF.SHOW_ELEMENT, {
      acceptNode: (n) => (n !== el && n.nodeType === 1 && n.hasAttribute("data-block") ? NF.FILTER_REJECT : NF.FILTER_ACCEPT),
    });
    const range = doc.createRange();
    let pos = 0, started = false;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === 1) { if (n.nodeName === "BR") pos += 1; continue; }
      const len = n.data.length;
      if (!started && start < pos + len) { range.setStart(n, start - pos); started = true; }
      if (started && end <= pos + len) { range.setEnd(n, end - pos); return range; }
      pos += len;
    }
    return null;
  }

  let activeIssue = -1;

  function paint() {
    const doc = editorDoc(), win = doc.defaultView;
    if (!win.CSS || !win.CSS.highlights || !win.Highlight) return;
    if (!doc.getElementById("decadre-hl")) {
      const st = doc.createElement("style");
      st.id = "decadre-hl";
      st.textContent = HL_CSS;
      doc.head.appendChild(st);
    }
    const groups = { strong: [], hint: [], active: [] };
    state.issues.forEach((is, i) => {
      const el = unitElement(doc, is.unit);
      const r = el && rangeFor(doc, el, is.start, is.end);
      // If the editor shows something else there, skip it rather than underline the wrong words.
      if (!r || D.engine.fold(r.toString()) !== D.engine.fold(is.match)) return;
      groups[is.severity === "hint" ? "hint" : "strong"].push(r);
      if (i === activeIssue) groups.active.push(r.cloneRange());
    });
    for (const [k, ranges] of Object.entries(groups)) win.CSS.highlights.set(`decadre-${k}`, new win.Highlight(...ranges));
  }

  let panelOpen = true;
  let state = { issues: [], checklist: [] };

  whenEditorReady((wp) => {
    document.body.appendChild(host);

    root.addEventListener("click", (ev) => {
      if (ev.target.closest(".toggle")) { panelOpen = !panelOpen; return render(state); }
      if (ev.target.closest("[data-goto]")) return focusTitle();
      const ins = ev.target.closest("[data-insert]");
      if (ins) {
        const it = state.checklist.find((x) => x.id === ins.dataset.insert);
        if (it) insertFromChecklist(wp, it);
        return;
      }
      const li = ev.target.closest(".issue");
      if (!li) return;
      const is = state.issues[+li.dataset.i];
      const btn = ev.target.closest("[data-repl]");
      if (btn && is) {
        const word = is.fitted[+btn.dataset.repl];
        if (!word || !replaceIssue(wp, is, word)) { last = ""; refresh(); }
        return;
      }
      // RichText selection offsets are plain-text offsets, the same as the engine's.
      if (is && is.unit.id !== "title") {
        wp.data.dispatch("core/block-editor").selectionChange(is.unit.id, "content", is.start, is.end);
      }
    });

    const hover = (ev) => {
      const li = ev.target.closest(".issue");
      const i = li && ev.type !== "mouseout" && ev.type !== "focusout" ? +li.dataset.i : -1;
      if (i !== activeIssue) { activeIssue = i; paint(); }
    };
    for (const type of ["mouseover", "mouseout", "focusin", "focusout"]) root.addEventListener(type, hover);

    // wp.data.subscribe fires on every store change: debounce, and only re-analyse if the text
    // changed. Underlines are redrawn every time: WordPress can rebuild a paragraph's DOM (e.g. on
    // selection) without changing its text, which leaves the old ranges pointing at nothing.
    let last = "", timer;
    const refresh = () => {
      const units = readPost(wp);
      const sig = JSON.stringify(units.map((u) => [u.id, u.html ?? u.text]));
      if (sig !== last) {
        last = sig;
        state = analyse(units);
        activeIssue = -1;
        render(state);
      }
      paint();
    };
    wp.data.subscribe(() => { clearTimeout(timer); timer = setTimeout(refresh, 600); });
    refresh();
  });
})();
