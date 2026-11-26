#!/usr/bin/env python3
"""Write the source of a Kindle German-English dictionary from the database of
~/dict (or dict-android) and the Kaikki download it was built from.

Usage: python3 -I build_kindle.py DICT.db German.jsonl.gz OUT_DIR

OUT_DIR gets woerterbuch.opf and the HTML it lists; kindlegen turns the .opf
into the .mobi (see README.md).

One entry per German word that stands alone as a headword in Ding, holding the
sub-entries it heads (main senses first). The inflected forms from the
database's `forms` table are listed with their dictionary form, which is what
lets the Kindle open "gehen" from "ging".
"""
import gzip
import html
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

MAX_SENSES = 12         # per entry
MAX_FORMS = 200         # per entry; kindlegen stops at 255
ENTRIES_PER_FILE = 5000

# As in tools/build_db.py.
ANNOTATION = re.compile(r"\{[^}]*\}|\[[^\]]*\]|\([^)]*\)")
FILLER = {"sich", "etw", "jdn", "jdm", "jds", "jd", "jmd", "jmdn", "jmdm", "jmds"}
WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
WORD_SS = re.compile(r"[^\W_]*ß[^\W_]*")

IDX_NS = "https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf"
MBP_NS = "https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf"


def headwords(de_sub):
    """(word, n) for each synonym of a sub-entry that is one word; n counts the synonyms."""
    for n, synonym in enumerate(ANNOTATION.sub(" ", de_sub).split(";")):
        words = [w for w in WORD.findall(synonym) if w.lower() not in FILLER]
        if len(words) == 1 and "…" not in synonym and len(words[0]) <= 40:
            yield words[0], n


def read_entries(db):
    """key (lowercased headword) -> {"word": spelling, "senses": [(rank, de, en)]}."""
    entries = {}
    for line_id, de, en in db.execute("SELECT id, de, en FROM lines ORDER BY id"):
        de_subs, en_subs = de.split(" | "), en.split(" | ")
        for sub, de_sub in enumerate(de_subs):
            en_sub = en_subs[sub] if sub < len(en_subs) else ""
            if not en_sub:
                continue
            for word, n in headwords(de_sub):
                # Main entry before sub-entry, first synonym before later ones; then the
                # longest lines (the main senses), as the database numbers them.
                rank = ((2 if sub else 0) + (1 if n else 0), line_id, sub)
                entry = entries.setdefault(word.lower(), {"word": word, "senses": []})
                entry["senses"].append((rank, de_sub, en_sub))
    for entry in entries.values():
        entry["senses"].sort()
        entry["main"] = entry["senses"][0][0][0] < 2
    return entries


def read_eszett(kaikki_path):
    """Spelling with ss -> the spellings with ß it may stand for.

    The forms table writes ß as ss; books don't.
    """
    out = defaultdict(set)
    with gzip.open(kaikki_path, "rt", encoding="utf-8") as f:
        for line in f:
            if "ß" not in line:
                continue
            for word in WORD_SS.findall(line):
                word = word.lower()
                out[word.replace("ß", "ss")].add(word)
    return out


def read_forms(db, entries, eszett):
    """entry key -> the inflected forms that lead to it, as they are spelled in a book."""
    forms = defaultdict(dict)  # key -> {spelling: None}, in table order
    for fold, form, lemma in db.execute("SELECT fold, form, lemma FROM forms ORDER BY lemma, kind, fold"):
        key = lemma.lower()
        if key not in entries:
            continue
        spelling = form or fold
        for variant in (spelling, *sorted(eszett.get(spelling, ()))):
            own = entries.get(variant)
            if own and own["main"] and variant != key:
                continue  # a word in its own right ("gegangen", "Morgen"): its own entry answers
            # Nouns are capitalised wherever they stand; the Kindle folds case for the rest.
            forms[key][variant.capitalize() if lemma[:1].isupper() else variant] = None
    return forms


def drop_shadowed(entries, forms):
    """Entries that are only an inflected form listed under a main entry ("Häuser {pl}"):
    the form's lemma answers instead, and says more."""
    listed = {f.lower() for key in forms for f in forms[key]}
    return {k: e for k, e in entries.items() if e["main"] or k not in listed}


def marked(text):
    """Bold, except Ding's {grammar}, [field] and (comments), and the punctuation between."""
    out, at = [], 0
    for m in [*ANNOTATION.finditer(text), None]:
        plain = text[at:m.start() if m else len(text)]
        # Bold from the first letter to the last: "; Zuhause " keeps its "; " and spaces outside.
        inner = re.search(r"\w(?:.*\w)?\.?", plain, re.S)
        if inner:
            out.append("%s<b>%s</b>%s" % (html.escape(plain[:inner.start()]), html.escape(inner.group()),
                                          html.escape(plain[inner.end():])))
        else:
            out.append(html.escape(plain))
        if m:
            out.append(html.escape(m.group()))
            at = m.end()
    return "".join(out)


