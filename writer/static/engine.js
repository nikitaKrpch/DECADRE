/* Assistant de rédaction — rules engine.
 *
 * Decadre.engine.findIssues(text, rules) -> Issue[] (see writer/CONTRACT.md)
 *
 * How it works:
 *   1. "Fold" the text: lowercase, strip accents, straighten apostrophes, one character at
 *      a time, so the folded copy has exactly the same length and positions as the original.
 *   2. Turn each rule pattern into a regular expression on folded text: whole words only,
 *      "*" = any word ending, and common French plural / feminine / verb endings added
 *      automatically (so "allégation" also finds "allégations", "peloter" finds "pelotait",
 *      "dispute" finds "disputait"). A rule with "exact": true turns this off.
 *   3. Keep the longest match where matches overlap, mark matches inside quotations.
 *
 * Runs in the browser (window.Decadre.engine) and in Node (module.exports) for validation.
 */
(function (root) {
  "use strict";
  const D = (root.Decadre = root.Decadre || {});

  const APOSTROPHES = /[’‘ʼ′`´]/;
  const LETTER = "\\p{L}\\p{N}";
  const MIN_INFLECT = 4; // shorter words ("de", "la", "par") are matched exactly

  // Same length as the input: every UTF-16 unit maps to exactly one unit.
  function fold(text) {
    let out = "";
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (APOSTROPHES.test(ch)) out += "'";
      else if (ch === " " || ch === " ") out += " "; // non-breaking spaces (« texte »)
      else {
        const base = ch.toLowerCase().normalize("NFD")[0];
        out += base && base.length === 1 ? base : ch;
      }
    }
    return out;
  }

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // One word of a pattern -> regex source. Endings are matched on folded text (é -> e).
  function wordSource(word, exact) {
    if (word.includes("*")) {
      return word.split("*").map(escapeRegex).join(`[${LETTER}]*`);
    }
    const w = escapeRegex(word);
    if (exact || word.length < MIN_INFLECT || !/[a-z]$/.test(word)) return w;
    // -er verbs: caresser -> caresse, caressé(e)(s), caressait, caressent, caressant...
    if (word.length >= 5 && word.endsWith("er")) {
      const stem = escapeRegex(word.slice(0, -2));
      return `${stem}(?:er|erait|era|ent|ees|ee|es|e|aient|ait|ais|ai|ant|ons|ez|a)`;
    }
    // -al adjectives: familial -> familiaux, familiale(s)
    if (word.length >= 5 && word.endsWith("al")) {
      return `${escapeRegex(word.slice(0, -2))}(?:al|aux|ale|ales|als)`;
    }
    // -e words are often nouns AND verbs: dispute -> disputes, disputait, disputé(e)(s)
    if (word.length >= 5 && word.endsWith("e")) {
      return `${escapeRegex(word.slice(0, -1))}(?:e|es|er|ee|ees|ent|aient|ait|ais|ant)`;
    }
    // everything else: plural and feminine (présumé -> présumée(s), fléau -> fléaux)
    return `${w}(?:e|s|es|x)?`;
  }

  const regexCache = new Map();

  function patternRegex(pattern, exact) {
    const cacheKey = (exact ? "=" : "~") + pattern;
    if (regexCache.has(cacheKey)) return regexCache.get(cacheKey);
    let re = null;
    const words = fold(String(pattern)).trim().split(/\s+/).filter(Boolean);
    if (words.length) {
      const body = words.map((w) => wordSource(w, exact)).join("\\s+");
      try {
        re = new RegExp(`(?<![${LETTER}])${body}(?![${LETTER}])`, "gu");
        // A pattern that can match nothing (e.g. a lone "*") would underline empty spots.
        if (re.test("")) throw new Error("matches empty text");
        re.lastIndex = 0;
      } catch (err) {
        console.warn("[Decadre] pattern ignored:", pattern, err.message);
        re = null;
      }
    }
    regexCache.set(cacheKey, re);
    return re;
  }

  // Ranges [start, end) of text inside quotation marks. French « » and curly “ ” open and
  // close; straight " toggles. A quote never runs past the end of its paragraph, so one
  // unclosed « can't turn the rest of the article into a "quotation".
  function quoteRanges(text) {
    const ranges = [];
    let open = -1;
    let closer = null;
    const close = (end) => {
      if (open !== -1) ranges.push([open, end]);
      open = -1;
      closer = null;
    };
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === "\n" && /^\n\s*\n/.test(text.slice(i, i + 20))) {
        close(i);
      } else if (open === -1) {
        if (ch === "«") [open, closer] = [i, "»"];
        else if (ch === "“") [open, closer] = [i, "”"];
        else if (ch === '"') [open, closer] = [i, '"'];
      } else if (ch === closer) {
        close(i + 1);
      }
    }
    close(text.length);
    return ranges;
  }

  function inRanges(ranges, pos) {
    for (const [s, e] of ranges) {
      if (pos < s) return false;
      if (pos < e) return true;
    }
    return false;
  }

  function findIssues(text, rules) {
    if (typeof text !== "string" || !text || !Array.isArray(rules)) return [];
    const folded = fold(text);
    const quotes = quoteRanges(text);
    const found = [];

    for (const rule of rules) {
      if (!rule || !Array.isArray(rule.patterns)) continue;
      for (const pattern of rule.patterns) {
        const re = patternRegex(pattern, rule.exact);
        if (!re) continue;
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(folded))) {
          if (m[0].length === 0) {
            // step over a whole character (emoji are 2 units; stepping 1 would loop forever)
            re.lastIndex = m.index + (folded.codePointAt(m.index) > 0xffff ? 2 : 1);
            continue;
          }
          const start = m.index;
          const end = start + m[0].length;
          found.push({
            key: `${rule.id}:${start}`,
            ruleId: rule.id,
            start,
            end,
            match: text.slice(start, end),
            severity: rule.severity === "hint" ? "hint" : "strong",
            replacements: Array.isArray(rule.replacements) ? rule.replacements : [],
            reason: rule.reason || "",
            source: rule.source || "",
            category: rule.category || "",
            inQuote: inRanges(quotes, start),
            origin: "rules",
          });
        }
      }
    }

    // Overlaps: longest match wins, then strong before hint, then rule order.
    found.sort(
      (a, b) =>
        a.start - b.start ||
        b.end - b.start - (a.end - a.start) ||
        (a.severity === b.severity ? 0 : a.severity === "strong" ? -1 : 1)
    );
    const out = [];
    let lastEnd = -1;
    for (const is of found) {
      if (is.start >= lastEnd) {
        out.push(is);
        lastEnd = is.end;
      } else if (is.end > lastEnd && out.length && is.end - is.start > out[out.length - 1].end - out[out.length - 1].start) {
        // a longer match starting inside the previous one replaces it
        out[out.length - 1] = is;
        lastEnd = is.end;
      }
    }
    return out;
  }

  D.engine = { findIssues, fold };
  if (typeof module !== "undefined" && module.exports) module.exports = D.engine;
})(typeof window !== "undefined" ? window : globalThis);
