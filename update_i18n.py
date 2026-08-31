#!/usr/bin/env python3
"""
update_i18n.py

Companion to check_i18n.py. Walks every .html file in a folder, finds every
element tagged with data-i18n="key.path" or data-i18n-attr="attrName:key.path",
and WRITES the text actually present in the HTML back into the i18n JSON file
at that key path -- i.e. HTML is the source of truth, and the JSON is patched
to agree with it, instead of just being reported on.

Concretely, for every key found in the HTML:
  - If the key already resolves in the JSON and the value differs -> UPDATE it.
  - If the key does not resolve anywhere in the JSON            -> ADD it.
  - If the key resolves but to a non-string (dict/list)         -> SKIP it
    (printed under SKIPPED - BAD TYPE; needs a human to sort out).

--- Key resolution / placement (same convention as check_i18n.py) ---
  1. "shared" keys (nav.*, footer.*, ... - configurable via --shared-prefixes)
     live under json["shared"].
  2. Everything else is page-specific and lives under json[<page>], where
     <page> comes from <body data-page="..."> (kebab-case -> camelCase).
When a key doesn't exist yet, it is CREATED under whichever of those two
locations applies (same rule used to look it up).

--- *Html keys ---
If the last segment of a key ends in "Html" (e.g. "about.introHtml"), the
value written to JSON is the element's inner markup (tags kept), not just
its text -- matching the existing convention of storing raw HTML for those
keys. Every other key gets the element's plain, whitespace-collapsed text.
Note: this may reformat the markup slightly (quote style, whitespace,
self-closing tags) even when nothing meaningful changed -- check_i18n.py
will still report it as a MATCH either way, since it strips tags before
comparing.

--- Conflicts ---
"shared" keys are expected to be identical across every page that uses them.
If two HTML files disagree on the text for the same shared key, that's a
conflict. By default the first value encountered (files are processed in
sorted filename order) wins and every conflict is printed; use --on-conflict
to change that behavior.

--- Safety ---
This script previews changes by default and makes NO changes on disk unless
you pass --apply. When applying, it writes a .bak copy of the JSON first
unless you pass --no-backup.

--- Usage ---
    python3 update_i18n.py                              # preview only
    python3 update_i18n.py --apply                       # apply in current folder
    python3 update_i18n.py /path/to/site --apply
    python3 update_i18n.py --json data_en.json --apply
    python3 update_i18n.py --shared-prefixes nav,footer,common --apply
    python3 update_i18n.py --on-conflict last --apply
    python3 update_i18n.py --out data_en.new.json --apply   # write elsewhere

Run check_i18n.py afterwards to confirm everything now matches.
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
    """Strip HTML tags, unescape entities, collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_module.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_html_key(dotted_key: str) -> bool:
    """Keys whose final path segment ends in 'Html' are expected to hold
    raw markup (e.g. 'about.introHtml') rather than plain text."""
    return dotted_key.split(".")[-1].endswith("Html")


def extract_element_value(tag, dotted_key: str) -> str:
    """The value that should be written to JSON for a data-i18n element."""
    if is_html_key(dotted_key):
        raw = tag.decode_contents()
        return re.sub(r"\s+", " ", raw).strip()
    return normalize(tag.get_text(separator=" "))


def get_nested(data, dotted_key: str):
    """Walk a dotted/indexed path through nested dicts/lists (read-only).
    Returns (value, found_bool)."""
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
    Returns (value_or_None, found_bool, where_str_or_None)."""
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


def set_nested(root: dict, dotted_key: str, value) -> None:
    """Create/overwrite dicts & lists along dotted_key so that
    root[<path>] = value, creating containers as needed.
    List indices are numeric path segments, e.g. 'items.0.title'."""
    parts = dotted_key.split(".")
    cur = root
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part.isdigit():
            idx = int(part)
            if not isinstance(cur, list):
                raise TypeError(f"expected a list at '{'.'.join(parts[:i])}' to set index {idx}")
            while len(cur) <= idx:
                cur.append(None)
            if last:
                cur[idx] = value
            else:
                nxt_is_list = parts[i + 1].isdigit()
                if not isinstance(cur[idx], (dict, list)):
                    cur[idx] = [] if nxt_is_list else {}
                cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                raise TypeError(f"expected a dict at '{'.'.join(parts[:i])}' to set key '{part}'")
            if last:
                cur[part] = value
            else:
                nxt_is_list = parts[i + 1].isdigit()
                if part not in cur or not isinstance(cur[part], (dict, list)):
                    cur[part] = [] if nxt_is_list else {}
                cur = cur[part]


def target_section_for(key: str, page_section, shared_prefixes: set):
    """Where a NEW key should be created: 'shared' if its top-level segment
    is a shared prefix, otherwise the current page's section (or None if
    there isn't one)."""
    top = key.split(".")[0]
    if top in shared_prefixes:
        return "shared"
    return page_section


