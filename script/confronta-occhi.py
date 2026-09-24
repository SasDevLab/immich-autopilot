#!/usr/bin/env python3
"""Confronta alla cieca due modi di far descrivere le fotografie.

  A - la catena di oggi: moondream guarda e scrive in inglese, poi qwen3
      riscrive in italiano. Due modelli, due passaggi.
  B - un modello che vede e scrive da solo, in un passaggio.

Le risposte si presentano SENZA dire quale e' quale, come nel torneo che
elesse qwen3:4b: se si sa chi ha scritto cosa, si sceglie quello che si
spera vinca.

QUESTO SCRIPT HA FATTO DANNI. LEGGERE PRIMA DI RILANCIARLO.
=========================================================
Il 24/09/2026 ha lasciato la casa senza condizionatori due volte.

Primo guasto: ho caricato Qwen3-VL in Q4_K_M, 3,9 GB, su un telefono che ne
aveva 3,5 liberi. Android ha chiuso l'app dei condizionatori per far posto.

Secondo guasto: avevo messo un controllo della memoria, e non ha protetto
niente, per due motivi che valgono in generale.

  1. Il peso lo leggevo da /api/tags, che dice quanto pesa il file SUL DISCO.
     Un modello caricato occupa di piu': i pesi, piu' il contesto, piu' la
     cache delle chiavi. Il conto veniva giusto e la memoria finiva comunque.

  2. Il nome. In /api/tags moondream si chiama "moondream:latest", io
     cercavo "moondream", non lo trovavo, e il peso risultava zero. Il
     controllo passava dicendo "il modello ne vuole ~0": scriveva di stare
     controllando mentre non controllava niente. E' il tipo di guasto
     peggiore, perche' rassicura.

Quindi adesso non si stima: si MISURA. Si carica, si guarda quanta memoria
e' rimasta davvero, e se e' sotto il pavimento si scarica subito. E i
condizionatori si controllano dopo OGNI fotografia, non ogni cinque: la
verifica costa un decimo di secondo, l'inferenza quattordici.

E i risultati si scrivono a ogni fotografia. La prima volta si e' fermato a
14 su 20 e non aveva salvato niente: tre quarti d'ora di telefono buttati.

Sul valore della prova
----------------------
Il telefono serve ai condizionatori. Descrivere le fotografie un po' meglio
non vale la casa senza aria: se la prova non ci sta dentro con margine, la
risposta giusta e' non farla.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

OLLAMA = "http://192.168.0.23:11434"
PONTE = "http://192.168.0.23:9912"
AC = "04FA83BCFAA9"
ADB = ("/mnt/c/Users/golei/AppData/Local/Microsoft/WinGet/Packages/"
       "Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe")
TEL = "RZ8RC25PDFR"
USCITA = "/tmp/confronto.json"

# Sotto questa memoria libera Android comincia a chiudere applicazioni, e la
# prima che chiude e' quella dei condizionatori. Misurato il 24/09/2026: con
# 3058 MB liberi e moondream caricato il telefono e' scivolato a 20 MB.
PAVIMENTO_MB = 700

VECCHIO_OCCHI = "moondream:latest"
VECCHIO_PENNA = "qwen3:4b-instruct"
NUOVO = os.environ.get("MODELLO_NUOVO", "")


def memoria_libera_mb():
    r = subprocess.run([ADB, "-s", TEL, "shell", "grep MemAvailable /proc/meminfo"],
                       capture_output=True, text=True, errors="replace")
    try:
        return int(r.stdout.split()[1]) // 1024
    except Exception:
        return -1


def condizionatori_vivi():
    try:
        with urllib.request.urlopen(PONTE + "/status/" + AC, timeout=12) as f:
            return len(json.loads(f.read().decode()).get("attributes") or {}) >= 10
    except Exception:
        return False


def scarica_dalla_memoria(nome):
    try:
        req = urllib.request.Request(
            OLLAMA + "/api/generate",
            data=json.dumps({"model": nome, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass
    time.sleep(6)


def esiste(nome):
    """Il nome va confrontato per intero: e' l'errore che rese cieco il
    controllo della memoria."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=20) as f:
            return nome in [m["name"] for m in json.loads(f.read().decode()).get("models", [])]
    except Exception:
        return False


