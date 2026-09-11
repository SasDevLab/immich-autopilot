#!/usr/bin/env python3
"""Build a dictionary from a public frequency list, keeping only the words that
actually describe pictures.

Hand-writing a dictionary works but ties the result to whoever wrote it. A
frequency list is free of that, at the cost of being mostly useless: the top of
any such list is "and, not, that, of, the", and further down sit plenty of
abstractions no photograph can show.

The filter is the model itself. A word worth keeping is one that *discriminates*
- very close to some photos and far from others. A vague word sits at the same
distance from everything, and its similarity across the library has almost no
spread. So: embed the candidates, measure the spread of each against a sample of
real photos, keep the widest.

That also makes the dictionary self-adjusting: on a library of landscapes it
keeps different words than on one of family portraits.

Cost: one embedding call per candidate, roughly a second each. 1000 candidates
is about fifteen minutes, once.

Usage:
    fetch-dictionary.py                       Italian, 1200 candidates, keep 400
    fetch-dictionary.py --lang en --keep 500
    fetch-dictionary.py --file mylist.txt     use a local list instead
"""
import json
import os
import random
import subprocess
import sys

DB = os.environ.get("IMMICH_DB", "immich_postgres")
SERVER = os.environ.get("IMMICH_SERVER", "immich_server")
ML = os.environ.get("IMMICH_ML", "http://immich_machine_learning:3003")
DB_USER = os.environ.get("IMMICH_DB_USER", "postgres")
DB_NAME = os.environ.get("IMMICH_DB_NAME", "immich")

FONTE = ("https://raw.githubusercontent.com/hermitdave/FrequencyWords"
         "/master/content/2018/%s/%s_50k.txt")

# Frequency lists start with function words. Rather than a language-specific
# stoplist, skip the very top of the list and anything too short: between them
# they remove nearly all of it, in any language.
SALTA_INIZIALI = 150
LUNGHEZZA_MINIMA = 4

# A word phrased as a caption matches better than a bare token: these models are
# trained on descriptions of images, not on vocabulary lists.
MODELLO_FRASE = {"it": "una foto di %s", "en": "a photo of %s"}


def psql(sql):
    open("/tmp/dict.sql", "w").write(sql)
    subprocess.run(["docker", "cp", "/tmp/dict.sql", f"{DB}:/tmp/dict.sql"], capture_output=True)
    r = subprocess.run(["docker", "exec", DB, "psql", "-U", DB_USER, "-d", DB_NAME,
                        "-A", "-t", "-q", "-f", "/tmp/dict.sql"], capture_output=True, text=True)
    if r.returncode != 0:
        print("  SQL failed:", r.stderr.strip()[:300]); sys.exit(1)
    return r.stdout


def embed(text, model):
    o = subprocess.run(
        ["docker", "exec", SERVER, "curl", "-s", "-m", "60", "-X", "POST", f"{ML}/predict",
         "-F", 'entries={"clip":{"textual":{"modelName":"%s"}}}' % model,
         "-F", "text=%s" % text], capture_output=True, text=True).stdout
    try:
        return json.loads(json.loads(o)["clip"])
    except Exception:
        return None


def main():
    def arg(nome, pred):
        return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else pred

    lingua = arg("--lang", "it")
    candidati = int(arg("--candidates", "1200"))
    tenere = int(arg("--keep", "400"))
    campione = int(arg("--sample", "400"))
    locale = arg("--file", "")

    modello = psql("SELECT valore FROM curator_config WHERE chiave='clip_model';").strip()
    if not modello:
        print("  Tables missing: run sql/01-schema.sql first"); sys.exit(1)

    # --- candidate words ------------------------------------------------------
    if locale:
        parole = [w.strip() for w in open(locale, encoding="utf-8") if w.strip()]
        print("  %d words from %s" % (len(parole), locale))
    else:
        url = FONTE % (lingua, lingua)
        print("  downloading %s ..." % url)
        r = subprocess.run(["docker", "exec", SERVER, "curl", "-s", "-m", "60", url],
                           capture_output=True, text=True)
        righe = [l.split()[0] for l in r.stdout.splitlines() if l.split()]
        if len(righe) < 1000:
            print("  list not reachable (%d lines). Use --file with a local one." % len(righe))
            sys.exit(1)
        parole = [w for w in righe[SALTA_INIZIALI:]
                  if len(w) >= LUNGHEZZA_MINIMA and w.isalpha()]
        print("  %d words in the list, %d usable" % (len(righe), len(parole)))
    parole = parole[:candidati]

    # --- a sample of real photos to measure against ---------------------------
    righe = psql("SELECT s.embedding::text FROM smart_search s "
                 "JOIN asset a ON a.id = s.\"assetId\" AND a.\"deletedAt\" IS NULL "
                 "ORDER BY random() LIMIT %d;" % campione)
    foto = []
    for l in righe.splitlines():
        if l.startswith("["):
            foto.append([float(x) for x in l.strip("[]").split(",")])
    if len(foto) < 50:
        print("  too few indexed photos (%d): run Smart Search first" % len(foto)); sys.exit(1)
    print("  measuring against %d photos" % len(foto))

    # normalise once, so a dot product is a cosine similarity
    def norma(v):
        n = sum(x * x for x in v) ** 0.5
        return [x / n for x in v] if n else v
    foto = [norma(v) for v in foto]

    frase = MODELLO_FRASE.get(lingua, "%s")
    misurate = []
    for i, w in enumerate(parole, 1):
        v = embed(frase % w, modello)
        if v is None:
            continue
        v = norma(v)
        sim = [sum(a * b for a, b in zip(v, f)) for f in foto]
        media = sum(sim) / len(sim)
        # spread is what matters: a word close to everything equally describes
        # nothing, however high its average similarity
        scarto = (sum((s - media) ** 2 for s in sim) / len(sim)) ** 0.5
        misurate.append((scarto, w, v))
        if i % 100 == 0:
            print("    ...%d/%d" % (i, len(parole))); sys.stdout.flush()

    misurate.sort(reverse=True, key=lambda x: x[0])
    scelte = misurate[:tenere]
    print("  keeping the %d most discriminating" % len(scelte))
    print("  best:  %s" % ", ".join(w for _, w, _ in scelte[:12]))
    print("  worst kept: %s" % ", ".join(w for _, w, _ in scelte[-6:]))
    print("  discarded:  %s" % ", ".join(w for _, w, _ in misurate[-8:]))

    psql("DELETE FROM curator_dictionary WHERE modello <> '%s';" % modello)
    blocco = []
    for _, w, v in scelte:
        blocco.append("('%s','[%s]','%s')" % (w.replace("'", "''"),
                                              ",".join("%.6f" % x for x in v), modello))
        if len(blocco) >= 40:
            psql("INSERT INTO curator_dictionary (parola, vettore, modello) VALUES "
                 + ",".join(blocco) + " ON CONFLICT (parola) DO NOTHING;")
            blocco = []
    if blocco:
        psql("INSERT INTO curator_dictionary (parola, vettore, modello) VALUES "
             + ",".join(blocco) + " ON CONFLICT (parola) DO NOTHING;")

    print("  words in the dictionary: %s" % psql("SELECT count(*) FROM curator_dictionary;").strip())
    print()
    print("  NOTE: the rules in curator_rules refer to words by name. A rule")
    print("  naming a word this list did not keep will never match - check them")
    print("  after switching dictionary.")


if __name__ == "__main__":
    main()
