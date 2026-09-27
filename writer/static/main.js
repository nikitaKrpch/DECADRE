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

  // Runs on every keystroke, synchronously: the underlines must never lag behind
  // the text or they drift out of place. The engine is expected to take < 50 ms.
  function analyse() {
    const text = D.ui.getText();
    let found = [];
    try {
      if (D.engine) found = D.engine.findIssues(text, D.rules || []);
    } catch (err) {
      console.error("[Decadre] engine.findIssues failed", err);
    }
    relocateAi(text);
    const visible = merge(found, aiIssues).filter((is) => !ignored.has(ignoreId(is, text)));
    D.ui.render(text, visible);

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
    let ruleIssues = [];
    try {
      if (D.engine) ruleIssues = D.engine.findIssues(text, D.rules || []);
    } catch (err) {
      console.error("[Decadre] engine.findIssues failed", err);
    }
    try {
      // The model is told what the rules already flag, so it looks for what a word list can't see.
      const already = [...new Set(ruleIssues.map((is) => is.match))];
      const res = await D.deepcheck.run(text, already);
      const list = Array.isArray(res) ? res : res.issues || [];
      const unlocated = Array.isArray(res) ? [] : res.unlocated || [];
      // Anything on words the rules already underline adds nothing: drop it (and don't count it).
      aiIssues = list
        .map((is) => Object.assign({}, is, { origin: "ai", key: is.key || `ai:${is.ruleId}:${is.start}` }))
        .filter((a) => !ruleIssues.some((r) => a.start < r.end && r.start < a.end));
      D.ui.renderUnlocated(unlocated);
      analyse();
      D.ui.setAiState("done", aiIssues.length + unlocated.length);
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
      onDeepCheck: D.deepcheck ? deepCheck : null,
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
