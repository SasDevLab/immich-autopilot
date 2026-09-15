
-- Una riga per persona: le sue misure massime e l'elenco dei volti candidati.
-- Salta chi ha una copertina scelta a mano (diversa da quella che questa
-- procedura aveva impostato l'ultima volta): quelle scelte vincono per sempre.
WITH ammesse AS (
  SELECT p.id
  FROM person p
  JOIN "user" u ON u.id = p."ownerId"
  LEFT JOIN autopilot_covers ac ON ac.person_id = p.id
  -- In Immich le persone sono PRIVATE di ogni utente: ognuno ha le proprie,
  -- riconosciute sulle proprie foto. La chiave API con cui si applica la
  -- modifica appartiene a questo utente, quindi tentare di scrivere sulle
  -- persone di un altro account darebbe 403 e un allarme Telegram ogni notte.
  WHERE u.email = 'marolla1989@gmail.com'
    AND (ac.person_id IS NULL OR p."faceAssetId" IS NOT DISTINCT FROM ac.face_id)
),
centro AS (
  SELECT af."personId" pid, avg(fs.embedding) media
  FROM asset_face af JOIN face_search fs ON fs."faceId" = af.id
  JOIN asset a2 ON a2.id = af."assetId" AND a2."deletedAt" IS NULL
  WHERE af."personId" IN (SELECT id FROM ammesse) AND af."deletedAt" IS NULL
    -- La faccia media si calcola SOLO sulle foto recenti. Con 451 volti del
    -- 2021 contro 168 del 2026, la media era il volto di cinque anni fa e
    -- vincevano sempre le scansioni vecchie: la foto piu' TIPICA non e' la
    -- foto piu' ATTUALE.
    AND a2."fileCreatedAt" > now() - ((SELECT max(value) FROM autopilot_config
                                        WHERE key='cover_months') || ' months')::interval
  GROUP BY af."personId"
),
volti AS (
  SELECT af."personId" pid, af.id fid, af."assetId" aid,
         1 - (fs.embedding <=> c.media) tip,
         (af."boundingBoxX2"-af."boundingBoxX1")*(af."boundingBoxY2"-af."boundingBoxY1") area,
         (af."boundingBoxX1" <= 0.02*af."imageWidth" OR af."boundingBoxY1" <= 0.02*af."imageHeight"
          OR af."boundingBoxX2" >= 0.98*af."imageWidth" OR af."boundingBoxY2" >= 0.98*af."imageHeight") tagliato,
         (SELECT count(*) FROM asset_face o
           WHERE o."assetId"=af."assetId" AND o.id<>af.id AND o."deletedAt" IS NULL
             AND o."boundingBoxX1" < af."boundingBoxX2"+0.4*(af."boundingBoxX2"-af."boundingBoxX1")
             AND o."boundingBoxX2" > af."boundingBoxX1"-0.4*(af."boundingBoxX2"-af."boundingBoxX1")
             AND o."boundingBoxY1" < af."boundingBoxY2"+0.4*(af."boundingBoxY2"-af."boundingBoxY1")
             AND o."boundingBoxY2" > af."boundingBoxY1"-0.4*(af."boundingBoxY2"-af."boundingBoxY1")) vicini,
         to_char(a."fileCreatedAt",'YYYY-MM-DD') data,
         -- quanto il volto riempie la foto: il filtro 'tagliato' guarda solo i
         -- bordi, ma un volto al 7% dell'inquadratura, ritagliato in quadrato
         -- per la miniatura, viene fuori stretto e sembra tagliato lo stesso
         (af."boundingBoxX2"-af."boundingBoxX1")*(af."boundingBoxY2"-af."boundingBoxY1")::numeric
           / nullif(af."imageWidth"*af."imageHeight", 0) AS quota,
         -- quanto la foto somiglia a "occhiali da sole", in scarti dalla media
         -- dell'archivio: sopra i 2 scarti stanno le giornate al mare, sotto
         -- lo zero i ritratti in casa. Misurato: +4,8 contro -2,2.
         coalesce((SELECT (1 - (ss.embedding <=> dd.vector) - st.media) / nullif(st.scarto, 0)
                   FROM smart_search ss
                   CROSS JOIN (SELECT vector FROM autopilot_dictionary WHERE word='occhiali') dd
                   CROSS JOIN (SELECT avg(1 - (s2.embedding <=> d2.vector)) media,
                                      stddev_pop(1 - (s2.embedding <=> d2.vector)) scarto
                               FROM smart_search s2
                               CROSS JOIN (SELECT vector FROM autopilot_dictionary WHERE word='occhiali') d2) st
                   WHERE ss."assetId" = af."assetId"), 0) AS occhiali,
         -- Il bianco e nero non e' deducibile dai dati EXIF (le foto
         -- monocromatiche restano registrate come sRGB) ne' dalla ricerca
         -- semantica (metteva foto a colori tra i primi risultati di "black
         -- and white"). Va misurato sui pixel, quindi e' precalcolato in
         -- autopilot_colour. Una foto mai misurata conta come a colori.
         coalesce(col.monochrome, false) bn,
         -- il giudizio sul RITAGLIO del volto: la geometria non sa dire se una
         -- faccia sta masticando o ha gli occhiali da sole, il modello si' - ma
         -- solo guardando il ritaglio, non la foto intera
         coalesce(q.pro - q.contro, 0) AS voto,
         -- nitidezza misurata sui pixel, confrontata poi fra i candidati
         coalesce(q.sharpness, 0) AS nitidezza
  FROM asset_face af
  JOIN face_search fs ON fs."faceId" = af.id
  JOIN centro c ON c.pid = af."personId"
  JOIN asset a ON a.id = af."assetId" AND a."deletedAt" IS NULL
  JOIN asset_file f ON f."assetId" = af."assetId" AND f.type = 'preview'
  LEFT JOIN autopilot_colour col ON col.asset_id = af."assetId"
  LEFT JOIN autopilot_face_quality q ON q.face_id = af.id
  WHERE af."deletedAt" IS NULL AND af."isVisible" = true
    -- Chi non ha foto recenti non compare affatto: meglio tenere la copertina
    -- vecchia che sostituirla con un'altra foto altrettanto vecchia.
    AND a."fileCreatedAt" > now() - ((SELECT max(value) FROM autopilot_config
                                       WHERE key='cover_months') || ' months')::interval
)
SELECT v.pid AS person_id,
       max(v.tip)  AS tmax,
       max(v.area) AS amax,
       (SELECT "faceAssetId" FROM person WHERE id = v.pid) AS attuale,
       json_agg(json_build_object('fid', v.fid, 'aid', v.aid, 'tip', v.tip, 'area', v.area,
                                  'tagliato', v.tagliato, 'vicini', v.vicini, 'data', v.data,
                                  'bn', v.bn,
                                    -- senza questi due il codice li legge
                                    -- come 'non definiti', e i gradini che
                                    -- guardano la dimensione non scattano mai
                                    'quota', v.quota,
                                    'occhiali', v.occhiali,
                                    'voto', v.voto,
                                    'nitidezza', v.nitidezza)) AS candidati
FROM volti v
GROUP BY v.pid;
