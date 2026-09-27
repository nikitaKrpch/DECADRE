/* Assistant de rédaction — wiring (owner: P3)
 *
 * Connects Decadre.engine (P2), Decadre.checklist and Decadre.deepcheck (P4)
 * to Decadre.ui. Every piece is optional, so the page keeps working when one
 * of them is missing or throws.
 */
(function () {
  "use strict";
  const D = (window.Decadre = window.Decadre || {});

  const ignored = new Set();
  let aiIssues = [];
  let checklistTimer = null;
  let analysisTimer = null;
  let analysisRequest = 0;

  // An ignore must survive edits elsewhere in the text, so it can't use the raw
  // position. Identify the issue by rule + matched words + which occurrence it is.
  function ignoreId(issue, text) {
    const lower = text.toLowerCase();
    const m = lower.slice(issue.start, issue.end);
    let n = 0;
    for (let i = lower.indexOf(m); i !== -1 && i < issue.start; i = lower.indexOf(m, i + 1)) n++;
    return `${issue.origin || "rules"}|${issue.ruleId}|${m}|${n}`;
  }

  // AI issues come back once, with positions for the text at that moment.
  // After edits, move each one to the nearest place its words still appear, or drop it.
  function relocateAi(text) {
    aiIssues = aiIssues.filter((is) => {
      if (text.slice(is.start, is.end) === is.match) return true;
      let best = -1;
      for (let i = text.indexOf(is.match); i !== -1; i = text.indexOf(is.match, i + 1)) {
        if (best === -1 || Math.abs(i - is.start) < Math.abs(best - is.start)) best = i;
      }
      if (best === -1) return false;
      is.start = best;
      is.end = best + is.match.length;
      is.key = `ai:${is.ruleId}:${best}`;
      return true;
    });
  }

  // Rule issues win over AI issues on the same words; result is sorted and non-overlapping.
  function merge(ruleIssues, ai) {
    const all = ruleIssues.concat(ai.filter((a) => !ruleIssues.some((r) => a.start < r.end && r.start < a.end)));
    all.sort((a, b) => a.start - b.start || b.end - a.end);
    const out = [];
    let lastEnd = -1;
    for (const is of all) {
      if (is.start >= lastEnd) {
        out.push(is);
        lastEnd = is.end;
      }
    }
    return out;
  }

  function scheduleServerAnalysis(text) {
    clearTimeout(analysisTimer);
    const requestId = ++analysisRequest;
    if (!text.trim()) return;
    analysisTimer = setTimeout(async () => {
      try {
        const response = await fetch("/rediger/api/analyse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!response.ok) return;
        const result = await response.json();
        if (requestId !== analysisRequest || D.ui.getText() !== text || !Array.isArray(result.issues)) return;
        const visible = merge(result.issues, aiIssues).filter((is) => !ignored.has(ignoreId(is, text)));
        D.ui.render(text, visible);
      } catch (err) {
        // Local matching remains visible when the server is unavailable.
        console.warn("[Decadre] server rule analysis unavailable", err);
      }
    }, 400);
  }

  // Local matching keeps feedback immediate; the server replaces it after lemmatization.
  function analyse(text = D.ui.getText()) {
    let found = [];
    try {
      if (D.engine) found = D.engine.findIssues(text, D.rules || []);
    } catch (err) {
      console.error("[Decadre] engine.findIssues failed", err);
    }
    relocateAi(text);
    const visible = merge(found, aiIssues).filter((is) => !ignored.has(ignoreId(is, text)));
    D.ui.render(text, visible);
    scheduleServerAnalysis(text);

    clearTimeout(checklistTimer);
    checklistTimer = setTimeout(() => updateChecklist(text), 250);
  }

  function updateChecklist(text) {
    if (!D.checklist || !D.ui.checklistEl) return;
    try {
      D.checklist.render(D.ui.checklistEl, D.checklist.evaluate(text));
    } catch (err) {
      console.error("[Decadre] checklist failed", err);
    }
  }

  async function deepCheck(text) {
    if (!text.trim()) return;
    D.ui.setAiState("loading");
    try {
      const res = await D.deepcheck.run(text);
      const list = Array.isArray(res) ? res : res.issues || [];
      aiIssues = list.map((is) => Object.assign({}, is, { origin: "ai", key: is.key || `ai:${is.ruleId}:${is.start}` }));
      D.ui.renderUnlocated(Array.isArray(res) ? [] : res.unlocated || []);
      analyse();
      D.ui.setAiState("done", aiIssues.length);
    } catch (err) {
      console.error("[Decadre] deep check failed", err);
      D.ui.setAiState("error");
    }
  }

  function start() {
    const root = document.getElementById("decadre-writer");
    if (!root || !D.ui) return;
    D.ui.init(root, {
      onInput: analyse,
      onReplace: (is, rep) => D.ui.replaceRange(is.start, is.end, rep),
      onIgnore: (is) => {
        ignored.add(ignoreId(is, D.ui.getText()));
        analyse();
      },
      onSample: () => {
        const s = (D.samples || [])[0];
        if (s) D.ui.setText(s.text);
      },
      onDeepCheck: D.deepcheck ? deepCheck : null,
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