# ---------------------------------------------------------------- scan

def _record(occurrences, warnings, json_data, page_section, shared_prefixes, path, line, key, value):
    existing_value, found, where = resolve_key(json_data, page_section, key)
    if found and not isinstance(existing_value, str):
        occurrences.append({
            "key": key, "value": value, "file": path.name, "line": line,
            "found": True, "where": where, "existing_value": existing_value,
            "bad_type": True, "target": where,
        })
        return
    target = where if found else target_section_for(key, page_section, shared_prefixes)
    if target is None:
        warnings.append(
            f"{path.name}:{line}: key '{key}' isn't in the JSON yet and there's no "
            f"data-page on <body> to place it under; skipping."
        )
        return
    occurrences.append({
        "key": key, "value": value, "file": path.name, "line": line,
        "found": found, "where": where, "existing_value": existing_value,
        "bad_type": False, "target": target,
    })


def scan_files(html_files, json_data, shared_prefixes):
    occurrences = []
    warnings = []
    for path in html_files:
        raw = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.find("body")
        data_page = body.get("data-page") if body else None
        page_section = kebab_to_camel(data_page) if data_page else None
        if body and not data_page:
            warnings.append(
                f"{path.name}: <body> has no data-page attribute; only 'shared' "
                f"keys can be added/updated for this file."
            )

        for tag in soup.find_all(attrs={"data-i18n": True}):
            key = tag.get("data-i18n")
            line = tag.sourceline
            value = extract_element_value(tag, key)
            _record(occurrences, warnings, json_data, page_section, shared_prefixes, path, line, key, value)

        for tag in soup.find_all(attrs={"data-i18n-attr": True}):
            line = tag.sourceline
            spec = tag.get("data-i18n-attr")
            for piece in spec.split(","):
                piece = piece.strip()
                if ":" not in piece:
                    warnings.append(
                        f"{path.name}:{line}: malformed data-i18n-attr '{piece}' "
                        f"(expected attrName:key.path)"
                    )
                    continue
                attr_name, key = piece.split(":", 1)
                attr_name, key = attr_name.strip(), key.strip()
                value = normalize(tag.get(attr_name, ""))
                _record(occurrences, warnings, json_data, page_section, shared_prefixes, path, line, key, value)
    return occurrences, warnings


# ---------------------------------------------------------------- plan

def build_plan(occurrences, on_conflict):
    """Collapse occurrences into at most one write per (target, key),
    detecting conflicts where two files want different values at the
    same JSON location.
    Returns (plan, conflicts):
      plan      : {(target, key): occurrence_to_write}
      conflicts : {(target, key): [occurrence, occurrence, ...]}
    """
    plan = {}
    conflicts = {}
    for occ in occurrences:
        if occ["bad_type"]:
            continue
        loc = (occ["target"], occ["key"])
        if occ["found"] and occ["existing_value"] == occ["value"]:
            continue  # already correct
        if loc not in plan:
            plan[loc] = occ
            continue
        if plan[loc]["value"] == occ["value"]:
            continue  # same new value from another file, no conflict
        conflicts.setdefault(loc, [plan[loc]]).append(occ)
        if on_conflict == "last":
            plan[loc] = occ
        # "first" and "error" both keep plan[loc] as the first value seen
    return plan, conflicts


