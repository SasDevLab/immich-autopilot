#!/usr/bin/env python3
"""Take out of an album the photos that were never part of the occasion.

The measurement finds them and decides; the model says, in plain language, what
they actually are. Which is the opposite of the division of labour tried first,
and the reason is worth recording.

Asked to review a whole album, a small model accuses the right photos and clears
the wrong ones. Asked "can this photo be in this album?" while being handed both
the timings and the word lists, it reads only the words - it removed the photo of
the Reggia di Caserta from the Caserta concert, the Reggia being where the
concert took place, and trimmed a birthday party at both ends.

Yet asked about time alone - "the concert ran 22:45 to 23:34, the photo is from
23:34, during or another moment?" - both models answered 4 out of 4, the 1.5B one
included. They can reason; they cannot reason about two things at once. Handed
two criteria they answer the easier one and forget the other.

So the SQL decides, using the two conditions that hold on real data:

  * only single-day albums. Over eight days in Nice the measure flagged 52
    photos of 204 and nearly all belonged: a journey contains variety by nature.
    Single-day albums gave 10 suspects out of 99, and those were the real ones.

  * the photo must sit at least two hours from the album's CORE - the photos that
    do carry its words. Without this the first and last photo of every party were
    accused, those being the beginning and the end of it. And the distance is
    measured from the core, not from the nearest photo, because intruders arrive
    in groups: the two gift photos in the Caparezza album are 16 seconds apart.

The model is then asked one question at a time, and only to describe what the
photo shows - which is what reaches the owner in the summary. "A photo taken at
16:38 that looks like unwrapping a present" tells him more than "one photo
removed".

Nothing is ever deleted: the photo leaves the album and stays in the library.

Usage:
    review-albums.py             show what it would do
    review-albums.py --apply     take the photos out of their albums
"""
import base64
import json
import os
import subprocess
import sys

DB = os.environ.get("IMMICH_DB", "immich_postgres")
IMMICH = os.environ.get("IMMICH_URL", "http://127.0.0.1:2283")
KEY_FILE = os.environ.get("IMMICH_KEY_FILE", "/root/.immich-key")

# The model lives on the phone, reached over adb. It is optional: without it the
# removals still happen, they just arrive without a description.
ADB = os.environ.get("ADB", "/mnt/c/Users/golei/AppData/Local/Microsoft/WinGet/"
                            "Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/"
                            "platform-tools/adb.exe")
PHONE = os.environ.get("PHONE_SERIAL", "RZ8RC25PDFR")
TERMUX_HOME = "/data/data/com.termux/files/home"
TERMUX_PREFIX = "/data/data/com.termux/files/usr"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

ISOLATION_SECONDS = 7200        # two hours from the album's core
CORE_WORDS = 3                  # how many of the album's words make a photo "core"


