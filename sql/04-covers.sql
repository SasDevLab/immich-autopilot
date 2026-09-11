-- Which face should be a person's cover photo.
--
-- Immich picks whichever face crop scored highest at detection, which has
-- nothing to do with whether the picture is any good: galleries fill up with
-- ears, half faces and cut-off eyes.
--
-- The criteria below are preferences in order, not filters. With hard filters,
-- people who have exactly one detected face come out with no candidate at all -
-- and in a real library that is a sizeable minority.
--
-- Returns one row per person that needs changing. It writes nothing: the change
-- goes through Immich's API, which is the only thing that also regenerates the
-- cropped thumbnail on disk. Setting person."faceAssetId" directly moves the
-- pointer and leaves the old image in place.
WITH cfg AS (
  SELECT
    max(valore) FILTER (WHERE chiave='owner_email') AS owner_email,
    max(valore) FILTER (WHERE chiave='immich_url')   AS immich_url,
    max(valore) FILTER (WHERE chiave='cover_max_distance')::numeric AS max_dist,
    max(valore) FILTER (WHERE chiave='cover_min_area')::numeric AS min_area
  FROM curator_config
),
eleggibili AS (
  -- people whose cover still matches what this job last set: anything else was
  -- chosen by hand, and a manual choice wins for good.
  -- Config is read with scalar subqueries rather than joining cfg: a comma-join
  -- in the middle of a join chain attaches the next LEFT JOIN to the wrong
  -- table, which is a quiet way to get wrong answers.
  SELECT p.id
  FROM person p
  JOIN "user" u ON u.id = p."ownerId"
  LEFT JOIN curator_covers cc ON cc.person_id = p.id
  WHERE ((SELECT owner_email FROM cfg) = '' OR u.email = (SELECT owner_email FROM cfg))
    AND (cc.person_id IS NULL OR p."faceAssetId" IS NOT DISTINCT FROM cc.face_id)
),
centro AS (
  -- the "average face" of each person: the most typical face is usually the
  -- frontal, well-lit one, because odd angles sit far from the average
  SELECT af."personId" pid, avg(fs.embedding) media
  FROM asset_face af
  JOIN face_search fs ON fs."faceId" = af.id
  WHERE af."personId" IN (SELECT id FROM eleggibili) AND af."deletedAt" IS NULL
  GROUP BY af."personId"
),
volti AS (
  SELECT af."personId" pid, af.id fid, af."assetId" aid,
         1 - (fs.embedding <=> c.media) AS tipicita,
         (af."boundingBoxX2"-af."boundingBoxX1")*(af."boundingBoxY2"-af."boundingBoxY1") AS area,
         -- a box touching the frame means the face is cut off
         (af."boundingBoxX1" <= 0.02*af."imageWidth" OR af."boundingBoxY1" <= 0.02*af."imageHeight"
          OR af."boundingBoxX2" >= 0.98*af."imageWidth" OR af."boundingBoxY2" >= 0.98*af."imageHeight") AS tagliato,
         -- another face inside the crop means the cover shows two people
         (SELECT count(*) FROM asset_face o
           WHERE o."assetId" = af."assetId" AND o.id <> af.id AND o."deletedAt" IS NULL
             AND o."boundingBoxX1" < af."boundingBoxX2" + 0.4*(af."boundingBoxX2"-af."boundingBoxX1")
             AND o."boundingBoxX2" > af."boundingBoxX1" - 0.4*(af."boundingBoxX2"-af."boundingBoxX1")
             AND o."boundingBoxY1" < af."boundingBoxY2" + 0.4*(af."boundingBoxY2"-af."boundingBoxY1")
             AND o."boundingBoxY2" > af."boundingBoxY1" - 0.4*(af."boundingBoxY2"-af."boundingBoxY1")) AS vicini,
         a."fileCreatedAt" AS quando,
         coalesce(col.bianco_e_nero, false) AS bianco_e_nero
  FROM asset_face af
  JOIN face_search fs ON fs."faceId" = af.id
  JOIN centro c ON c.pid = af."personId"
  JOIN asset a ON a.id = af."assetId" AND a."deletedAt" IS NULL
  JOIN asset_file f ON f."assetId" = af."assetId" AND f.type = 'preview'
  LEFT JOIN curator_colour col ON col.asset_id = af."assetId"
  WHERE af."deletedAt" IS NULL AND af."isVisible" = true
),
massimi AS (
  SELECT pid, max(tipicita) tip_max, max(area) area_max FROM volti GROUP BY pid
),
scelta AS (
  SELECT DISTINCT ON (v.pid) v.pid, v.fid, v.aid
  FROM volti v JOIN massimi m ON m.pid = v.pid
  ORDER BY v.pid,
           -- colour first: monochrome is demoted, never excluded, so a person
           -- whose only decent shots are black and white keeps one
           v.bianco_e_nero,
           (CASE WHEN v.tagliato THEN 1 ELSE 0 END),
           (CASE WHEN v.tipicita >= m.tip_max - (SELECT max_dist FROM cfg)
                  AND v.area >= (SELECT min_area FROM cfg) * m.area_max THEN 0 ELSE 1 END),
           (CASE WHEN v.vicini = 0 THEN 0 ELSE 1 END),
           v.quando DESC,
           v.area DESC
)
SELECT s.pid AS person_id,
       s.fid AS face_id,
       s.aid AS asset_id,
       coalesce(nullif(p.name, ''), '(senza nome)') AS nome,
       (SELECT immich_url FROM cfg) AS immich_url
FROM scelta s
JOIN person p ON p.id = s.pid
WHERE p."faceAssetId" IS DISTINCT FROM s.fid;
