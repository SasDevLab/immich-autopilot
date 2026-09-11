#!/usr/bin/env python3
"""Modalita' prova: mostra cosa farebbe il curatore, senza fare nulla.

Ispirata alla modalita' di anteprima di immich-smart-albums. Serve soprattutto
su archivi grandi: lanciare un automatismo alla cieca su decine di migliaia di
foto e scoprire dopo che ha sbagliato criterio significa dover disfare album a
mano, una cosa che l'interfaccia rende lenta.

Legge le STESSE query e le STESSE regole che usa il workflow notturno: se qui
si vede una cosa, quella cosa accadra'.

Uso:
    preview.py               cosa farebbe stanotte (solo foto senza album)
    preview.py --tutte       ignora il filtro sugli album: utile per tarare le
                           regole sull'archivio gia' organizzato, confrontando
                           il risultato con gli album fatti a mano
    preview.py --foto <id>   diagnosi di una singola foto: quanto e' vicina a
                           ogni parola del dizionario
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
    open("/tmp/prova.sql", "w").write(sql)
    subprocess.run(["docker", "cp", "/tmp/prova.sql", f"{DB}:/tmp/prova.sql"], capture_output=True)
    r = subprocess.run(["docker", "exec", DB, "psql", "-U", UTENTE, "-d", NOME,
                        "-A", "-t", "-F", sep, "-f", "/tmp/prova.sql"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  errore SQL:", r.stderr.strip()[:300])
        sys.exit(1)
    return r.stdout


def decidi(c, regole, presenza, margin):
    """La stessa logica del workflow. Torna (tipo, evidence, distacco)."""
    esiti = []
    for r in regole:
        nec = r["required"]
        if not all(any(c.get(p, 0) >= presenza for p in gruppo) for gruppo in nec):
            continue
        evidence = [p for p in r["evidence"] if c.get(p, 0) >= presenza]
        if not evidence:
            continue
        escl = max((c.get(p, 0) for p in r.get("against", [])), default=0)
        if escl > max(c[p] for p in evidence):
            continue
        punti = sum(min(c[p], 0.4) + 0.25 * min(1.0, c[p] / 0.12) for p in evidence)
        esiti.append((punti, r["tipo"], evidence))
    esiti.sort(reverse=True)
    if not esiti:
        return None, [], 0
    if len(esiti) == 1:
        return esiti[0][1], esiti[0][2], esiti[0][0]
    return esiti[0][1], esiti[0][2], esiti[0][0] - esiti[1][0]


def diagnosi_foto(aid):
    """Quanto una foto e' vicina a ogni parola. Con i numeri davanti si capisce
    perche' una decisione e' andata come e' andata, invece di ragionarci sopra."""
    righe = psql(f"""
      WITH sim AS (
        SELECT d.parola, 1 - (s.embedding <=> d.vettore) v
        FROM smart_search s CROSS JOIN curator_dictionary d
        WHERE s."assetId" = '{aid}'
      ),
      tutte AS (
        SELECT d.parola, avg(1 - (s.embedding <=> d.vettore)) m,
               stddev_pop(1 - (s.embedding <=> d.vettore)) sd
        FROM smart_search s CROSS JOIN curator_dictionary d GROUP BY d.parola
      )
      SELECT sim.parola || '|' || round(((sim.v - tutte.m)/nullif(tutte.sd,0))::numeric, 2)
      FROM sim JOIN tutte ON tutte.parola = sim.parola
      ORDER BY (sim.v - tutte.m)/nullif(tutte.sd,0) DESC NULLS LAST LIMIT 15;""")
    soglia = float(psql("SELECT valore FROM curator_config WHERE chiave='word_threshold';").strip())
    print("  Parole piu' vicine a questa foto (in deviazioni dalla media di ciascuna):")
    print("  la soglia per 'contenere' un concetto e' %.1f\n" % soglia)
    for l in righe.splitlines():
        if "|" not in l:
            continue
        p, z = l.split("|")
        z = float(z)
        print("    %-16s %5.2f  %s" % (p, z, "<-- conta" if z >= soglia else ""))


def main():
    if "--foto" in sys.argv:
        i = sys.argv.index("--foto")
        if i + 1 >= len(sys.argv):
            print("  manca l'identificativo della foto")
            sys.exit(1)
        diagnosi_foto(sys.argv[i + 1])
        return

    sql = open(os.path.join(QUI, "sql", "03-eventi.sql"), encoding="utf-8").read()
    if "--tutte" in sys.argv:
        sql = sql.replace(
            'AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = a.id)', "")
        print("  (modalita' --tutte: guardo anche le foto gia' in un album)\n")

    presenza = float(psql("SELECT valore FROM curator_config WHERE chiave='min_presence';").strip())
    margin = float(psql("SELECT valore FROM curator_config WHERE chiave='margin';").strip())

    righe = psql(sql, sep="\t").splitlines()
    if not righe or not any("\t" in l for l in righe):
        print("  Nessun periodo da catalogare: tutte le foto stanno gia' in un album.")
        print("  Per tarare le regole sull'archivio esistente: preview.py --tutte")
        return

    print("  %-52s %s" % ("COSA FAREBBE", "PERCHE'"))
    print("  " + "-" * 100)
    for l in righe:
        p = l.split("\t")
        if len(p) < 9:
            continue
        dal, al, quante, citta, concetti, _ids, estendi, regole_j, _marg = p[:9]
        try:
            c = {k: float(v) for k, v in json.loads(concetti).items()}
            regole = json.loads(regole_j)
        except Exception:
            continue
        for r in regole:
            for campo in ("required", "evidence", "against"):
                if isinstance(r.get(campo), str):
                    r[campo] = json.loads(r[campo])

        tipo, evidence, dist = decidi(c, regole, presenza, margin)
        mese, anno = MESI[int(dal[5:7]) - 1], dal[:4]
        luogo = (" a " + citta) if citta else ""
        if tipo and dist >= margin:
            nome = "%s%s, %s %s" % (tipo, luogo, mese, anno)
        else:
            nome = "%s%s %s" % ((citta + ", ") if citta else "", mese, anno)
        azione = "allunga album esistente" if estendi else "crea album"
        print("  %-52s %s" % ('%s "%s"' % (azione, nome), "%d foto, %s" % (int(quante), dal if dal == al else dal + " -> " + al)))
        if evidence:
            forti = sorted(evidence, key=lambda x: -c[x])[:6]
            print("  %-52s evidence: %s" % ("", ", ".join("%s %.0f%%" % (x, c[x] * 100) for x in forti)))
            print("  %-52s distacco dalla seconda ipotesi: %.2f%s"
                  % ("", dist, "  (sotto %.2f: resta la data)" % margin if dist < margin else ""))
        else:
            print("  %-52s nessuna prova: resta la data" % "")
        print()


if __name__ == "__main__":
    main()
