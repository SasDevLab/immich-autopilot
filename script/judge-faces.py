#!/usr/bin/env python3
"""Judge the face crops, and store the verdict.

Geometry cannot tell whether a face is chewing, crying, wearing sunglasses or
squinting - and those are exactly what makes a cover photo bad. The model knows,
but asking it about the WHOLE photo does not work: sunglasses on one face in a
group shot carry almost no weight in the image as a whole.

Given the CROP it works. Measured on a photo of the owner with a skewer in his
mouth: "a person eating" scored 0.1032 against 0.0316 and 0.0363 for the
alternatives, and "a clean smiling face" scored lowest of the three.

Blur is not asked of the model at all - it is measured on the pixels, as the
variance of the Laplacian, and stored as a number rather than a verdict. A fixed
threshold was the first idea and it was wrong: calibrated on covers that had
already been selected - the best of the library - it called 63% of real faces
blurred and left 22 people out of 37 with no candidate at all. Sharpness is
compared BETWEEN the candidates of the same person instead, so somebody whose
photos are all soft still gets their least blurred one.

Only the finalists are judged - the largest faces of each person - because
judging all 1255 recent faces would be an hour of model time, the same load that
brought the machine down when 653 photos arrived at once. And the verdict is
stored, so later nights judge only what is new.

Usage:
    judge-faces.py                 judge whatever has not been judged yet
    judge-faces.py --all           judge again from scratch
    judge-faces.py --person NAME   one person, printing the reasoning
"""
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageFilter

DB = os.environ.get("IMMICH_DB", "immich_postgres")
SERVER = os.environ.get("IMMICH_SERVER", "immich_server")
ML = os.environ.get("IMMICH_ML", "http://immich_machine_learning:3003")

# What a good portrait is, and what spoils one. The score is the best match
# among the good phrases minus the best among the bad.
GOOD = [
    "un ritratto nitido di una persona che guarda in camera",
    "un volto sorridente con gli occhi aperti",
]
BAD = [
    "una persona che mangia",
    "una persona con gli occhiali da sole",
    "un volto con gli occhi chiusi",
    "una persona che piange",
    "un volto di profilo girato di lato",
]


def sql(q, fetch=True):
    r = subprocess.run(["docker", "exec", "-i", DB, "psql", "-U", "postgres", "-d", "immich",
                        "-v", "ON_ERROR_STOP=1", "-A", "-F", "|", "-t", "-c", q],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  SQL failed: %s" % r.stderr.strip()[:200])
        sys.exit(1)
    return [l.split("|") for l in r.stdout.splitlines() if l.strip()] if fetch else None


def in_server(cmd):
    return subprocess.run(["docker", "exec", SERVER, "sh", "-c", cmd],
                          capture_output=True, text=True).stdout


def config(key, default):
    r = sql("SELECT max(value) FROM autopilot_config WHERE key='%s';" % key)
    try:
        return type(default)(r[0][0])
    except Exception:
        return default


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def text_vector(phrase, model):
    out = in_server(
        "curl -s -m 300 -X POST %s/predict "
        "-F 'entries={\"clip\":{\"textual\":{\"modelName\":\"%s\"}}}' "
        "-F \"text=%s\"" % (ML, model, phrase))
    if not out.strip():
        # L'errore che usciva prima - json.loads su stringa vuota, quindi
        # "Expecting value: line 1 column 1" - non faceva capire niente.
        raise SystemExit('  il servizio di machine learning non ha risposto in tempo. Di solito vuol dire che stava caricando il modello e la macchina era occupata (il 22/09/2026 alle 04:30, con il backup delle 04:15 ancora in corso). A macchina scarica il caricamento richiede 14 secondi.')
    return unit(json.loads(json.loads(out)["clip"]))


def sharpness(path):
    """Variance of the Laplacian: high means crisp edges, low means blur."""
    try:
        im = Image.open(path).convert("L")
    except Exception:
        return 0.0                      # a video frame that will not open is unusable
    lap = im.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1))
    px = list(lap.getdata())
    n = len(px)
    m = sum(px) / n
    return sum((x - m) ** 2 for x in px) / n


def crop_vector(path, x1, y1, x2, y2, model):
    """Crop the face with a 40% margin, then have it judged and measured."""
    w, h = x2 - x1, y2 - y1
    mx, my = w * 40 // 100, h * 40 // 100
    cx, cy = max(0, x1 - mx), max(0, y1 - my)
    out = in_server(
        'ffmpeg -loglevel error -y -i "%s" -vf "crop=%d:%d:%d:%d,scale=256:256" /tmp/j.jpg '
        '&& curl -s -m 300 -X POST %s/predict '
        '-F \'entries={"clip":{"visual":{"modelName":"%s"}}}\' -F "image=@/tmp/j.jpg"'
        % (path, w + 2 * mx, h + 2 * my, cx, cy, ML, model))
    subprocess.run(["docker", "cp", "%s:/tmp/j.jpg" % SERVER, "/tmp/j.jpg"], capture_output=True)
    blur = sharpness("/tmp/j.jpg")
    try:
        return unit(json.loads(json.loads(out)["clip"])), blur
    except Exception:
        return None, blur


