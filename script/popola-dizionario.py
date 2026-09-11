#!/usr/bin/env python3
"""Calcola il vettore di ogni parola del dizionario e lo salva nel database.

Da lanciare una volta all installazione, e ogni volta che si aggiungono parole
o si cambia il modello CLIP di Immich (i vettori del modello vecchio non sono
confrontabili con quelli del nuovo: vanno ricalcolati tutti).

Il modello gira nel container di Immich, in locale: nessun dato esce dalla
macchina, ne le foto ne le parole.

Uso:
    popola-dizionario.py [dizionario]   (predefinito: dizionari/it.txt)
    popola-dizionario.py --ricalcola    ricalcola anche le parole gia presenti
"""
import json
import os
import subprocess
import sys

QUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER_SERVER = os.environ.get("IMMICH_SERVER", "immich_server")
CONTAINER_DB = os.environ.get("IMMICH_DB", "immich_postgres")
ML = os.environ.get("IMMICH_ML", "http://immich_machine_learning:3003")
DB_UTENTE = os.environ.get("IMMICH_DB_USER", "postgres")
DB_NOME = os.environ.get("IMMICH_DB_NAME", "immich")


def psql(sql, silenzioso=False):
    open("/tmp/curatore.sql", "w").write(sql)
    subprocess.run(["docker", "cp", "/tmp/curatore.sql", f"{CONTAINER_DB}:/tmp/curatore.sql"],
                   capture_output=True)
    r = subprocess.run(["docker", "exec", CONTAINER_DB, "psql", "-U", DB_UTENTE, "-d", DB_NOME,
                        "-A", "-t", "-q", "-f", "/tmp/curatore.sql"],
                       capture_output=True, text=True)
    if r.returncode != 0 and not silenzioso:
        print("  errore SQL:", r.stderr.strip()[:300])
        sys.exit(1)
    return r.stdout


def vettore(frase, modello):
    o = subprocess.run(
        ["docker", "exec", CONTAINER_SERVER, "curl", "-s", "-m", "60", "-X", "POST",
         f"{ML}/predict",
         "-F", 'entries={"clip":{"textual":{"modelName":"%s"}}}' % modello,
         "-F", "text=%s" % frase],
        capture_output=True, text=True).stdout
    try:
        return json.loads(json.loads(o)["clip"])
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ricalcola = "--ricalcola" in sys.argv
    percorso = args[0] if args else os.path.join(QUI, "dizionari", "it.txt")

    modello = psql("SELECT valore FROM curatore_config WHERE chiave='modello_clip';").strip()
    if not modello:
        print("  Tabelle mancanti: lancia prima sql/01-schema.sql")
        sys.exit(1)

    # il modello del dizionario deve coincidere con quello di Immich, altrimenti
    # i vettori appartengono a spazi diversi e i confronti non significano nulla
    attuale = psql("SELECT value #>> '{machineLearning,clip,modelName}' "
                   "FROM system_metadata WHERE key='system-config';").strip()
    if attuale and attuale != modello:
        print("  ATTENZIONE: Immich usa '%s', la configurazione dice '%s'." % (attuale, modello))
        print("  Allinea 'modello_clip' in curatore_config, poi rilancia con --ricalcola.")
        sys.exit(1)

    parole = []
    for riga in open(percorso, encoding="utf-8"):
        riga = riga.strip()
        if riga and not riga.startswith("#"):
            parole.extend(riga.split())
    parole = sorted(set(parole))

    if ricalcola:
        psql("DELETE FROM curatore_dizionario;")
        gia = set()
    else:
        gia = set(psql("SELECT parola FROM curatore_dizionario WHERE modello = '%s';" % modello).split())

    nuove = [p for p in parole if p not in gia]
    print("  dizionario %s: %d parole, %d da calcolare"
          % (os.path.basename(percorso), len(parole), len(nuove)))
    if not nuove:
        return

    fatte, blocco = 0, []
    for p in nuove:
        # "una foto di X" funziona meglio della parola nuda: il modello e stato
        # addestrato su descrizioni di immagini, non su elenchi di vocaboli
        v = vettore("una foto di " + p, modello)
        if v is None:
            print("    non riuscita:", p)
            continue
        blocco.append("('%s','[%s]','%s')" % (p.replace("'", "''"),
                                              ",".join("%.6f" % x for x in v), modello))
        fatte += 1
        if len(blocco) >= 40:
            psql("INSERT INTO curatore_dizionario (parola, vettore, modello) VALUES "
                 + ",".join(blocco) + " ON CONFLICT (parola) DO NOTHING;")
            blocco = []
            print("    ...%d/%d" % (fatte, len(nuove)))
            sys.stdout.flush()
    if blocco:
        psql("INSERT INTO curatore_dizionario (parola, vettore, modello) VALUES "
             + ",".join(blocco) + " ON CONFLICT (parola) DO NOTHING;")

    print("  parole nel dizionario: %s" % psql("SELECT count(*) FROM curatore_dizionario;").strip())


if __name__ == "__main__":
    main()
