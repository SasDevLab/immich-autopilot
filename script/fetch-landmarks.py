#!/usr/bin/env python3
"""Download the notable places for the countries the library actually contains.

Immich's own place database holds inhabited places only: it answers "Rionero in
Vulture" for a day spent at the Laghi di Monticchio, because the lake is not in
it and the nearest town is. GeoNames publishes the rest - lakes, peaks, parks,
stadiums, monuments - one file per country.

Which countries to fetch is not a setting: it is read from the photos. Go to
Spain and the next run picks up ES on its own. The name-to-code mapping comes
from GeoNames too, so no list of countries is written down here either.

Only feature codes that can name a destination are kept. A hotel or a square
200 m away says nothing about a day out, and the table stays small.

Usage:
    fetch-landmarks.py              fetch whatever the library needs
    fetch-landmarks.py --all        re-fetch countries already loaded
"""
import io
import os
import subprocess
import sys
import urllib.request
import zipfile

DB = os.environ.get("IMMICH_DB", "immich_postgres")
GEONAMES = "https://download.geonames.org/export/dump/"

# Codes that can stand as the name of a place you went to. Everything else -
# hotels, squares, churches, streams, ruins - is a landmark you happened to be
# near, which is not the same thing.
DESTINATIONS = (
    "LK", "LKS", "RESV", "WTRH",          # water
    "BCH", "CAPE", "ISL",                 # coast
    "MT", "PK", "VLC",                     # relief
    "PRK", "GDN", "FRST",                  # green
    "STDM", "AMTH", "ZOO",                 # venues
    "PAL", "CSTL", "MUS", "ARCH", "ANS",  # heritage
    "LCTY",                                # named localities (fairgrounds, districts)
)


def psql(sql):
    subprocess.run(["docker", "exec", "-i", DB, "psql", "-U", "postgres", "-d", "immich",
                    "-v", "ON_ERROR_STOP=1", "-q", "-c", sql],
                   check=True, capture_output=True, text=True)


def query(sql):
    r = subprocess.run(["docker", "exec", "-i", DB, "psql", "-U", "postgres", "-d", "immich",
                        "-A", "-t", "-c", sql], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.strip()]


def main():
    psql("""CREATE TABLE IF NOT EXISTS autopilot_landmarks (
              country       char(2) NOT NULL,
              name          text NOT NULL,
              latitude      double precision NOT NULL,
              longitude     double precision NOT NULL,
              feature_class char(1) NOT NULL,
              feature_code  text NOT NULL);""")
    psql("CREATE INDEX IF NOT EXISTS autopilot_landmarks_pos "
         "ON autopilot_landmarks (latitude, longitude);")

    wanted = query("SELECT DISTINCT e.country FROM asset_exif e "
                   "JOIN asset a ON a.id = e.\"assetId\" AND a.\"deletedAt\" IS NULL "
                   "WHERE e.country IS NOT NULL;")
    if not wanted:
        print("  no country on any photo yet: nothing to fetch")
        return
    print("  countries in the library: %s" % ", ".join(sorted(wanted)))

    # GeoNames' own name-to-code table, so no mapping is hard-coded here
    info = urllib.request.urlopen(GEONAMES + "countryInfo.txt", timeout=60).read().decode("utf-8")
    by_name = {}
    for line in info.splitlines():
        if line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) > 4:
            by_name[f[4].strip().lower()] = f[0].strip()

    codes, unknown = [], []
    for name in wanted:
        code = by_name.get(name.strip().lower())
        (codes.append(code) if code else unknown.append(name))
    if unknown:
        print("  no GeoNames code for: %s (skipped)" % ", ".join(unknown))

    already = set(query("SELECT DISTINCT country FROM autopilot_landmarks;"))
    if "--all" in sys.argv:
        already = set()

    for code in sorted(set(codes)):
        if code in already:
            print("  %s: already loaded" % code)
            continue
        print("  %s: downloading ..." % code, end=" ", flush=True)
        try:
            blob = urllib.request.urlopen(GEONAMES + code + ".zip", timeout=300).read()
        except Exception as e:
            print("failed (%s)" % e)
            continue
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            raw = z.read(code + ".txt").decode("utf-8", "replace")

        rows = []
        for line in raw.splitlines():
            f = line.split("\t")
            if len(f) < 9 or f[7] not in DESTINATIONS:
                continue
            # name, lat, lon must all be present to be usable
            if not (f[1] and f[4] and f[5]):
                continue
            rows.append("%s\t%s\t%s\t%s\t%s\t%s" % (code, f[1].replace("\t", " "), f[4], f[5], f[6], f[7]))

        if not rows:
            print("no usable places")
            continue
        tsv = "/tmp/landmarks_%s.tsv" % code
        io.open(tsv, "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
        subprocess.run(["docker", "cp", tsv, "%s:%s" % (DB, tsv)], check=True, capture_output=True)
        psql("DELETE FROM autopilot_landmarks WHERE country = '%s';" % code)
        psql("COPY autopilot_landmarks (country, name, latitude, longitude, feature_class, "
             "feature_code) FROM '%s';" % tsv)
        print("%d places" % len(rows))

    total = query("SELECT count(*) || ' places, ' || count(DISTINCT country) || ' countries' "
                  "FROM autopilot_landmarks;")
    print("  now in the table: %s" % (total[0].strip() if total else "?"))


if __name__ == "__main__":
    main()
