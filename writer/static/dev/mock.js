/* DEV ONLY (owner: P3) — stand-ins so the UI can be built before the real parts exist.
 * Each block only runs if the real module is missing, so it steps aside automatically
 * once P2's rules.js / engine.js and P4's checklist.js / deepcheck.js are loaded.
 * Remove this file from editor.html at code freeze.
 */
(function () {
  "use strict";
  const D = (window.Decadre = window.Decadre || {});

  // Lowercase + strip accents one UTF-16 unit at a time, so positions stay 1:1 with the original.
  function fold(s) {
    let out = "";
    for (const ch of s.split("")) {
      const c = ch === "’" ? "'" : ch.toLowerCase().normalize("NFD")[0];
      out += c;
    }
    return out;
  }

  if (!D.rules) {
    console.info("[Decadre] mock rules in use");
    D.rules = [
      { id: "R11", category: "mots justes", patterns: ["drame*", "crime* passionnel*"], replacements: ["féminicide", "meurtre par partenaire ou ex-partenaire"], severity: "strong", reason: "Romantise ou banalise un meurtre ; nommer le féminicide montre sa dimension systémique.", source: "Livret 2023, p. 18" },
      { id: "R09", category: "mots justes", patterns: ["forcené*", "pervers", "prédateur*"], replacements: ["auteur de violence"], severity: "strong", reason: "Fait de l'auteur un être hors norme, alors que les auteurs de violences sont des personnes « ordinaires ».", source: "Livret 2023, p. 18" },
      { id: "R06", category: "mots justes", patterns: ["dispute*", "disputai*"], replacements: ["violences au sein du couple", "violences domestiques"], severity: "strong", reason: "Présente la violence comme un désaccord entre égaux et efface le rapport de pouvoir.", source: "Livret 2023, p. 16" },
      { id: "R10", category: "mots justes", patterns: ["victime* présumée*"], replacements: ["plaignante", "accusatrice"], severity: "strong", reason: "Met en doute la parole de la victime ; « plaignante » est exact et neutre.", source: "Livret 2023, p. 18" },
      { id: "R05", category: "mots justes", patterns: ["auteur* présumé*"], replacements: ["accusé"], severity: "strong", reason: "« Présumé » laisse planer un doute sur les faits ; « accusé » est exact et neutre.", source: "Livret 2023, p. 16" },
      { id: "R03", category: "mots justes", patterns: ["allégation*", "insinuation*"], replacements: ["accusations"], severity: "strong", reason: "Met en doute la parole de la victime ; « accusation » est un terme neutre.", source: "Livret 2023, p. 16" },
      { id: "R12", category: "mots justes", patterns: ["fléau*"], replacements: ["problème de société"], severity: "strong", reason: "Présente la violence comme une catastrophe naturelle, sans responsables.", source: "Livret 2023, p. 18" },
      { id: "A01", category: "animalisant", patterns: ["monstre*"], replacements: ["auteur de violence"], severity: "strong", reason: "Animalise l'auteur et le présente comme un être hors norme.", source: "Livret 2023, p. 9 (enjeu 5)" },
      { id: "F01", category: "déresponsabilisation", patterns: ["pét* les plombs", "pète* les plombs", "n'a pas supporté la rupture"], replacements: [], severity: "strong", reason: "Présente la violence comme une perte de contrôle, ce qui déresponsabilise l'auteur.", source: "Livret 2023, p. 9 (enjeu 5)" },
      { id: "F02", category: "substances", patterns: ["soirée* arrosée*"], replacements: [], severity: "hint", reason: "L'alcool ne justifie pas la violence : à mentionner seulement si c'est utile à l'information.", source: "Livret 2023, p. 9 (enjeu 5)" },
      { id: "F03", category: "origine", patterns: ["d'origine"], replacements: [], severity: "hint", reason: "Accentuer l'origine de l'auteur invisibilise la diversité des profils. Est-ce nécessaire ici ?", source: "Livret 2023, p. 9 (enjeu 5)" },
    ];
  }

  if (!D.engine) {
    console.info("[Decadre] mock engine in use");
    const cache = new Map();
    const toRegex = (pattern) => {
      if (!cache.has(pattern)) {
        const body = fold(pattern)
          .trim()
          .split(/\s+/)
          .map((word) => word.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[a-z]*"))
          .join("\\s+");
        cache.set(pattern, new RegExp(`(?<![a-z0-9])${body}(?![a-z0-9])`, "g"));
      }
      return cache.get(pattern);
    };
    const inQuote = (text, pos) => {
      const before = text.slice(0, pos);
      if (before.lastIndexOf("«") > before.lastIndexOf("»")) return true;
      return ((before.match(/["“”]/g) || []).length % 2) === 1;
    };

    D.engine = {
      findIssues(text, rules) {
        const folded = fold(text);
        const found = [];
        for (const rule of rules) {
          for (const p of rule.patterns) {
            const re = toRegex(p);
            re.lastIndex = 0;
            let m;
            while ((m = re.exec(folded))) {
              const start = m.index;
              const end = start + m[0].length;
              found.push({
                key: `${rule.id}:${start}`, ruleId: rule.id, start, end, match: text.slice(start, end),
                severity: rule.severity, replacements: rule.replacements || [], reason: rule.reason,
                source: rule.source, inQuote: inQuote(text, start), origin: "rules",
              });
            }
          }
        }
        // longest match first, then strong before hint; drop overlaps
        found.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start) || (a.severity === "strong" ? -1 : 1));
        const out = [];
        let lastEnd = -1;
        for (const is of found) if (is.start >= lastEnd) { out.push(is); lastEnd = is.end; }
        return out;
      },
    };
  }

  if (!D.checklist) {
    console.info("[Decadre] mock checklist in use");
    const has = (text, re) => re.test(fold(text));
    D.checklist = {
      evaluate(text) {
        if (!text.trim()) return [];
        const head = text.split(/\n\s*\n/).slice(0, 2).join(" ");
        const items = [
          { id: "headline", label: "Le titre et le chapeau nomment la violence.", done: has(head, /feminicide|violence|viol|agression|meurtre|tue/), hint: "Pas seulement « drame » ou « affaire »." },
          { id: "help", label: "Une ressource d'aide est mentionnée.", done: has(text, /violencequefaire|\b117\b|\b144\b|lavi|aide aux victimes/), hint: "Ex. violencequefaire.ch, 117, 144." },
          { id: "expert", label: "Une personne experte ou une association est citée.", done: has(text, /association|expert|psycholog|specialiste|sociologue/), hint: "" },
        ];
        if (has(text, /\d/)) items.push({ id: "stats", label: "Chiffres : définition, réalité sociale, méthode, contexte ?", done: false, hint: "Les quatre questions du livret (p. 28)." });
        return items;
      },
      render(el, items) {
        const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
        el.innerHTML = items.length
          ? `<ul>${items.map((it) => `<li class="dw-check ${it.done ? "is-done" : "is-todo"}">
              <span class="dw-check-mark" aria-hidden="true">${it.done ? "✓" : "○"}</span>
              <span><span class="dw-check-label">${esc(it.label)}</span><span class="visually-hidden"> ${it.done ? "(fait)" : "(à faire)"}</span>
              ${it.hint && !it.done ? `<span class="dw-check-hint">${esc(it.hint)}</span>` : ""}</span></li>`).join("")}</ul>`
          : `<p class="dw-small">—</p>`;
      },
    };
  }

  if (!D.deepcheck) {
    console.info("[Decadre] mock deep check in use");
    D.deepcheck = {
      async run(text) {
        await new Promise((r) => setTimeout(r, 900));
        const issues = [];
        const phrase = "un homme calme, très serviable";
        const at = text.indexOf(phrase);
        if (at !== -1) {
          issues.push({
            ruleId: "IA-portrait", start: at, end: at + phrase.length, match: phrase, severity: "hint",
            replacements: [], reason: "Le portrait flatteur de l'auteur peut relativiser les violences (enjeu 5).",
            source: "Suggestion IA (démo)", inQuote: false, origin: "ai",
          });
        }
        return {
          issues,
          unlocated: [{ extrait: "", reason: "La version de la victime n'apparaît pas : seules la police et des voisin·es sont citées.", suggestion: "Donner la parole à ses proches ou à une association." }],
        };
      },
    };
  }
})();