def apply_plan(json_data, plan):
    for (target, key), occ in plan.items():
        section_root = json_data.setdefault(target, {})
        set_nested(section_root, key, occ["value"])


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description="Sync an i18n JSON file to match the text actually written in the HTML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 update_i18n.py                 # preview only, no changes made\n"
            "  python3 update_i18n.py --apply\n"
            "  python3 update_i18n.py /path/to/site --apply\n"
            "  python3 update_i18n.py --json data_en.json --apply\n"
            "  python3 update_i18n.py --shared-prefixes nav,footer,common --apply\n"
            "  python3 update_i18n.py --on-conflict last --apply\n"
        ),
    )
    parser.add_argument("folder", nargs="?", default=".", help="Folder containing the .html files (default: current dir)")
    parser.add_argument("--json", default="data_en.json", help="i18n JSON filename, relative to folder unless absolute (default: data_en.json)")
    parser.add_argument("--out", default=None, help="Write the updated JSON here instead of overwriting the input file")
    parser.add_argument("--shared-prefixes", default="nav,footer",
                         help="Comma-separated top-level key segments that belong under json['shared'] (default: nav,footer)")
    parser.add_argument("--on-conflict", choices=["first", "last", "error"], default="first",
                         help="When HTML files disagree on the value for the same shared key: keep the first "
                              "one seen (default), keep the last one seen, or abort")
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this, the script only previews them.")
    parser.add_argument("--no-backup", action="store_true", help="Don't write a .bak copy of the JSON before overwriting")
    parser.add_argument("--verbose", action="store_true", help="List every added/updated key with old vs new value")
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

    shared_prefixes = {p.strip() for p in args.shared_prefixes.split(",") if p.strip()}

    occurrences, warnings = scan_files(html_files, json_data, shared_prefixes)
    bad_types = [o for o in occurrences if o["bad_type"]]
    plan, conflicts = build_plan(occurrences, args.on_conflict)

    if args.on_conflict == "error" and conflicts:
        print("CONFLICTS  (aborting - re-run with --on-conflict=first or last to proceed anyway)")
        print("-" * 70)
        for (target, key), occs in conflicts.items():
            print(f"  {target}.{key}")
            for o in occs:
                print(f"      {o['file']}:{o['line']}  -> {o['value']!r}")
        sys.exit(1)

    if warnings:
        print("WARNINGS")
        print("-" * 70)
        for w in warnings:
            print(f"  {w}")
        print()

    if bad_types:
        print("SKIPPED - BAD TYPE  (key resolves to a JSON object/array; left untouched)")
        print("-" * 70)
        for o in bad_types:
            print(f"  {o['file']}:{o['line']}  key = {o['key']}  (resolved to {type(o['existing_value']).__name__})")
        print()

    if conflicts:
        note = {"first": "kept the first value seen", "last": "kept the last value seen"}[args.on_conflict]
        print(f"CONFLICTS  ({note} - re-run with --on-conflict=error to abort instead)")
        print("-" * 70)
        for (target, key), occs in conflicts.items():
            print(f"  {target}.{key}")
            for o in occs:
                print(f"      {o['file']}:{o['line']}  -> {o['value']!r}")
        print()

    added = [(t, k, o) for (t, k), o in plan.items() if not o["found"]]
    updated = [(t, k, o) for (t, k), o in plan.items() if o["found"]]

    def show(items, label):
        if not items:
            return
        print(f"{label}  ({len(items)})")
        print("-" * 70)
        for t, k, o in items:
            if o["found"]:
                print(f"  {o['file']}:{o['line']}  {t}.{k}")
                print(f"      was : {o['existing_value']!r}")
                print(f"      now : {o['value']!r}")
            else:
                print(f"  {o['file']}:{o['line']}  {t}.{k}  (new)")
                print(f"      value : {o['value']!r}")
        print()

    if args.verbose or not args.apply:
        show(added, "WOULD ADD" if not args.apply else "ADDED")
        show(updated, "WOULD UPDATE" if not args.apply else "UPDATED")
    else:
        if added:
            print(f"Added   : {len(added)} key(s)")
        if updated:
            print(f"Updated : {len(updated)} key(s)")

    print("=" * 70)
    print(f"Files scanned    : {len(html_files)}")
    print(f"Keys to add      : {len(added)}")
    print(f"Keys to update   : {len(updated)}")
    print(f"Conflicts        : {len(conflicts)}")
    print(f"Skipped bad-type : {len(bad_types)}")
    print("=" * 70)

    if not args.apply:
        print("\nDry run only - no files were changed. Re-run with --apply to write these changes.")
        return

    apply_plan(json_data, plan)

    out_path = Path(args.out) if args.out else json_path
    if out_path == json_path and not args.no_backup:
        backup_path = json_path.with_name(json_path.name + ".bak")
        backup_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backup written to {backup_path}")

    out_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
