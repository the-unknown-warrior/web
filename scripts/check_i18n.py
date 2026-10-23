#!/usr/bin/env python3
"""
check_i18n.py

Walks every .html file in a folder, finds every element tagged with
data-i18n="key.path" or data-i18n-attr="attrName:key.path", and checks
whether the text actually written in the HTML matches the value stored
at that key path in an i18n JSON file (e.g. data_en.json).

HTML is treated as the source of truth. Anything that doesn't match
is printed as a MISMATCH; anything referenced in HTML but missing
from the JSON is printed as MISSING.

--- How keys resolve ---
Two conventions are supported, both seen in this project:
  1. "shared" keys (nav.*, footer.*, ...) -> looked up under json["shared"]
  2. page-specific keys (hero.*, cta.*, culture.items.0.title, ...)
     -> looked up under json[<page>], where <page> is derived from the
     <body data-page="..."> attribute (kebab-case -> camelCase), e.g.
     data-page="background-changer" -> json["backgroundChanger"]

For every key, "shared" is tried first, then the page section. This
matches the pattern observed across the supplied files (nav/footer
keys live only under "shared"; everything else lives under the page).
Dotted paths may include numeric segments for list indices
(e.g. "culture.items.0.desc" -> json[page]["culture"]["items"][0]["desc"]).

--- Usage ---
    python3 check_i18n.py                       # run in current folder, uses data_en.json
    python3 check_i18n.py /path/to/site
    python3 check_i18n.py /path/to/site --json data_en.json
    python3 check_i18n.py --verbose              # also print every MATCH
    python3 check_i18n.py --show-unused          # also list JSON keys no HTML file references

Exit code is non-zero if any mismatches or missing keys were found,
so this can be dropped straight into CI.
"""

import argparse
import html as html_module
import json
import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit(
        "This script needs BeautifulSoup4. Install it with:\n"
        "    pip install beautifulsoup4"
    )


# ---------------------------------------------------------------- helpers

def kebab_to_camel(s: str) -> str:
    """'background-changer' -> 'backgroundChanger'"""
    parts = s.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def normalize(s: str) -> str:
    """Strip any HTML tags, unescape entities, collapse whitespace.

    Used on BOTH sides of every comparison so that:
      - a JSON value containing raw markup (the *Html keys, e.g.
        "One holding company.<br><span>An index...</span>") compares
        fairly against the rendered element text
      - differences in line breaks / indentation between the HTML file
        and the JSON file don't produce false positives
    """
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_module.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_nested(data, dotted_key: str):
    """Walk a dotted/indexed path through nested dicts/lists.

    Returns (value, found_bool).
    """
    cur = data
    for part in dotted_key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None, False
    return cur, True


def resolve_key(json_data, page_section: str, dotted_key: str):
    """Try shared.<key> first, then <page_section>.<key>.

    Returns (value_or_None, found_bool, where_str)
    """
    shared = json_data.get("shared", {})
    val, found = get_nested(shared, dotted_key)
    if found:
        return val, True, "shared"

    if page_section:
        page_data = json_data.get(page_section)
        if page_data is not None:
            val, found = get_nested(page_data, dotted_key)
            if found:
                return val, True, page_section

    return None, False, None


def mark_used(used_paths, where, dotted_key):
    used_paths.add((where, dotted_key))


# ---------------------------------------------------------------- core

def check_file(path: Path, json_data: dict, args, used_paths: set, results: dict):
    raw = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")

    body = soup.find("body")
    data_page = body.get("data-page") if body else None
    page_section = kebab_to_camel(data_page) if data_page else None

    if body and not data_page:
        results["warnings"].append(
            f"{path.name}: <body> has no data-page attribute; only 'shared' keys will resolve."
        )

    # --- data-i18n (element text) ---
    for tag in soup.find_all(attrs={"data-i18n": True}):
        key = tag.get("data-i18n")
        line = tag.sourceline
        html_text = normalize(tag.get_text(separator=" "))

        json_val, found, where = resolve_key(json_data, page_section, key)
        if not found:
            results["missing"].append((path.name, line, key, html_text))
            continue

        mark_used(used_paths, where, key)

        if not isinstance(json_val, str):
            results["bad_type"].append((path.name, line, key, type(json_val).__name__))
            continue

        json_text = normalize(json_val)
        if html_text != json_text:
            results["mismatch"].append((path.name, line, key, html_text, json_text))
        elif args.verbose:
            results["match"].append((path.name, line, key, html_text))

    # --- data-i18n-attr (attribute text, e.g. alt:key or aria-label:key) ---
    for tag in soup.find_all(attrs={"data-i18n-attr": True}):
        line = tag.sourceline
        spec = tag.get("data-i18n-attr")
        for piece in spec.split(","):
            piece = piece.strip()
            if ":" not in piece:
                results["warnings"].append(
                    f"{path.name}:{line}: malformed data-i18n-attr '{piece}' (expected attrName:key.path)"
                )
                continue
            attr_name, key = piece.split(":", 1)
            attr_name = attr_name.strip()
            key = key.strip()

            html_val = tag.get(attr_name, "")
            html_text = normalize(html_val)

            json_val, found, where = resolve_key(json_data, page_section, key)
            if not found:
                results["missing"].append((path.name, line, key, html_text))
                continue

            mark_used(used_paths, where, key)

            if not isinstance(json_val, str):
                results["bad_type"].append((path.name, line, key, type(json_val).__name__))
                continue

            json_text = normalize(json_val)
            if html_text != json_text:
                results["mismatch"].append((path.name, line, key, html_text, json_text))
            elif args.verbose:
                results["match"].append((path.name, line, key, html_text))