def chiedi(modello, prompt, immagine=None, num_predict=70, timeout=600):
    corpo = {"model": modello, "prompt": prompt, "stream": False,
             "keep_alive": "5m",
             "options": {"num_predict": num_predict, "num_ctx": 2048, "temperature": 0.3}}
    if immagine:
        corpo["images"] = [base64.b64encode(immagine).decode()]
    req = urllib.request.Request(OLLAMA + "/api/generate",
                                 data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return (out.get("response") or "").strip(), time.time() - t0
    except Exception as e:
        return "ERRORE: %s" % type(e).__name__, time.time() - t0


def anteprima(asset_id):
    p = subprocess.run(["docker", "exec", "immich_postgres", "psql", "-U", "postgres",
                        "-d", "immich", "-A", "-t", "-c",
                        "SELECT path FROM asset_file WHERE \"assetId\"='%s' "
                        "AND type='preview';" % asset_id],
                       capture_output=True, text=True).stdout.strip()
    if not p:
        return None
    return subprocess.run(["docker", "exec", "immich_server", "cat", p],
                          capture_output=True).stdout


RUOLO_ITA = ("Riscrivi in italiano, in UNA riga di massimo 15 parole, che momento "
             "mostra questa fotografia. Non tradurre alla lettera: racconta la scena. "
             "Niente 'sembra' o 'forse'. Non nominare persone per nome. "
             "Scrivi solo la riga.\n\nDescrizione in inglese: ")

DOMANDA_VL = ("Descrivi questa fotografia in UNA riga di massimo 15 parole, in "
              "italiano: che momento e'. Niente 'sembra' o 'forse'. Non nominare "
              "persone per nome. Scrivi solo la riga.")


class Interrotto(Exception):
    """La casa viene prima della prova."""


def salva(risultati):
    with open(USCITA, "w", encoding="utf-8") as f:
        json.dump(risultati, f, ensure_ascii=False, indent=1)


def controlla_il_telefono(modello):
    """Dopo ogni fotografia: la casa sta bene? c'e' ancora memoria?

    Ogni controllo che fallisce scarica il modello e ferma tutto. Meglio una
    prova a meta' salvata che una prova intera e i condizionatori giu'.
    """
    libera = memoria_libera_mb()
    if 0 <= libera < PAVIMENTO_MB:
        scarica_dalla_memoria(modello)
        raise Interrotto("memoria scesa a %d MB, sotto il pavimento di %d"
                         % (libera, PAVIMENTO_MB))
    if not condizionatori_vivi():
        scarica_dalla_memoria(modello)
        raise Interrotto("i condizionatori non rispondono piu'")


def giro(modello, foto, immagini, risultati, campo, domanda_da, num_predict=70):
    """Fa un passaggio completo con un modello, misurando dopo il primo carico.

    Il peso non si stima dal file: si carica una volta e si guarda quanta
    memoria e' rimasta. Se il primo carico ha gia' mangiato troppo, si
    scarica e si smette prima di fare danni.
    """
    prima = memoria_libera_mb()
    print("    memoria libera prima di caricare: %d MB" % prima, flush=True)
    primo = True
    for i, (a, _) in enumerate(foto, 1):
        arg = domanda_da(a)
        if arg is None:
            continue
        prompt, immagine = arg
        r, s = chiedi(modello, prompt, immagine, num_predict=num_predict)
        risultati[a][campo] = r
        risultati[a]["t_" + campo] = round(s, 1)
        salva(risultati)
        if primo:
            dopo = memoria_libera_mb()
            print("    dopo il carico: %d MB liberi (il modello ne ha presi %d)"
                  % (dopo, max(0, prima - dopo)), flush=True)
            primo = False
        print("      %2d/%d  %.0fs" % (i, len(foto), s), flush=True)
        controlla_il_telefono(modello)
    scarica_dalla_memoria(modello)


def main():
    if not NUOVO:
        print("  manca MODELLO_NUOVO: quale modello va messo alla prova?")
        return 2

    foto = []
    for riga in open("/tmp/foto_prova.txt"):
        p = riga.strip().split("|")
        if len(p) >= 2:
            foto.append((p[0].strip(), p[1].strip()))
    print("  %d fotografie da confrontare" % len(foto))

    for m in (VECCHIO_OCCHI, VECCHIO_PENNA, NUOVO):
        if not esiste(m):
            print("  il modello '%s' non c'e' sul telefono: mi fermo prima di "
                  "cominciare" % m)
            return 1

    if not condizionatori_vivi():
        print("  i condizionatori sono giu': non e' il momento di provare")
        return 1
    libera = memoria_libera_mb()
    print("  memoria libera adesso: %d MB (pavimento %d)" % (libera, PAVIMENTO_MB))
    if libera < PAVIMENTO_MB * 2:
        print("  il telefono e' gia' stretto: non comincio")
        return 1

    risultati = {a: {"album": alb} for a, alb in foto}
    immagini = {}
    for a, _ in foto:
        img = anteprima(a)
        if img and len(img) > 2000:
            immagini[a] = img
    print("  %d anteprime lette dal disco" % len(immagini))

    fasi = [
        ("[1/3] %s guarda le fotografie" % VECCHIO_OCCHI, VECCHIO_OCCHI, "inglese",
         lambda a: ("Describe this photo.", immagini[a]) if a in immagini else None, 70),
        ("[2/3] %s riscrive in italiano" % VECCHIO_PENNA, VECCHIO_PENNA, "A",
         lambda a: (RUOLO_ITA + risultati[a]["inglese"], None)
                   if risultati[a].get("inglese", "").strip()
                   and not risultati[a]["inglese"].startswith("ERRORE") else None, 50),
        ("[3/3] %s guarda e scrive da solo" % NUOVO, NUOVO, "B",
         lambda a: (DOMANDA_VL, immagini[a]) if a in immagini else None, 70),
    ]

    for titolo, modello, campo, domanda_da, np_ in fasi:
        print("\n  %s" % titolo)
        try:
            giro(modello, foto, immagini, risultati, campo, domanda_da, np_)
        except Interrotto as e:
            print("    MI FERMO: %s" % e)
            print("    quello che ho fatto e' salvato in %s" % USCITA)
            print("    condizionatori: %s"
                  % ("vivi" if condizionatori_vivi() else "GIU', vanno riparati"))
            return 1

    salva(risultati)
    print("\n  salvato in %s" % USCITA)
    print("  condizionatori alla fine: %s"
          % ("vivi" if condizionatori_vivi() else "GIU'"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
