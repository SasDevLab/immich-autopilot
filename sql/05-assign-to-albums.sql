-- Unfiled photos that belong to an album which already exists.
--
-- Not by distance to the album's centre. An album holding a church, a dance and
-- a cake has its average somewhere between the three, resembling none of them,
-- and judging a photo against that point is like judging a family by its mean
-- height. Measured on a real library it put 20% of photos belonging to no album
-- into one anyway.
--
-- Instead: the nearest already-filed photos, and where THEY live. If nearly all
-- of them sit in one album, that is the answer.
--
-- The decisive part is the second condition. Content says WHAT a photo is; it
-- cannot say WHICH, because two studio shoots two years apart are the same
-- pixels. The date can. Requiring the neighbours to be close in time as well
-- took false positives from 12% to zero on the same library, with precision at
-- 99.9%.
--
-- Applied to the album's own date range this does nothing - albums that collect
-- photos over years accept anything. It has to be the neighbours' dates.
WITH cfg AS (
  SELECT
    max(value) FILTER (WHERE key='owner_email') AS owner_email,
    max(value) FILTER (WHERE key='timezone')    AS tz,
    max(value) FILTER (WHERE key='immich_url')  AS immich_url,
    max(value) FILTER (WHERE key='assign_neighbours')::int     AS k,
    max(value) FILTER (WHERE key='assign_similarity')::numeric AS min_sim,
    max(value) FILTER (WHERE key='assign_agreement')::numeric  AS agreement,
    max(value) FILTER (WHERE key='assign_days')::int           AS max_days
  FROM curator_config
),
filed AS (
  SELECT aa."albumId", s."assetId" aid, s.embedding,
         (a."fileCreatedAt" AT TIME ZONE (SELECT tz FROM cfg))::date d
  FROM album_asset aa
  JOIN album al ON al.id = aa."albumId" AND al."deletedAt" IS NULL
  JOIN smart_search s ON s."assetId" = aa."assetId"
  JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL
),
unfiled AS (
  SELECT s."assetId" aid, s.embedding,
         (a."fileCreatedAt" AT TIME ZONE (SELECT tz FROM cfg))::date d
  FROM smart_search s
  JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL
  JOIN "user" u ON u.id = a."ownerId"
  WHERE ((SELECT owner_email FROM cfg) = '' OR u.email = (SELECT owner_email FROM cfg))
    AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = s."assetId")
),
neighbours AS (
  SELECT u.aid, n."albumId", n.sim
  FROM unfiled u
  CROSS JOIN LATERAL (
    SELECT f."albumId", 1 - (f.embedding <=> u.embedding) sim
    FROM filed f
    WHERE abs(f.d - u.d) <= (SELECT max_days FROM cfg)
    ORDER BY f.embedding <=> u.embedding
    LIMIT (SELECT k FROM cfg)
  ) n
),
tally AS (
  SELECT aid, "albumId",
         count(*)   AS votes,
         max(sim)   AS best
  FROM neighbours GROUP BY aid, "albumId"
),
winner AS (
  SELECT DISTINCT ON (t.aid) t.aid, t."albumId", t.votes, t.best,
         (SELECT count(*) FROM neighbours n WHERE n.aid = t.aid) AS total
  FROM tally t ORDER BY t.aid, t.votes DESC, t.best DESC
)
SELECT w.aid AS asset_id,
       w."albumId" AS album_id,
       al."albumName" AS album_name,
       round(w.best::numeric, 3) AS similarity,
       w.votes, w.total,
       (SELECT immich_url FROM cfg) AS immich_url
FROM winner w
JOIN album al ON al.id = w."albumId"
WHERE w.total >= (SELECT k FROM cfg)                         -- enough neighbours in the window
  AND w.best >= (SELECT min_sim FROM cfg)                    -- and close enough
  AND w.votes::numeric / w.total >= (SELECT agreement FROM cfg)  -- and they agree
ORDER BY al."albumName", w.best DESC;