def collect_all_leaf_paths(data, prefix=""):
    """For --show-unused: enumerate every 'section.dotted.path' -> string leaf in the JSON."""
    paths = []
    if isinstance(data, dict):
        for k, v in data.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            paths.extend(collect_all_leaf_paths(v, new_prefix))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            new_prefix = f"{prefix}.{i}"
            paths.extend(collect_all_leaf_paths(v, new_prefix))
    else:
        if isinstance(data, str):
            paths.append(prefix)
    return paths


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Check HTML text against an i18n JSON file.")
    parser.add_argument("folder", nargs="?", default=".", help="Folder containing the .html files (default: current dir)")
    parser.add_argument("--json", default="data_en.json", help="i18n JSON filename, relative to folder unless absolute (default: data_en.json)")
    parser.add_argument("--verbose", action="store_true", help="Also print every match, not just mismatches")
    parser.add_argument("--show-unused", action="store_true", help="List JSON string keys that no HTML file references")
    args = parser.parse_args()

    folder = Path(args.folder)
    json_path = Path(args.json)
    if not json_path.is_absolute():
        json_path = folder / json_path

    if not json_path.exists():
        sys.exit(f"JSON file not found: {json_path}")

    json_data = json.loads(json_path.read_text(encoding="utf-8"))

    html_files = sorted(folder.glob("*.html"))
    if not html_files:
        sys.exit(f"No .html files found in {folder}")

    results = {"mismatch": [], "missing": [], "bad_type": [], "warnings": [], "match": []}
    used_paths = set()

    for f in html_files:
        check_file(f, json_data, args, used_paths, results)

    # ---- report ----
    if results["warnings"]:
        print("WARNINGS")
        print("-" * 70)
        for w in results["warnings"]:
            print(f"  {w}")
        print()

    if args.verbose and results["match"]:
        print("MATCHES")
        print("-" * 70)
        for fname, line, key, text in results["match"]:
            print(f"  OK   {fname}:{line}  {key}")
        print()

    if results["mismatch"]:
        print("MISMATCHES  (HTML text differs from JSON)")
        print("-" * 70)
        for fname, line, key, html_text, json_text in results["mismatch"]:
            print(f"  {fname}:{line}  key = {key}")
            print(f"      HTML : {html_text}")
            print(f"      JSON : {json_text}")
            print()

    if results["missing"]:
        print("MISSING  (referenced in HTML, not found anywhere in JSON)")
        print("-" * 70)
        for fname, line, key, html_text in results["missing"]:
            print(f"  {fname}:{line}  key = {key}")
            print(f"      HTML : {html_text}")
            print()

    if results["bad_type"]:
        print("BAD TYPE  (key resolves to a JSON object/array, not a string)")
        print("-" * 70)
        for fname, line, key, typename in results["bad_type"]:
            print(f"  {fname}:{line}  key = {key}  (resolved to {typename})")
        print()

    if args.show_unused:
        all_leaf_paths = set()
        for section, section_data in json_data.items():
            for leaf in collect_all_leaf_paths(section_data):
                all_leaf_paths.add((section, leaf))
        unused = sorted(all_leaf_paths - used_paths)
        if unused:
            print("UNUSED JSON KEYS  (in JSON, not referenced by any HTML file)")
            print("-" * 70)
            for section, key in unused:
                print(f"  {section}.{key}")
            print()

    total_checked = len(results["mismatch"]) + len(results["missing"]) + len(results["bad_type"]) + len(results["match"])
    print("=" * 70)
    print(f"Files scanned : {len(html_files)}")
    print(f"Keys checked  : {total_checked if args.verbose else '(re-run with --verbose for full count)'}")
    print(f"Mismatches    : {len(results['mismatch'])}")
    print(f"Missing keys  : {len(results['missing'])}")
    print(f"Bad type      : {len(results['bad_type'])}")
    print("=" * 70)

    if results["mismatch"] or results["missing"] or results["bad_type"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