def main():
    model = config("clip_model", "ViT-B-16-SigLIP-i18n-256__webli")
    months = config("cover_months", 24)
    finalists = config("judge_finalists", 5)
    owner = config("owner_email", "")

    person = None
    if "--person" in sys.argv:
        person = sys.argv[sys.argv.index("--person") + 1]

    where = []
    if owner:
        where.append("u.email = '%s'" % owner.replace("'", "''"))
    if person:
        where.append("p.name = '%s'" % person.replace("'", "''"))
    if not sys.argv.count("--all") and not person:
        where.append("NOT EXISTS (SELECT 1 FROM autopilot_face_quality q WHERE q.face_id = af.id)")
    clause = (" AND " + " AND ".join(where)) if where else ""

    rows = sql("""
      WITH ranked AS (
        SELECT p.name, af.id fid, f.path,
               af."boundingBoxX1" x1, af."boundingBoxY1" y1,
               af."boundingBoxX2" x2, af."boundingBoxY2" y2,
               a."originalFileName" file, to_char(a."fileCreatedAt",'YYYY-MM-DD') taken,
               row_number() OVER (PARTITION BY p."personGroupId" ORDER BY
                 (af."boundingBoxX2"-af."boundingBoxX1")*(af."boundingBoxY2"-af."boundingBoxY1") DESC) rn
        FROM person p
        JOIN "user" u ON u.id = p."ownerId"
        JOIN asset_face af ON af."personGroupId" = p."personGroupId" AND af."deletedAt" IS NULL AND af."isVisible"
        JOIN asset a ON a.id = af."assetId" AND a."deletedAt" IS NULL
        JOIN asset_file f ON f."assetId" = a.id AND f.type = 'preview'
        WHERE a."fileCreatedAt" > now() - interval '%d months'
          -- a box touching the frame means the face is cut off
          AND NOT (af."boundingBoxX1" <= 0.02*af."imageWidth" OR af."boundingBoxY1" <= 0.02*af."imageHeight"
                   OR af."boundingBoxX2" >= 0.98*af."imageWidth" OR af."boundingBoxY2" >= 0.98*af."imageHeight")
          %s)
      SELECT name, fid, path, x1, y1, x2, y2, file, taken FROM ranked WHERE rn <= %d
      ORDER BY name, rn;""" % (months, clause, finalists))

    if not rows:
        print("  nothing new to judge")
        return
    print("  %d faces to judge (about %d minutes)" % (len(rows), round(len(rows) * 3 / 60)))

    good = [text_vector(p, model) for p in GOOD]
    bad = [text_vector(p, model) for p in BAD]

    done, per_person = 0, {}
    for name, fid, path, x1, y1, x2, y2, file_, taken in rows:
        v, blur = crop_vector(path, int(x1), int(y1), int(x2), int(y2), model)
        if v is None:
            # an unreadable crop is still a verdict: it is unusable
            sql("""INSERT INTO autopilot_face_quality (face_id, sharpness, pro, contro, flaw)
                   VALUES ('%s', %.1f, 0, 1, 'unreadable')
                   ON CONFLICT (face_id) DO UPDATE SET sharpness=EXCLUDED.sharpness,
                     pro=EXCLUDED.pro, contro=EXCLUDED.contro, flaw=EXCLUDED.flaw,
                     judged=now();""" % (fid, blur), fetch=False)
            continue
        pro = max(sum(a * b for a, b in zip(v, t)) for t in good)
        contro = max(sum(a * b for a, b in zip(v, t)) for t in bad)
        worst = BAD[max(range(len(BAD)), key=lambda i: sum(a * b for a, b in zip(v, bad[i])))]
        sql("""INSERT INTO autopilot_face_quality (face_id, sharpness, pro, contro, flaw)
               VALUES ('%s', %.1f, %.6f, %.6f, '%s')
               ON CONFLICT (face_id) DO UPDATE SET sharpness=EXCLUDED.sharpness,
                 pro=EXCLUDED.pro, contro=EXCLUDED.contro, flaw=EXCLUDED.flaw,
                 judged=now();""" % (fid, blur, pro, contro, worst.replace("'", "''")),
            fetch=False)
        done += 1
        per_person.setdefault(name, []).append((pro - contro, blur, file_, taken, worst))
        if done % 25 == 0:
            print("    ...%d/%d" % (done, len(rows)))

    print("  judged: %d" % done)
    if person:
        for name, lst in per_person.items():
            lst.sort(reverse=True)
            print("\n  === %s ===" % name)
            for i, (score, blur, file_, taken, worst) in enumerate(lst):
                print("    %+.4f  %-24s %s  sharpness %5d  (%s)%s"
                      % (score, file_[:24], taken, blur, worst[:30],
                         "  <-- best" if i == 0 else ""))


if __name__ == "__main__":
    main()
