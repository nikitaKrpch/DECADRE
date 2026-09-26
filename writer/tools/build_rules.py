"""Build the writer's JavaScript rules from the reviewed Excel workbook.

Sources, in priority order (a pattern already used by an earlier rule is skipped):
  1. "Sheet1"        word | level | reason | replacement   (main list, ids R01, R02, ...)
                     An empty reason / level is filled from the "Mots justes" tab,
                     matched on the words (the ids differ between the two tabs).
  2. "Familles"      typical expressions per family of problems   (ids F-...)
  3. "Dictionnaires" words from the institute's lists             (ids D-...)
                     Uses the "Décision" column (garder -> strong, hint -> hint,
                     retirer -> skipped); an empty decision falls back to Claude's
                     suggestion. The reason is the "Raison" column, or a default per
                     list: the "Pourquoi (Claude)" notes are for reviewers, not journalists.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "Rule_Review.xlsx"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "static" / "rules.js"
SOURCE_SHEET = "Sheet1"
SEPARATOR = ";"
FIRST_DATA_ROW = 4  # "Mots justes", "Familles", "Dictionnaires": intro, legend, headers above

DEFAULT_SOURCE = "Livret décadréE 2023"
DICTIONARY_SOURCE = "Livret décadréE 2023, p. 8-9 (enjeux)"
DICTIONARY_REASONS = {
	"animalisant": "Animalise l'auteur et en fait un être hors norme, ce qui masque la dimension sociale des violences.",
	"minimisant": "Minimise la gravité des violences.",
	"santé mentale": "Explique la violence par la maladie ou la perte de contrôle, ce qui déresponsabilise l'auteur.",
	"substances": "L'alcool ou la drogue ne justifient pas la violence : à mentionner seulement si c'est utile à l'information.",
}


def split_values(value: Any, separator: str = SEPARATOR) -> list[str]:
	"""Split a workbook cell into cleaned values."""
	if value is None:
		return []
	return [part.strip() for part in str(value).split(separator) if part.strip()]


def fold(text: str) -> str:
	"""Lowercase, no accents, straight apostrophes: used to compare words across tabs."""
	text = unicodedata.normalize("NFD", str(text).lower().replace("’", "'"))
	return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").split())


def slug(text: str) -> str:
	return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def clean_note(value: Any) -> str:
	"""Cell text, or "" for empty cells and placeholders such as "(à écrire ...)"."""
	text = "" if value is None else str(value).strip()
	return "" if text.startswith("(") else text


def cell(row: tuple, index: int) -> Any:
	return row[index] if index < len(row) else None


def parse_severity(value: Any) -> dict[str, str] | str | None:
	""""strong" / "hint" -> that string. "strong (dispute) / hint (conflit)" -> {word: severity}."""
	text = "" if value is None else str(value).strip().lower()
	if text in {"strong", "hint"}:
		return text
	per_word = {}
	for level, words in re.findall(r"(strong|hint)\s*\(([^)]*)\)", text):
		for word in split_values(words, ","):
			per_word[fold(word)] = level
	return per_word or None


def load_booklet_notes(workbook) -> dict[str, dict[str, Any]]:
	"""Map every pattern of the "Mots justes" tab to its reason, severity and page."""
	notes = {}
	if "Mots justes" not in workbook.sheetnames:
		return notes
	for row in workbook["Mots justes"].iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
		patterns = split_values(cell(row, 1)) + split_values(cell(row, 6))
		page = cell(row, 3)
		if isinstance(page, float) and page.is_integer():
			page = int(page)  # a page typed as a number comes back as 17.0
		note = {
			"reason": clean_note(cell(row, 8)),
			"severity": parse_severity(cell(row, 7)),
			"source": f"{DEFAULT_SOURCE}, p. {page}" if page else DEFAULT_SOURCE,
		}
		for pattern in patterns:
			notes.setdefault(fold(re.sub(r"\(.*?\)", "", pattern)), note)
	return notes


def booklet_note_for(patterns: list[str], notes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
	for pattern in patterns:
		if fold(pattern) in notes:
			return notes[fold(pattern)]
	return None


def build_main_rules(workbook, notes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
	"""Rules from "Sheet1", completed from the "Mots justes" tab where cells are empty."""
	if SOURCE_SHEET not in workbook.sheetnames:
		raise ValueError(f"Workbook does not contain the {SOURCE_SHEET!r} sheet")

	rows = workbook[SOURCE_SHEET].iter_rows(values_only=True)
	headers = next((row for row in rows if any(value is not None for value in row)), None)
	if not headers:
		return []

	column_indexes = {str(header).strip().lower(): index for index, header in enumerate(headers) if header is not None}
	required_columns = {"word", "level", "reason", "replacement"}
	missing_columns = required_columns - column_indexes.keys()
	if missing_columns:
		missing = ", ".join(sorted(missing_columns))
		raise ValueError(f"Missing required columns: {missing}")

	rules = []
	for rule_number, row in enumerate(rows, start=1):
		patterns = split_values(cell(row, column_indexes["word"]))
		if not patterns:
			continue

		note = booklet_note_for(patterns, notes) or {}
		reason = clean_note(cell(row, column_indexes["reason"])) or note.get("reason", "")
		replacements = split_values(cell(row, column_indexes["replacement"]))
		base = {
			"id": f"R{rule_number:02d}",
			"category": "mots justes",
			"replacements": replacements,
			"reason": reason,
			"source": note.get("source", DEFAULT_SOURCE),
		}

		level = parse_severity(cell(row, column_indexes["level"]))
		if level is None:
			level = note.get("severity")
		if isinstance(level, dict):
			# "strong (dispute) / hint (conflit)": one rule per severity, same reason
			groups: dict[str, list[str]] = {}
			for pattern in patterns:
				groups.setdefault(level.get(fold(pattern), "strong"), []).append(pattern)
			for severity, group in groups.items():
				suffix = "" if severity == "strong" or len(groups) == 1 else "-hint"
				rules.append({**base, "id": base["id"] + suffix, "patterns": group, "severity": severity})
		else:
			rules.append({**base, "patterns": patterns, "severity": level if level in {"strong", "hint"} else "strong"})

	return rules


def build_family_rules(workbook) -> list[dict[str, Any]]:
	"""One rule per expression of the "Familles" tab."""
	rules = []
	if "Familles" not in workbook.sheetnames:
		return rules
	for row in workbook["Familles"].iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
		expression = clean_note(cell(row, 2))
		if not expression:
			continue
		severity = parse_severity(cell(row, 3))
		enjeu = clean_note(cell(row, 1))
		rules.append({
			"id": f"F-{slug(expression)}",
			"category": clean_note(cell(row, 0)),
			"patterns": [expression],
			"replacements": split_values(cell(row, 5), "/"),
			"reason": clean_note(cell(row, 4)),
			"source": f"{DEFAULT_SOURCE}, p. 8-9 ({enjeu})" if enjeu else DEFAULT_SOURCE,
			"severity": severity if severity in {"strong", "hint"} else "hint",
		})
	return rules


def build_dictionary_rules(workbook) -> tuple[list[dict[str, Any]], int]:
	"""Rules from the "Dictionnaires" tab. Returns (rules, how many used Claude's suggestion)."""
	rules, fallbacks = [], 0
	if "Dictionnaires" not in workbook.sheetnames:
		return rules, fallbacks
	for row in workbook["Dictionnaires"].iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
		word = clean_note(cell(row, 0))
		if not word:
			continue
		decision = clean_note(cell(row, 4)).lower()
		if not decision:
			decision = clean_note(cell(row, 2)).lower()
			fallbacks += 1
		if decision not in {"garder", "hint"}:
			continue
		lists = split_values(cell(row, 1), ",")
		category = lists[0] if lists else ""
		rules.append({
			"id": f"D-{slug(word)}",
			"category": category,
			"patterns": [word],
			"replacements": split_values(cell(row, 5), "/"),
			"reason": clean_note(cell(row, 6)) or DICTIONARY_REASONS.get(category, ""),
			"source": DICTIONARY_SOURCE,
			"severity": "strong" if decision == "garder" else "hint",
		})
	return rules, fallbacks


def drop_duplicates(rules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
	"""Keep each pattern only in its first rule (Sheet1 > Familles > Dictionnaires)."""
	seen, kept, dropped = set(), [], []
	for rule in rules:
		patterns = []
		for pattern in rule["patterns"]:
			key = fold(pattern)
			if key in seen:
				dropped.append(f"{rule['id']}: {pattern}")
			else:
				seen.add(key)
				patterns.append(pattern)
		if patterns:
			kept.append({**rule, "patterns": patterns})
	return kept, dropped


def build_rules(input_path: Path) -> list[dict[str, Any]]:
	"""Read every rule source from the workbook and convert them to frontend rules."""
	workbook = load_workbook(input_path, data_only=True, read_only=True)
	notes = load_booklet_notes(workbook)
	main_rules = build_main_rules(workbook, notes)
	family_rules = build_family_rules(workbook)
	dictionary_rules, fallbacks = build_dictionary_rules(workbook)
	rules, dropped = drop_duplicates(main_rules + family_rules + dictionary_rules)

	no_reason = [rule["id"] for rule in rules if not rule["reason"]]
	print(f"Sheet1: {len(main_rules)} · Familles: {len(family_rules)} · Dictionnaires: {len(dictionary_rules)}"
		f" ({fallbacks} without a decision, Claude's suggestion used)")
	if dropped:
		print(f"Duplicates skipped ({len(dropped)}): {', '.join(dropped)}")
	if no_reason:
		print(f"WARNING, no reason ({len(no_reason)}): {', '.join(no_reason)}")
	return rules


def write_rules(output_path: Path, rules: list[dict[str, Any]]) -> None:
	"""Write rules as a JavaScript module consumed by the writer frontend."""
	output_path.parent.mkdir(parents=True, exist_ok=True)
	serialized_rules = json.dumps(rules, ensure_ascii=False, indent=2)
	output_path.write_text(
		"// GENERATED by writer/tools/build_rules.py from Rule_Review.xlsx: do not edit by hand.\n"
		"(function () {\n"
		'  "use strict";\n'
		"  const D = (window.Decadre = window.Decadre || {});\n"
		f"  D.rules = {serialized_rules};\n"
		"})();\n",
		encoding="utf-8",
	)


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT, help="Input Rule_Review.xlsx path")
	parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT, help="Output rules.js path")
	args = parser.parse_args()

	rules = build_rules(args.input)
	write_rules(args.output, rules)
	print(f"Wrote {len(rules)} rules to {args.output}")


if __name__ == "__main__":
	main()