def sql(query, fetch=True):
    r = subprocess.run(["docker", "exec", "-i", DB, "psql", "-U", "postgres", "-d", "immich",
                        "-v", "ON_ERROR_STOP=1", "-A", "-F", "\t", "-t", "-c", query],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  SQL failed: %s" % r.stderr.strip()[:200])
        sys.exit(1)
    return [l.split("\t") for l in r.stdout.splitlines() if l.strip()] if fetch else None


def ask_model(prompt, tokens=70):
    """One question at a time. Returns None when the phone is not reachable."""
    body = json.dumps({"model": MODEL, "stream": False,
                       "options": {"temperature": 0.0, "num_predict": tokens},
                       "prompt": prompt})
    b64 = base64.b64encode(body.encode()).decode()
    env = ("export PATH=%s/bin:$PATH LD_LIBRARY_PATH=%s/lib HOME=%s"
           % (TERMUX_PREFIX, TERMUX_PREFIX, TERMUX_HOME))
    try:
        subprocess.run([ADB, "-s", PHONE, "shell",
                        "run-as com.termux sh -c 'echo %s | base64 -d > %s/ask.json'"
                        % (b64, TERMUX_HOME)], capture_output=True, timeout=60)
        subprocess.run([ADB, "-s", PHONE, "shell",
                        "run-as com.termux sh -c '%s; cd %s; curl -s -m 300 "
                        "http://127.0.0.1:11434/api/generate --data @ask.json -o ask_r.json'"
                        % (env, TERMUX_HOME)], capture_output=True, timeout=400)
        out = subprocess.run([ADB, "-s", PHONE, "shell",
                              "run-as com.termux cat %s/ask_r.json" % TERMUX_HOME],
                             capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout).get("response", "").strip()
    except Exception:
        return None


def main():
    apply = "--apply" in sys.argv

    rows = sql("""
      WITH sim AS (
        SELECT s."assetId" aid, d.word, 1 - (s.embedding <=> d.vector) v
        FROM smart_search s CROSS JOIN autopilot_dictionary d
        JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL),
      stat AS (SELECT word, avg(v) m, stddev_pop(v) sd FROM sim GROUP BY word),
      strong AS (
        SELECT sim.aid, sim.word FROM sim JOIN stat ON stat.word = sim.word
        WHERE stat.sd > 0 AND (sim.v - stat.m) / stat.sd >=
              (SELECT max(value)::numeric FROM autopilot_config WHERE key='word_threshold')),
      -- Single-day albums only: a journey of several days contains different
      -- things and they all belong to it.
      one_day AS (
        SELECT aa."albumId" alb
        FROM album_asset aa JOIN asset a ON a.id = aa."assetId" AND a."deletedAt" IS NULL
        GROUP BY aa."albumId"
        HAVING count(DISTINCT (a."fileCreatedAt" AT TIME ZONE
               (SELECT max(value) FROM autopilot_config WHERE key='timezone'))::date) = 1),
      photo AS (
        SELECT al.id alb, al."albumName" album, a.id aid, a."fileCreatedAt" ts,
               to_char(a."fileCreatedAt" AT TIME ZONE
                 (SELECT max(value) FROM autopilot_config WHERE key='timezone'),
                 'DD/MM/YYYY HH24:MI') taken, a."originalFileName" file
        FROM album al
        JOIN album_asset aa ON aa."albumId" = al.id
        JOIN asset a ON a.id = aa."assetId" AND a."deletedAt" IS NULL
        WHERE al."deletedAt" IS NULL
          AND al.id IN (SELECT album_id::text::uuid FROM autopilot_albums)
          AND al.id IN (SELECT alb FROM one_day)),
      ranked AS (
        SELECT alb, word, row_number() OVER (PARTITION BY alb ORDER BY n DESC) r
        FROM (SELECT photo.alb, s.word, count(*) n FROM photo JOIN strong s ON s.aid = photo.aid
              GROUP BY photo.alb, s.word) x),
      -- how many of the album's own words each photo carries
      carried AS (
        SELECT photo.alb, photo.aid,
               (SELECT count(*) FROM ranked t JOIN strong s ON s.word = t.word AND s.aid = photo.aid
                 WHERE t.alb = photo.alb AND t.r <= 6) n
        FROM photo),
      -- the core of the album, against which isolation is measured
      core AS (
        SELECT p.alb, p.ts FROM photo p JOIN carried c ON c.aid = p.aid AND c.alb = p.alb
        WHERE c.n >= %d),
      span AS (
        SELECT alb,
               to_char(min(ts) AT TIME ZONE (SELECT max(value) FROM autopilot_config WHERE key='timezone'),'HH24:MI')
               || ' - ' ||
               to_char(max(ts) AT TIME ZONE (SELECT max(value) FROM autopilot_config WHERE key='timezone'),'HH24:MI') hours
        FROM core GROUP BY alb)
      SELECT p.album, p.aid::text, p.taken, p.file, p.alb::text,
             coalesce((SELECT string_agg(s.word, ', ' ORDER BY s.word)
                       FROM strong s WHERE s.aid = p.aid), '(nothing)'),
             coalesce(sp.hours, '?'),
             round((SELECT min(abs(extract(epoch FROM (c.ts - p.ts)))) FROM core c
                     WHERE c.alb = p.alb) / 3600.0, 1)
      FROM photo p
      JOIN carried ca ON ca.aid = p.aid AND ca.alb = p.alb
      LEFT JOIN span sp ON sp.alb = p.alb
      WHERE ca.n = 0
        AND (SELECT min(abs(extract(epoch FROM (c.ts - p.ts)))) FROM core c
              WHERE c.alb = p.alb) > %d
        AND NOT EXISTS (SELECT 1 FROM autopilot_excluded e
                         WHERE e.asset_id = p.aid AND e.album_id = p.alb)
      ORDER BY p.album, p.ts;""" % (CORE_WORDS, ISOLATION_SECONDS))

    if not rows:
        print("  every album is coherent: nothing to take out")
        return

    print("  %d photo(s) that do not belong\n" % len(rows))
    done = []
    for album, aid, taken, file_, alb, words, hours, gap in rows:
        # One question, and only the one the model is good at: what is this?
        what = ask_model(
            "Una fotografia mostra: %s.\n"
            "Descrivi in UNA riga breve, in italiano, che momento sembra essere. "
            "Non elencare le parole, dì che cosa sta succedendo." % words)
        what = (what or "").replace("\n", " ").strip()[:110] or "(nessuna descrizione)"
        print("  %s" % album)
        print("    %s del %s  (%s ore dal cuore dell'album, che va %s)"
              % (file_, taken, gap, hours))
        print("    sembra: %s" % what)
        print()
        done.append((alb, aid, album, file_, taken, what))

    if not apply:
        print("  (prova: non ho tolto niente. Con --apply le toglie davvero)")
        return

    key = open(KEY_FILE).read().strip()
    for alb, aid, album, file_, taken, what in done:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "30",
                            "-X", "DELETE", "-H", "x-api-key: " + key,
                            "-H", "Content-Type: application/json",
                            "-d", json.dumps({"ids": [aid]}),
                            "%s/api/albums/%s/assets" % (IMMICH, alb)],
                           capture_output=True, text=True)
        if r.stdout.strip() == "200":
            # remembered, or the album job would put it back the next night
            sql("""INSERT INTO autopilot_excluded (asset_id, album_id, reason)
                   VALUES ('%s','%s','%s') ON CONFLICT DO NOTHING;"""
                % (aid, alb, (what[:150]).replace("'", "''")), fetch=False)
            print("  tolta  %-26s da %s" % (file_[:26], album[:40]))
        else:
            print("  FALLITA %-26s (%s)" % (file_[:26], r.stdout.strip()))


if __name__ == "__main__":
    main()
