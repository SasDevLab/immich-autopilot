-- What each not-yet-filed period of photos is made of.
--
-- Nothing is hard-coded here: every threshold comes from curator_config, so
-- tuning happens with an UPDATE and no workflow edit.
--
-- The STATISTICS are computed over the whole library, because how close a word
-- sits to everything is a property of the word, not of the new photos. The
-- EVENTS are formed only from photos outside every album: that way the curator
-- cannot duplicate anything, and never touches what a person filed by hand.
WITH cfg AS (
  SELECT
    max(value) FILTER (WHERE key='owner_email')    AS owner_email,
    max(value) FILTER (WHERE key='timezone')       AS tz,
    max(value) FILTER (WHERE key='word_threshold')::numeric AS word_threshold,
    max(value) FILTER (WHERE key='min_presence')::numeric   AS min_presence,
    max(value) FILTER (WHERE key='min_photos')::int         AS min_photos,
    max(value) FILTER (WHERE key='gap_days')::int           AS gap_days,
    max(value) FILTER (WHERE key='max_span_days')::int      AS max_span
  FROM curator_config
),
sim AS (
  SELECT s."assetId" aid, d.word, 1 - (s.embedding <=> d.vector) v
  FROM smart_search s
  CROSS JOIN curator_dictionary d
  JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL
),
stat AS (SELECT word, avg(v) m, stddev_pop(v) sd FROM sim GROUP BY word),
strong AS (
  -- A photo "contains" a concept when it stands above that word's own average.
  -- Without this normalisation the words that sit close to everything win every
  -- time, and the evidence stops meaning anything.
  SELECT sim.aid, sim.word
  FROM sim JOIN stat ON stat.word = sim.word
  WHERE stat.sd > 0
    AND (sim.v - stat.m) / stat.sd >= (SELECT word_threshold FROM cfg)
),
unfiled AS (
  SELECT a.id aid,
         (a."fileCreatedAt" AT TIME ZONE (SELECT tz FROM cfg))::date g,
         e.city
  FROM asset a
  JOIN "user" u ON u.id = a."ownerId"
  LEFT JOIN asset_exif e ON e."assetId" = a.id
  WHERE a."deletedAt" IS NULL
    AND ((SELECT owner_email FROM cfg) = '' OR u.email = (SELECT owner_email FROM cfg))
    AND EXISTS (SELECT 1 FROM smart_search s WHERE s."assetId" = a.id)
    AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = a.id)
),
days AS (SELECT DISTINCT g FROM unfiled),
marks AS (
  SELECT g, CASE WHEN lag(g) OVER (ORDER BY g) IS NULL
                   OR g - lag(g) OVER (ORDER BY g) > (SELECT gap_days FROM cfg)
                 THEN 1 ELSE 0 END n
  FROM days
),
islands AS (SELECT g, sum(n) OVER (ORDER BY g) island FROM marks),
ev AS (SELECT i.island, u.aid, u.g, u.city FROM unfiled u JOIN islands i ON i.g = u.g),
sizes AS (SELECT island, count(DISTINCT aid) n FROM ev GROUP BY island),
composition AS (
  SELECT ev.island, s.word,
         round(count(DISTINCT s.aid)::numeric / max(sizes.n), 3) share
  FROM ev JOIN strong s ON s.aid = ev.aid JOIN sizes ON sizes.island = ev.island
  GROUP BY ev.island, s.word
  HAVING count(DISTINCT s.aid)::numeric / max(sizes.n) >= (SELECT min_presence FROM cfg)
)
SELECT min(ev.g)::text AS from_date,
       max(ev.g)::text AS to_date,
       max(sizes.n)    AS photos,
       mode() WITHIN GROUP (ORDER BY ev.city) FILTER (WHERE ev.city IS NOT NULL) AS city,
       (SELECT json_object_agg(c.word, c.share) FROM composition c
         WHERE c.island = ev.island) AS concepts,
       json_agg(DISTINCT ev.aid) AS ids,
       -- an album already created that borders this period: extend it rather
       -- than start a second one, so a trip spanning nights stays whole
       (SELECT ca.album_id FROM curator_albums ca
         WHERE ca.to_date >= min(ev.g) - 2 AND ca.from_date <= max(ev.g) + 2
         ORDER BY ca.to_date DESC LIMIT 1) AS album_to_extend,
       (SELECT json_agg(json_build_object('type', r.type, 'required', r.required,
                                          'evidence', r.evidence, 'against', r.against))
          FROM curator_rules r WHERE r.active) AS rules,
       (SELECT max(value) FROM curator_config WHERE key='margin')::numeric AS margin,
       (SELECT max(value) FROM curator_config WHERE key='min_presence')::numeric AS min_presence,
       (SELECT max(value) FROM curator_config WHERE key='immich_url') AS immich_url
FROM ev JOIN sizes ON sizes.island = ev.island
GROUP BY ev.island
HAVING max(sizes.n) >= (SELECT min_photos FROM cfg)
   AND max(ev.g) - min(ev.g) <= (SELECT max_span FROM cfg)
ORDER BY min(ev.g);