def entry_html(n, entry, forms):
    senses, seen = [], set()
    for _rank, de, en in entry["senses"]:
        if (de, en) not in seen:
            seen.add((de, en))
            senses.append("<p>%s &#8212; %s</p>" % (marked(de), html.escape(en)))
        if len(senses) == MAX_SENSES:
            break
    infl = ""
    if forms:
        infl = "<idx:infl>%s</idx:infl>" % "".join(
            '<idx:iform value="%s"/>' % html.escape(f, quote=True) for f in list(forms)[:MAX_FORMS])
    return ('<idx:entry name="default" scriptable="yes" spell="yes"><a id="e%d"></a>'
            '<idx:orth value="%s">%s</idx:orth>\n%s\n</idx:entry>\n<hr/>\n'
            % (n, html.escape(entry["word"], quote=True), infl, "\n".join(senses)))


PAGE = """<html xmlns:idx="%s" xmlns:mbp="%s">
<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<style>p { margin: 0; text-indent: 0; } hr { margin: 0.4em 0; }</style></head>
<body><mbp:frameset>
%%s</mbp:frameset></body></html>
""" % (IDX_NS, MBP_NS)

ABOUT = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/></head><body>
<h1>Wörterbuch</h1>
<p>German–English, %(entries)s entries and %(forms)s inflected forms.</p>
<p>Dictionary: Ding German–English, version %(ding)s. © Frank Richter, 1995–2026.
GNU General Public License, version 2 or later. https://dict.zero-g.net/</p>
<p>Inflected forms: Wiktionary, by way of Kaikki.org. Creative Commons
Attribution-ShareAlike 4.0. https://kaikki.org/</p>
<p>Built by build_kindle.py (dict-kindle), under the GNU General Public License, version 3.</p>
</body></html>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Wörterbuch Deutsch–Englisch (Ding)</dc:title>
<dc:creator>Frank Richter; Wiktionary</dc:creator>
<dc:language>de</dc:language>
<dc:identifier id="uid">link.darmok.dict.kindle.de-en</dc:identifier>
<dc:rights>GPL-2.0-or-later (Ding); CC BY-SA 4.0 (Wiktionary)</dc:rights>
<x-metadata>
<DictionaryInLanguage>de</DictionaryInLanguage>
<DictionaryOutLanguage>en</DictionaryOutLanguage>
<DefaultLookupIndex>default</DefaultLookupIndex>
</x-metadata>
</metadata>
<manifest>
%(items)s
</manifest>
<spine>
%(refs)s
</spine>
</package>
"""


def main():
    db_path, kaikki_path, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.html"):
        old.unlink()
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    entries = read_entries(db)
    forms = read_forms(db, entries, read_eszett(kaikki_path))
    entries = drop_shadowed(entries, forms)

    names = ["about"]
    ding = db.execute("SELECT value FROM meta WHERE key = 'ding_version'").fetchone()[0]
    n_forms = sum(len(list(forms[k])[:MAX_FORMS]) for k in entries if k in forms)
    (out_dir / "about.html").write_text(
        ABOUT % {"entries": f"{len(entries):,}", "forms": f"{n_forms:,}", "ding": html.escape(ding)},
        encoding="utf-8")
    keys = sorted(entries)
    for start in range(0, len(keys), ENTRIES_PER_FILE):
        name = "entries%03d" % (start // ENTRIES_PER_FILE)
        body = "".join(entry_html(start + i, entries[k], forms.get(k))
                       for i, k in enumerate(keys[start:start + ENTRIES_PER_FILE]))
        (out_dir / f"{name}.html").write_text(PAGE % body, encoding="utf-8")
        names.append(name)
    (out_dir / "woerterbuch.opf").write_text(OPF % {
        "items": "\n".join(f'<item id="{n}" href="{n}.html" media-type="application/xhtml+xml"/>' for n in names),
        "refs": "\n".join(f'<itemref idref="{n}"/>' for n in names),
    }, encoding="utf-8")
    size = sum(p.stat().st_size for p in out_dir.glob("*.html"))
    print(f"{out_dir}: {len(entries)} entries, {n_forms} inflected forms, "
          f"{len(names)} files, {size / 1e6:.1f} MB of source")


if __name__ == "__main__":
    main()
