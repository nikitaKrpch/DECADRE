/* Assistant de rédaction — "what's missing" checklist (owner: P4)
 *
 * Decadre.checklist.evaluate(text) → [{ id, label, done, hint, source?, insert? }]
 * Decadre.checklist.render(el, items)
 * Rule-based and instant (no AI). "insert" texts come from décadréE's own documents,
 * never from the model: Livret 2023 (p. 10-11) and the statistics review (May 2025).
 */
(function () {
  "use strict";
  const D = (window.Decadre = window.Decadre || {});

  // Lowercase + strip accents, so the rules below can be written without accents.
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/’/g, "'");

  const HELP_BOX =
    "\n\nBesoin d'aide ?\n" +
    "Si vous vous inquiétez pour vous ou un-e de vos proches, contactez en toute confidentialité :\n" +
    "Police : 117\n" +
    "Urgences médicales : 144\n" +
    "La Main Tendue (adultes) : 143\n" +
    "Pro Juventute (jeunes) : 147\n" +
    "Aide aux victimes LAVI : 142\n" +
    "Centre d'aide aux victimes : opferhilfe-schweiz.ch/fr\n" +
    "violencequefaire.ch — service de conseils en ligne anonyme et gratuit";

  const STAT_DOMESTIC =
    "\n\nEn 2024, 21 127 infractions ont été enregistrées en Suisse dans le contexte de la violence " +
    "domestique (statistique policière nationale).";
  const STAT_SEXUAL =
    "\n\nEn Suisse, 22 % des femmes ont subi des actes sexuels non consentis à partir de 16 ans " +
    "(étude gfs.bern pour Amnesty International).";

  // 1. Help resources: a known service, or a helpline number (117 police, 144 urgences, 143 La Main
  //    Tendue, 147 Pro Juventute, 142 aide aux victimes) next to words that show it's a helpline
  //    (so "117 femmes tuées" doesn't count).
  function hasHelpResource(t) {
    if (/violencequefaire|opferhilfe|\blavi\b|\bavvec\b|solidarite femmes|aide aux victimes|main tendue|pro juventute/.test(t)) return true;
    const re = /\b(117|144|143|147|142)\b/g;
    let m;
    while ((m = re.exec(t))) {
      const around = t.slice(Math.max(0, m.index - 40), m.index + 43);
      if (/police|urgence|appel|contact|compos|ambulance|secours|numero|ecoute/.test(around)) return true;
    }
    return false;
  }

  // 2. A woman killed by a (ex-)partner, but the word "féminicide" isn't used.
  const isPartnerKilling = (t) =>
    /\b(tue|tuee|tuer|meurtre|homicide|assassin\w*|abattu\w*)\b/.test(t) &&
    /\b(compagne|epouse|conjointe|concubine|petite amie|femme)\b/.test(t);

  // 4. An expert or specialised organisation.
  const hasExpert = (t) =>
    /\b(association\w*|expert\w*|psychologue\w*|psychiatre\w*|specialiste\w*|sociolog\w*|chercheu\w*|bureau (federal |cantonal )?de l'egalite|bfeg)\b/.test(t);

  // 5. Statistics: figures with a unit/scope, or an explicit reference to data.
  const hasStatistics = (t) =>
    /\d+(?:[.,]\d+)?\s?%/.test(t) ||
    /\b\d+ sur \d+\b|\bune femme sur\b/.test(t) ||
    /\b\d+\s+(femmes|victimes|cas|infractions|personnes)\b.{0,60}\b(par an|chaque annee|en 20\d\d|en suisse|en france)\b/.test(t) ||
    /\b(par an|chaque annee|en 20\d\d|en suisse|en france)\b.{0,60}\b\d{2,}\s+(femmes|victimes|cas|infractions|personnes)\b/.test(t) ||
    /\b(toutes les (deux |trois )?(semaines|jours|mois|ans)|chaque (semaine|jour|mois|annee))\b/.test(t) ||
    /\b(statistique\w*|selon les (dernieres )?(donnees|chiffres))\b/.test(t);

  // Forms of "viol/violer" only: a plain "viol\w*" would also match violence, violent(e), violemment.
  const isSexualViolence = (t) => /\b(viol(s|e|es|ee|ees|er|ait|aient|eur|eurs)?\b|agression\w* sexuel\w*|contrainte sexuelle|harcelement sexuel|attouchement\w*)\b/.test(t);

  // The headline: the first non-empty line.
  function headline(text) {
    const m = /[^\n]*\S[^\n]*/.exec(text);
    return m ? { start: m.index, end: m.index + m[0].length } : null;
  }

  // Where a statistic fits best: right after the paragraph that follows the headline and lead.
  function afterFirstFactsParagraph(text) {
    const paras = [];
    const re = /[^\n]+/g;
    let m;
    while ((m = re.exec(text))) if (m[0].trim()) paras.push(m.index + m[0].length);
    const pos = paras[2] ?? text.length;
    return { start: pos, end: pos };
  }

  function evaluate(text) {
    if (!text.trim()) return [];
    const t = fold(text);
    const items = [];

    // Label = what to do when missing, a short confirmation when done.
    const item = (id, done, todo, doneLabel, hint, source, extra) =>
      Object.assign({ id, done, label: done ? doneLabel : todo, hint, source }, extra);

    const help = hasHelpResource(t);
    items.push(item("help", help,
      "Ajouter une ressource d'aide", "Ressource d'aide mentionnée",
      "Des lectrices peuvent être concernées : indiquez où trouver de l'aide.",
      "Livret décadréE 2023, p. 10",
      { insert: { text: HELP_BOX, button: "Insérer l'encadré d'aide", place: "end" } }));

    if (isPartnerKilling(t)) {
      items.push(item("feminicide", /feminicide/.test(t),
        "Nommer le féminicide", "Féminicide nommé",
        "Une femme tuée par son (ex-)conjoint : c'est un féminicide. Nommez-le, idéalement dans le titre.",
        "Livret décadréE 2023, p. 14",
        { at: headline(text), goto: "Voir le titre" }));
    }

    items.push(item("expert", hasExpert(t),
      "Citer une personne spécialisée", "Personne spécialisée citée",
      "Ex. : centre LAVI, Solidarité Femmes, Bureau de l'égalité.",
      "Livret décadréE 2023, p. 8",
      { where: "Idéalement après le récit des faits." }));

    items.push(item("stats", hasStatistics(t),
      "Situer les faits avec un chiffre", "Chiffre de contexte présent",
      "Un chiffre montre que ces violences ne sont pas exceptionnelles.",
      "Livret décadréE 2023, p. 28",
      { insert: { text: isSexualViolence(t) ? STAT_SEXUAL : STAT_DOMESTIC, button: "Insérer un chiffre sourcé", place: "afterFacts" } }));

    return items;
  }

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  let lastItems = [];

  function render(el, items) {
    lastItems = items;
    el.innerHTML = items.length
      ? `<ul>${items.map((it) => `<li class="dw-check ${it.done ? "is-done" : "is-todo"}">
          <span class="dw-check-mark" aria-hidden="true">${it.done ? "✓" : "○"}</span>
          <span>
            <span class="dw-check-label">${esc(it.label)}</span><span class="visually-hidden"> ${it.done ? "(fait)" : "(à faire)"}</span>
            ${!it.done && it.hint ? `<span class="dw-check-hint">${esc(it.hint)}</span>` : ""}
            ${!it.done && it.source ? `<span class="dw-check-hint dw-small">Source : ${esc(it.source)}</span>` : ""}
            ${!it.done && it.where ? `<span class="dw-check-hint">${esc(it.where)}</span>` : ""}
            ${!it.done && it.at && D.ui && D.ui.select ? `<button type="button" class="dw-btn dw-btn-quiet" data-goto="${esc(it.id)}">${esc(it.goto)}</button>` : ""}
            ${!it.done && it.insert ? `<button type="button" class="dw-btn dw-btn-quiet" data-insert="${esc(it.id)}">${esc(it.insert.button)}</button>` : ""}
          </span></li>`).join("")}</ul>`
      : `<p class="dw-small">—</p>`;

    // Insert at the item's place (end of article, or after the first facts paragraph), then select the
    // new text so the journalist sees where it went. ui.replaceRange re-runs the analysis, so the item ticks.
    el.onclick = (ev) => {
      const go = ev.target.closest("[data-goto]");
      if (go) {
        const it = lastItems.find((x) => x.id === go.dataset.goto);
        if (it && it.at) D.ui.select(it.at.start, it.at.end);
        return;
      }
      const btn = ev.target.closest("[data-insert]");
      if (!btn || !D.ui) return;
      const item = lastItems.find((it) => it.id === btn.dataset.insert);
      if (!item) return;
      const text = D.ui.getText();
      const pos = item.insert.place === "afterFacts" ? afterFirstFactsParagraph(text).start : text.length;
      D.ui.replaceRange(pos, pos, item.insert.text);
      if (D.ui.select) {
        const lead = item.insert.text.length - item.insert.text.trimStart().length; // skip the blank line before it
        D.ui.select(pos + lead, pos + item.insert.text.length);
      }
    };
  }

  D.checklist = { evaluate, render };
})();
