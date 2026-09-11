#!/usr/bin/env python3
"""Calcola il vector di ogni word del dizionario e lo salva nel database.

Da lanciare una volta all installazione, e ogni volta che si aggiungono words
o si cambia il model CLIP di Immich (i vectors del model vecchio non sono
confrontabili con quelli del nuovo: vanno rebuildti tutti).

Il model gira nel container di Immich, in local_file: nessun dato esce dalla
macchina, ne le foto ne le words.

Uso:
    build-dictionary.py [dizionario]   (predefinito: dictionaries/it.txt)
    build-dictionary.py --rebuild    rebuild anche le words already presenti
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
    open("/tmp/autopilota.sql", "w").write(sql)
    subprocess.run(["docker", "cp", "/tmp/autopilota.sql", f"{CONTAINER_DB}:/tmp/autopilota.sql"],
                   capture_output=True)
    r = subprocess.run(["docker", "exec", CONTAINER_DB, "psql", "-U", DB_UTENTE, "-d", DB_NOME,
                        "-A", "-t", "-q", "-f", "/tmp/autopilota.sql"],
                       capture_output=True, text=True)
    if r.returncode != 0 and not silenzioso:
        print("  errore SQL:", r.stderr.strip()[:300])
        sys.exit(1)
    return r.stdout


def vector(phrase, model):
    o = subprocess.run(
        ["docker", "exec", CONTAINER_SERVER, "curl", "-s", "-m", "60", "-X", "POST",
         f"{ML}/predict",
         "-F", 'entries={"clip":{"textual":{"modelName":"%s"}}}' % model,
         "-F", "text=%s" % phrase],
        capture_output=True, text=True).stdout
    try:
        return json.loads(json.loads(o)["clip"])
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuild = "--rebuild" in sys.argv
    path = args[0] if args else os.path.join(QUI, "dictionaries", "it.txt")

    model = psql("SELECT value FROM autopilot_config WHERE key='clip_model';").strip()
    if not model:
        print("  Tabelle mancanti: lancia prima sql/01-schema.sql")
        sys.exit(1)

    # il model del dizionario deve coincidere con quello di Immich, altrimenti
    # i vectors appartengono a spazi diversi e i confronti non significano nulla
    attuale = psql("SELECT value #>> '{machineLearning,clip,modelName}' "
                   "FROM system_metadata WHERE key='system-config';").strip()
    if attuale and attuale != model:
        print("  ATTENZIONE: Immich usa '%s', la configurazione dice '%s'." % (attuale, model))
        print("  Allinea 'clip_model' in autopilot_config, poi rilancia con --rebuild.")
        sys.exit(1)

    words = []
    for riga in open(path, encoding="utf-8"):
        riga = riga.strip()
        if riga and not riga.startswith("#"):
            words.extend(riga.split())
    words = sorted(set(words))

    if rebuild:
        psql("DELETE FROM autopilot_dictionary;")
        already = set()
    else:
        already = set(psql("SELECT word FROM autopilot_dictionary WHERE model = '%s';" % model).split())

    new_words = [p for p in words if p not in already]
    print("  dizionario %s: %d words, %d da calcolare"
          % (os.path.basename(path), len(words), len(new_words)))
    if not new_words:
        return

    done, batch = 0, []
    for p in new_words:
        # "una foto di X" funziona meglio della word nuda: il model e stato
        # addestrato su descrizioni di immagini, non su elenchi di vocaboli
        v = vector("una foto di " + p, model)
        if v is None:
            print("    non riuscita:", p)
            continue
        batch.append("('%s','[%s]','%s')" % (p.replace("'", "''"),
                                              ",".join("%.6f" % x for x in v), model))
        done += 1
        if len(batch) >= 40:
            psql("INSERT INTO autopilot_dictionary (word, vector, model) VALUES "
                 + ",".join(batch) + " ON CONFLICT (word) DO NOTHING;")
            batch = []
            print("    ...%d/%d" % (done, len(new_words)))
            sys.stdout.flush()
    if batch:
        psql("INSERT INTO autopilot_dictionary (word, vector, model) VALUES "
             + ",".join(batch) + " ON CONFLICT (word) DO NOTHING;")

    print("  words nel dizionario: %s" % psql("SELECT count(*) FROM autopilot_dictionary;").strip())


if __name__ == "__main__":
    main()
