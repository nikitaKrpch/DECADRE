// Tests for writer/static/engine.js.  Run: node writer/tests/engine.test.js
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");

const engine = require(path.join(__dirname, "../static/engine.js"));
global.window = globalThis;
require(path.join(__dirname, "../static/rules.js"));
require(path.join(__dirname, "../static/samples.js"));
const realRules = globalThis.Decadre.rules;

const rule = (id, patterns, extra = {}) => ({ id, patterns, replacements: [], severity: "strong", reason: "", ...extra });
const matches = (text, rules) => engine.findIssues(text, rules).map((i) => i.match);

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log("  ✓", name);
  } catch (err) {
    console.log("  ✗", name);
    console.log("     ", err.message.split("\n").join("\n      "));
    process.exitCode = 1;
  }
}

console.log("engine.findIssues");

test("accents and capitals do not matter", () => {
  assert.deepEqual(matches("La VICTIME PRESUMEE a parlé.", [rule("R", ["victime présumée"])]), ["VICTIME PRESUMEE"]);
});

test("whole words only: viol does not match violence, violet, violon", () => {
  assert.deepEqual(matches("violence, violet, violon, viol.", [rule("R", ["viol"])]), ["viol"]);
});

test("plural and feminine forms are found automatically", () => {
  const r = [rule("R", ["allégation", "victime présumée", "fléau", "pervers"])];
  assert.deepEqual(matches("Des allégations. Les victimes présumées. Ces fléaux. Une perverse.", r),
    ["allégations", "victimes présumées", "fléaux", "perverse"]);
});

test("common verb forms are found from the infinitive", () => {
  const r = [rule("R", ["peloter", "caresser", "embrasser"])];
  assert.deepEqual(matches("Il l'a pelotée, il caressait, ils l'ont embrassé.", r), ["pelotée", "caressait", "embrassé"]);
});

test("nouns that are also verbs: dispute finds disputait, avoue finds avouait", () => {
  const r = [rule("R", ["dispute", "elle avoue"])];
  assert.deepEqual(matches("Ils se disputaient. Elle avouait.", r), ["disputaient", "Elle avouait"]);
});

test("-al adjectives: familial finds familiaux", () => {
  assert.deepEqual(matches("Des drames familiaux.", [rule("R", ["familial"])]), ["familiaux"]);
});

test("* matches any word ending", () => {
  assert.deepEqual(matches("forcené, forcenés, forcenée", [rule("R", ["forcen*"])]), ["forcené", "forcenés", "forcenée"]);
});

test("multi-word patterns match across line breaks and several spaces", () => {
  assert.deepEqual(matches("un crime\npassionnel, un crime   passionnel", [rule("R", ["crime passionnel"])]),
    ["crime\npassionnel", "crime   passionnel"]);
});

test("curly and straight apostrophes are the same", () => {
  const r = [rule("R", ["faire l’amour"])];
  assert.deepEqual(matches("faire l'amour / faire l’amour", r), ["faire l'amour", "faire l’amour"]);
});

test("a word after an elision is found (L'auteur présumé)", () => {
  assert.deepEqual(matches("L'auteur présumé a nié.", [rule("R", ["auteur présumé"])]), ["auteur présumé"]);
});

test("positions point at the original text", () => {
  const text = "Élément : « Drame » à Genève, drames, DRAME.";
  for (const is of engine.findIssues(text, [rule("R", ["drame"])])) {
    assert.equal(text.slice(is.start, is.end), is.match);
  }
});

test("inQuote inside « », “ ” and straight quotes, not outside", () => {
  const text = "« un monstre » puis “un monstre” puis \"un monstre\" et un monstre.";
  assert.deepEqual(engine.findIssues(text, [rule("R", ["monstre"])]).map((i) => i.inQuote), [true, true, true, false]);
});

test("an unclosed « stops at the end of its paragraph", () => {
  const text = "« Il a dit que c'était horrible.\n\nLe forcené a été arrêté.";
  const [is] = engine.findIssues(text, [rule("R", ["forcené"])]);
  assert.equal(is.inQuote, false);
});

test("non-breaking spaces inside « » are handled", () => {
  const text = "« un monstre » et un monstre";
  assert.deepEqual(engine.findIssues(text, [rule("R", ["un monstre"])]).map((i) => i.inQuote), [true, false]);
});

test("overlaps: longest match wins, results sorted and non-overlapping", () => {
  const r = [rule("A", ["passionnel"]), rule("B", ["crime passionnel"])];
  const out = engine.findIssues("un crime passionnel et un drame passionnel", r);
  assert.deepEqual(out.map((i) => i.ruleId + ":" + i.match), ["B:crime passionnel", "A:passionnel"]);
  for (let i = 1; i < out.length; i++) assert.ok(out[i].start >= out[i - 1].end);
});

test("same length overlap: strong wins over hint", () => {
  const r = [rule("H", ["dispute"], { severity: "hint" }), rule("S", ["dispute"])];
  assert.deepEqual(engine.findIssues("une dispute", r).map((i) => i.ruleId), ["S"]);
});

test("rule.exact turns automatic endings off", () => {
  assert.deepEqual(matches("conflits et conflit", [rule("R", ["conflit"], { exact: true })]), ["conflit"]);
});

test("issue has every field the UI reads", () => {
  const [is] = engine.findIssues("un drame", [rule("R8", ["drame"], { replacements: ["féminicide"], reason: "r", source: "s" })]);
  assert.deepEqual(Object.keys(is).sort(),
    ["category", "end", "inQuote", "key", "match", "origin", "reason", "replacements", "ruleId", "severity", "source", "start"]);
  assert.equal(is.key, "R8:3");
});

test("never throws on odd input", () => {
  assert.deepEqual(engine.findIssues("", realRules), []);
  assert.deepEqual(engine.findIssues(null, realRules), []);
  assert.deepEqual(engine.findIssues("texte", null), []);
  engine.findIssues("😀 ﬁ ǅ İstanbul \u0000 ((( [[ *", [rule("R", ["(((", "[", "*", ""]), null, {}]);
});

test("real rules.js on the demo article: positions valid, no overlaps", () => {
  const text = globalThis.Decadre.samples[0].text;
  const out = engine.findIssues(text, realRules);
  assert.ok(out.length > 0, "expected some issues on the demo article");
  for (let i = 0; i < out.length; i++) {
    assert.equal(text.slice(out[i].start, out[i].end), out[i].match);
    if (i) assert.ok(out[i].start >= out[i - 1].end);
  }
});

test("fast: long article (~3,500 words) with real rules under 50 ms", () => {
  const text = Array(25).fill(globalThis.Decadre.samples[0].text).join("\n\n");
  engine.findIssues(text, realRules); // warm-up (regex compilation)
  const t = process.hrtime.bigint();
  for (let k = 0; k < 10; k++) engine.findIssues(text, realRules);
  const ms = Number(process.hrtime.bigint() - t) / 1e6 / 10;
  assert.ok(ms < 50, `took ${ms.toFixed(1)} ms`);
  console.log(`      (${text.split(/\s+/).length} words, ${ms.toFixed(1)} ms per call)`);
});

console.log(`\n${passed} passed${process.exitCode ? ", some FAILED" : ""}`);
