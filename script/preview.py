#!/usr/bin/env python3
"""Preview: show what the autopilot would do, and change nothing.

Borrowed from immich-smart-albums. It matters most on large libraries: running
an automation blind over tens of thousands of photos and finding out afterwards
that the criteria were wrong means undoing albums by hand, which the interface
makes slow.

It reads the SAME queries and the SAME rules as the nightly run, so whatever
appears here is what will happen.

Usage:
    preview.py               what it would do tonight (unfiled photos only)
    preview.py --all         ignore the "unfiled only" filter: this is how you
                             tune the rules, by comparing its answers against
                             albums filed by hand
    preview.py --photo <id>  one photo, and how close it sits to every word
"""
import json
import os
import subprocess
import sys

QUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("IMMICH_DB", "immich_postgres")
UTENTE = os.environ.get("IMMICH_DB_USER", "postgres")
NOME = os.environ.get("IMMICH_DB_NAME", "immich")

MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio',
        'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']


def psql(sql, sep="|"):
    open("/tmp/preview.sql", "w").write(sql)
    subprocess.run(["docker", "cp", "/tmp/preview.sql", f"{DB}:/tmp/preview.sql"], capture_output=True)
    r = subprocess.run(["docker", "exec", DB, "psql", "-U", UTENTE, "-d", NOME,
                        "-A", "-t", "-F", sep, "-f", "/tmp/preview.sql"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  SQL error:", r.stderr.strip()[:300])
        sys.exit(1)
    return r.stdout


def decide(c, rules, presence, margin):
    """The same logic the workflow uses. Returns (type, evidence, margin)."""
    outcomes = []
    for r in rules:
        nec = r["required"]
        if not all(any(c.get(p, 0) >= presence for p in gruppo) for gruppo in nec):
            continue
        evidence = [p for p in r["evidence"] if c.get(p, 0) >= presence]
        if not evidence:
            continue
        escl = max((c.get(p, 0) for p in r.get("against", [])), default=0)
        if escl > max(c[p] for p in evidence):
            continue
        score = sum(min(c[p], 0.4) + 0.25 * min(1.0, c[p] / 0.12) for p in evidence)
        outcomes.append((score, r["type"], evidence))
    outcomes.sort(reverse=True)
    if not outcomes:
        return None, [], 0
    if len(outcomes) == 1:
        return outcomes[0][1], outcomes[0][2], outcomes[0][0]
    return outcomes[0][1], outcomes[0][2], outcomes[0][0] - outcomes[1][0]


def diagnose_photo(aid):
    """How close one photo sits to every word. With the numbers in front of you,
    a decision can be read rather than argued with."""
    rows = psql(f"""
      WITH sim AS (
        SELECT d.word, 1 - (s.embedding <=> d.vector) v
        FROM smart_search s CROSS JOIN autopilot_dictionary d
        WHERE s."assetId" = '{aid}'
      ),
      allwords AS (
        SELECT d.word, avg(1 - (s.embedding <=> d.vector)) m,
               stddev_pop(1 - (s.embedding <=> d.vector)) sd
        FROM smart_search s CROSS JOIN autopilot_dictionary d GROUP BY d.word
      )
      SELECT sim.word || '|' || round(((sim.v - allwords.m)/nullif(allwords.sd,0))::numeric, 2)
      FROM sim JOIN allwords ON allwords.word = sim.word
      ORDER BY (sim.v - allwords.m)/nullif(allwords.sd,0) DESC NULLS LAST LIMIT 15;""")
    threshold = float(psql("SELECT value FROM autopilot_config WHERE key='word_threshold';").strip())
    print("  Words closest to this photo, in deviations above each word's own average:")
    print("  a concept counts from %.1f upwards\n" % threshold)
    for l in rows.splitlines():
        if "|" not in l:
            continue
        p, z = l.split("|")
        z = float(z)
        print("    %-16s %5.2f  %s" % (p, z, "<-- counts" if z >= threshold else ""))


def main():
    if "--photo" in sys.argv:
        i = sys.argv.index("--photo")
        if i + 1 >= len(sys.argv):
            print("  missing the photo id")
            sys.exit(1)
        diagnose_photo(sys.argv[i + 1])
        return

    sql = open(os.path.join(QUI, "sql", "03-events.sql"), encoding="utf-8").read()
    if "--all" in sys.argv:
        sql = sql.replace(
            'AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = a.id)', "")
        print("  (--all: photos already in an album are considered too)\n")

    presence = float(psql("SELECT value FROM autopilot_config WHERE key='min_presence';").strip())
    margin = float(psql("SELECT value FROM autopilot_config WHERE key='margin';").strip())

    rows = psql(sql, sep="\t").splitlines()
    if not rows or not any("\t" in l for l in rows):
        print("  Nothing to file: every photo is already in an album.")
        print("  To tune the rules against what is already filed: preview.py --all")
        return

    print("  %-52s %s" % ("WHAT IT WOULD DO", "WHY"))
    print("  " + "-" * 100)
    for l in rows:
        p = l.split("\t")
        if len(p) < 9:
            continue
        dal, al, count, city, concepts, _ids, extend, rules_json, _marg = p[:9]
        try:
            c = {k: float(v) for k, v in json.loads(concepts).items()}
            rules = json.loads(rules_json)
        except Exception:
            continue
        for r in rules:
            for campo in ("required", "evidence", "against"):
                if isinstance(r.get(campo), str):
                    r[campo] = json.loads(r[campo])

        tipo, evidence, dist = decide(c, rules, presence, margin)
        mese, anno = MESI[int(dal[5:7]) - 1], dal[:4]
        where_ = (" a " + city) if city else ""
        if tipo and dist >= margin:
            name = "%s%s, %s %s" % (tipo, where_, mese, anno)
        else:
            name = "%s%s %s" % ((city + ", ") if city else "", mese, anno)
        action = "extend album" if extend else "create album"
        print("  %-52s %s" % ('%s "%s"' % (action, name), "%d photos, %s" % (int(count), dal if dal == al else dal + " -> " + al)))
        if evidence:
            top = sorted(evidence, key=lambda x: -c[x])[:6]
            print("  %-52s evidence: %s" % ("", ", ".join("%s %.0f%%" % (x, c[x] * 100) for x in top)))
            print("  %-52s margin over the runner-up: %.2f%s"
                  % ("", dist, "  (below %.2f: keeps the date)" % margin if dist < margin else ""))
        else:
            print("  %-52s no evidence: keeps the date" % "")
        print()


if __name__ == "__main__":
    main()
