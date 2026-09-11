-- Di cosa e' fatto ogni periodo di foto non ancora catalogate.
--
-- Nessun valore e' scritto qui dentro: tutto viene da curatore_config, cosi'
-- si regola senza toccare il workflow.
--
-- Le STATISTICHE si calcolano su tutto l'archivio, perche' quanto una parola
-- sia "vicina a tutto" e' una proprieta' della parola, non delle foto nuove.
-- Gli EVENTI invece si formano solo con le foto fuori da ogni album: cosi' il
-- curatore non duplica nulla e non tocca quello che l'utente ha organizzato.
WITH cfg AS (
  SELECT
    max(valore) FILTER (WHERE chiave='proprietario')    AS proprietario,
    max(valore) FILTER (WHERE chiave='fuso_orario')     AS fuso,
    max(valore) FILTER (WHERE chiave='soglia_scena')::numeric    AS soglia,
    max(valore) FILTER (WHERE chiave='presenza_minima')::numeric AS presenza,
    max(valore) FILTER (WHERE chiave='foto_minime')::int         AS minime,
    max(valore) FILTER (WHERE chiave='vuoto_giorni')::int        AS vuoto,
    max(valore) FILTER (WHERE chiave='durata_massima')::int      AS durata
  FROM curatore_config
),
sim AS (
  SELECT s."assetId" aid, d.parola, 1 - (s.embedding <=> d.vettore) v
  FROM smart_search s
  CROSS JOIN curatore_dizionario d
  JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL
),
stat AS (SELECT parola, avg(v) m, stddev_pop(v) sd FROM sim GROUP BY parola),
forti AS (
  -- una foto "contiene" un concetto quando si stacca dalla media di QUELLA
  -- parola: senza questa normalizzazione vincerebbero sempre i termini che
  -- somigliano un po' a tutto
  SELECT sim.aid, sim.parola
  FROM sim JOIN stat ON stat.parola = sim.parola, cfg
  WHERE stat.sd > 0 AND (sim.v - stat.m) / stat.sd >= cfg.soglia
),
libere AS (
  SELECT a.id aid, (a."fileCreatedAt" AT TIME ZONE (SELECT fuso FROM cfg))::date g, e.city
  FROM asset a
  JOIN "user" u ON u.id = a."ownerId"
  LEFT JOIN asset_exif e ON e."assetId" = a.id, cfg
  WHERE a."deletedAt" IS NULL
    AND (cfg.proprietario = '' OR u.email = cfg.proprietario)
    AND EXISTS (SELECT 1 FROM smart_search s WHERE s."assetId" = a.id)
    AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = a.id)
),
distinti AS (SELECT DISTINCT g FROM libere),
marcati AS (
  SELECT g, CASE WHEN lag(g) OVER (ORDER BY g) IS NULL
                   OR g - lag(g) OVER (ORDER BY g) > (SELECT vuoto FROM cfg)
                 THEN 1 ELSE 0 END n
  FROM distinti
),
isole AS (SELECT g, sum(n) OVER (ORDER BY g) isola FROM marcati),
ev AS (SELECT i.isola, l.aid, l.g, l.city FROM libere l JOIN isole i ON i.g = l.g),
dim AS (SELECT isola, count(DISTINCT aid) n FROM ev GROUP BY isola),
comp AS (
  -- i parametri si leggono con sottointerrogazioni scalari, non unendo cfg:
  -- una colonna di cfg dentro HAVING andrebbe raggruppata, e il senso si perde
  SELECT ev.isola, f.parola,
         round(count(DISTINCT f.aid)::numeric / max(dim.n), 3) quota
  FROM ev JOIN forti f ON f.aid = ev.aid JOIN dim ON dim.isola = ev.isola
  GROUP BY ev.isola, f.parola
  HAVING count(DISTINCT f.aid)::numeric / max(dim.n)
         >= (SELECT presenza FROM cfg)
)
SELECT min(ev.g)::text AS dal,
       max(ev.g)::text AS al,
       max(dim.n)      AS quante,
       mode() WITHIN GROUP (ORDER BY ev.city) FILTER (WHERE ev.city IS NOT NULL) AS citta,
       (SELECT json_object_agg(c.parola, c.quota) FROM comp c WHERE c.isola = ev.isola) AS concetti,
       json_agg(DISTINCT ev.aid) AS ids,
       -- un album gia' creato che confina con questo periodo: si allunga invece
       -- di crearne un secondo, cosi' un viaggio di piu' giorni resta unito
       (SELECT ca.album_id FROM curatore_album ca
         WHERE ca.al >= min(ev.g) - 2 AND ca.dal <= max(ev.g) + 2
         ORDER BY ca.al DESC LIMIT 1) AS album_da_estendere,
       (SELECT json_agg(json_build_object('tipo', r.tipo, 'necessarie', r.necessarie,
                                          'prove', r.prove, 'escluse', r.escluse))
          FROM curatore_regole r WHERE r.attiva) AS regole,
       (SELECT max(valore) FROM curatore_config WHERE chiave='margine')::numeric AS margine,
       (SELECT max(valore) FROM curatore_config WHERE chiave='presenza_minima')::numeric AS presenza,
       (SELECT max(valore) FROM curatore_config WHERE chiave='immich_url') AS immich_url
FROM ev JOIN dim ON dim.isola = ev.isola
GROUP BY ev.isola
HAVING max(dim.n) >= (SELECT minime FROM cfg)
   AND max(ev.g) - min(ev.g) <= (SELECT durata FROM cfg)
ORDER BY min(ev.g);
