# dict-kindle

The German–English dictionary of `~/dict` and dict-android as a Kindle
dictionary: long-press a word in a German book and its entry comes up,
inflected forms included ("ging" opens "gehen").

- `build_kindle.py` writes the dictionary's source (an .opf and HTML with
  Kindle's index markup) from the database and the Kaikki download in
  `~/dict/data`.
- Amazon's `kindlegen` compiles that into the .mobi. Amazon no longer offers
  it; `vendor/kindlegen/` holds version 2.9 for Linux from
  <https://archive.org/download/kindlegen2.9/kindlegen_linux_2.6_i386_v2_9.tar.gz>
  (sha256 `9828db5a…042296`, the sum the Arch package records). Not committed.

## Build

    python3 -I build_kindle.py ../dict/data/dict.db ../dict/data/kaikki/German.jsonl.gz build/src
    vendor/kindlegen/kindlegen build/src/woerterbuch.opf -c1 -dont_append_source -o woerterbuch.mobi

The result is `build/src/woerterbuch.mobi`.

## Install

Copy the .mobi over USB into the Kindle's `documents/dictionaries` folder, then
choose it under Settings → Language & Dictionaries → Dictionaries → German.
It answers in books whose language is German.

## What is in it

- One entry per German word that stands alone as a headword in Ding, with up
  to 12 of the sub-entries it heads, main senses first.
- The inflected forms of the database's `forms` table, each listed under its
  dictionary form; forms with ß are listed in both spellings.
- German to English only, and single words only: the Kindle matches the word
  touched, so phrases and separable verbs written apart are not found.

## Licence

The code is licensed under the GNU General Public License, version 3. The
dictionary data keeps its own licences (Ding: GPL 2 or later; Wiktionary by way
of Kaikki.org: CC BY-SA 4.0); the dictionary's first page carries the
attribution, and anyone given the .mobi must get those terms with it.
