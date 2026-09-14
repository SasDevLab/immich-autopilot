-- Versione 3: eventi lontani da casa + occasioni riconosciute a casa.
-- Tutto il resto non e' un evento e va nel raccoglitore del mese (query a parte).
WITH cfg AS (
  SELECT
    max(value) FILTER (WHERE key='owner_email')    AS owner_email,
    max(value) FILTER (WHERE key='timezone')       AS tz,
    max(value) FILTER (WHERE key='word_threshold')::numeric  AS word_threshold,
    max(value) FILTER (WHERE key='min_presence')::numeric    AS min_presence,
    max(value) FILTER (WHERE key='min_photos')::int          AS min_photos,
    max(value) FILTER (WHERE key='gap_days')::int            AS gap_days,
    max(value) FILTER (WHERE key='max_span_days')::int       AS max_span,
    -- how far two consecutive days must be to belong to different events
    max(value) FILTER (WHERE key='split_km')::numeric        AS split_km,
    -- beyond this distance from home, any period is a trip
    max(value) FILTER (WHERE key='home_km')::numeric         AS home_km,
    -- how present a rule's required word must be to count as satisfied
    max(value) FILTER (WHERE key='required_share')::numeric   AS required_share
  FROM autopilot_config
),
sim AS (
  SELECT s."assetId" aid, d.word, 1 - (s.embedding <=> d.vector) v
  FROM smart_search s
  CROSS JOIN autopilot_dictionary d
  JOIN asset a ON a.id = s."assetId" AND a."deletedAt" IS NULL
),
stat AS (SELECT word, avg(v) m, stddev_pop(v) sd FROM sim GROUP BY word),
forti AS (
  SELECT sim.aid, sim.word FROM sim JOIN stat ON stat.word = sim.word
  WHERE stat.sd > 0 AND (sim.v - stat.m) / stat.sd >= (SELECT word_threshold FROM cfg)
),
-- I nomi di citta' vanno ripuliti prima di finire in un titolo: Immich
-- restituisce gli arrondissement ("Marseille 06") e i quartieri, cosi' l'album
-- di marzo si sarebbe chiamato "Marseille 02". Prima si toglie il numero, poi
-- si traduce dove l'italiano esiste - l'utente scrive Nizza, non Nice.
libere AS (
  SELECT a.id aid, (a."fileCreatedAt" AT TIME ZONE (SELECT tz FROM cfg))::date g,
         coalesce(n.local_name, pulita.c) city,
         e.latitude lat, e.longitude lon
  FROM asset a
  JOIN "user" u ON u.id = a."ownerId" AND ((SELECT owner_email FROM cfg) = '' OR u.email = (SELECT owner_email FROM cfg))
  LEFT JOIN asset_exif e ON e."assetId" = a.id
  LEFT JOIN LATERAL (SELECT btrim(regexp_replace(e.city, '\s+[0-9]+$', '')) c) pulita ON true
  LEFT JOIN autopilot_place_names n ON n.foreign_name = pulita.c
  WHERE a."deletedAt" IS NULL
    AND EXISTS (SELECT 1 FROM smart_search s WHERE s."assetId" = a.id)
    AND NOT EXISTS (SELECT 1 FROM album_asset aa WHERE aa."assetId" = a.id)
),
-- "Casa" non si scrive a mano, ma nemmeno si ricava dalla mediana di tutto:
-- con le foto concentrate in due zone (la Puglia e la Francia) la mediana delle
-- latitudini e quella delle longitudini, calcolate separatamente, cadono in un
-- punto che non corrisponde a nessun luogo - era finita vicino a Vieste, e cosi'
-- Giovinazzo risultava a 77 km da casa e Vieste a 2.
-- Casa e' la citta' dove si passano piu' GIORNI: Giovinazzo 67, Bari 7. Si
-- contano i giorni e non le foto, perche' una sola festa fa molte foto in un
-- posto dove non si abita.
casa AS (
  SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY e.latitude) la,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY e.longitude) lo
  FROM asset_exif e
  JOIN asset a ON a.id = e."assetId" AND a."deletedAt" IS NULL
  WHERE e.city IS NOT NULL
    AND btrim(regexp_replace(e.city, '\s+[0-9]+$', '')) = (
      SELECT btrim(regexp_replace(e2.city, '\s+[0-9]+$', ''))
      FROM asset_exif e2
      JOIN asset a2 ON a2.id = e2."assetId" AND a2."deletedAt" IS NULL
      WHERE e2.city IS NOT NULL
      GROUP BY 1
      ORDER BY count(DISTINCT (a2."fileCreatedAt" AT TIME ZONE (SELECT tz FROM cfg))::date) DESC,
               count(*) DESC
      LIMIT 1)
),
giorni AS (
  SELECT g, count(*) n,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY lat) la,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY lon) lo
  FROM libere GROUP BY g
),
passi AS (
  SELECT g, n, la, lo, lag(g) OVER (ORDER BY g) g0,
         lag(la) OVER (ORDER BY g) la0, lag(lo) OVER (ORDER BY g) lo0
  FROM giorni
),
marcati AS (
  SELECT g, CASE WHEN g0 IS NULL OR g - g0 > (SELECT gap_days FROM cfg)
                   OR (la IS NOT NULL AND la0 IS NOT NULL AND
                       6371*acos(least(1,greatest(-1, sin(radians(la0))*sin(radians(la))
                         + cos(radians(la0))*cos(radians(la))*cos(radians(lo-lo0))))) > (SELECT split_km FROM cfg))
                 THEN 1 ELSE 0 END n
  FROM passi
),
isole AS (SELECT g, sum(n) OVER (ORDER BY g) isola FROM marcati),
ev AS (SELECT i.isola, l.aid, l.g, l.city, l.lat, l.lon FROM libere l JOIN isole i ON i.g = l.g),
dim AS (SELECT isola, count(DISTINCT aid) n FROM ev GROUP BY isola),
comp AS (
  SELECT ev.isola, f.word, round(count(DISTINCT f.aid)::numeric / max(dim.n), 3) quota
  FROM ev JOIN forti f ON f.aid = ev.aid JOIN dim ON dim.isola = ev.isola
  GROUP BY ev.isola, f.word
  HAVING count(DISTINCT f.aid)::numeric / max(dim.n) >= (SELECT min_presence FROM cfg)
),
top5 AS (
  SELECT isola, word FROM (
    SELECT isola, word, row_number() OVER (PARTITION BY isola ORDER BY quota DESC) r
    FROM comp) x WHERE r <= 5
),
giorni_buoni AS (
  SELECT DISTINCT ev.isola, ev.g FROM ev
  JOIN forti f ON f.aid = ev.aid
  JOIN top5 t ON t.isola = ev.isola AND t.word = f.word
),
potato_grezzo AS (SELECT isola, min(g) dal, max(g) al FROM giorni_buoni GROUP BY isola),
-- Una giornata passata INTERAMENTE a casa non appartiene a un evento che si
-- svolge altrove. Tre giorni di mare a Vieste si tiravano dietro il rientro e
-- i due giorni dopo a Giovinazzo; il concerto a Caserta si portava una pizza a
-- Bari e una serata in paese.
--
-- La condizione e' "TUTTE le foto del giorno", non "il baricentro del giorno":
-- la giornata della partenza ha due foto all'aeroporto di Bari e undici in
-- Francia, e deve restare intera, perche' l'aeroporto fa parte del viaggio. I
-- giorni da togliere invece sono puri - tre foto su tre a casa, sei su sei.
giorni_a_casa AS (
  SELECT t.isola, ev.g
  FROM potato_grezzo t
  JOIN ev ON ev.isola = t.isola AND ev.g BETWEEN t.dal AND t.al
  CROSS JOIN casa h
  WHERE ev.lat IS NOT NULL
  GROUP BY t.isola, ev.g, h.la, h.lo
  HAVING count(*) FILTER (
           WHERE 6371*acos(least(1,greatest(-1,
             sin(radians(h.la))*sin(radians(ev.lat))
             + cos(radians(h.la))*cos(radians(ev.lat))*cos(radians(ev.lon - h.lo)))))
                 > (SELECT home_km FROM cfg)) = 0
),
-- Se anche il nucleo dell'evento e' a casa non si toglie niente: un compleanno
-- in paese e' fatto per forza di giorni passati a casa.
nucleo AS (
  SELECT t.isola, t.dal, t.al,
         max(6371*acos(least(1,greatest(-1,
           sin(radians(h.la))*sin(radians(ev.lat))
           + cos(radians(h.la))*cos(radians(ev.lat))*cos(radians(ev.lon - h.lo)))))) km_max
  FROM potato_grezzo t
  JOIN ev ON ev.isola = t.isola AND ev.g BETWEEN t.dal AND t.al
  CROSS JOIN casa h
  WHERE ev.lat IS NOT NULL
  GROUP BY t.isola, t.dal, t.al
),
giorni_tenuti AS (
  SELECT n.isola, ev.g
  FROM nucleo n
  JOIN ev ON ev.isola = n.isola AND ev.g BETWEEN n.dal AND n.al
  WHERE n.km_max <= (SELECT home_km FROM cfg)
     OR NOT EXISTS (SELECT 1 FROM giorni_a_casa c WHERE c.isola = n.isola AND c.g = ev.g)
  GROUP BY n.isola, ev.g
),
potato AS (SELECT isola, min(g) dal, max(g) al FROM giorni_tenuti GROUP BY isola),
-- Un'occasione RICONOSCIUTA non e' "una parola frequente": e' un gruppo di
-- parole che una regola attiva pretende, tutte presenti. Senza questo passavano
-- 'giocattolo 80%' (sono solo giocattoli sul tappeto) e 'schermo 48%' (la vita
-- di tutti i giorni), mentre il compleanno e il concerto sono occasioni vere.
-- Le regole stanno in autopilot_rules, quindi la soglia non la decido io qui:
-- basta aggiungere o togliere una regola per cambiare cosa conta come evento.
gruppi AS (
  SELECT r.type, r.months, g.ord, jsonb_array_elements_text(g.gruppo) AS parola
  FROM autopilot_rules r
  CROSS JOIN LATERAL jsonb_array_elements(r.required::jsonb)
       WITH ORDINALITY AS g(gruppo, ord)
  WHERE r.active
),
occasioni AS (
  SELECT c.isola
  FROM comp c
  JOIN gruppi gr ON gr.parola = c.word AND c.quota >= (SELECT required_share FROM cfg)
  -- e il mese deve tornare: senza questo il 3-9 aprile passava come Natale,
  -- perche' fra i giocattoli il modello riconosceva un presepe al 47%
  JOIN (SELECT isola, min(g) g0 FROM ev GROUP BY isola) q ON q.isola = c.isola
  WHERE gr.months IS NULL OR extract(month FROM q.g0)::int = ANY(gr.months)
  GROUP BY c.isola, gr.type, gr.ord
  HAVING count(DISTINCT gr.parola) = (SELECT count(DISTINCT g2.parola) FROM gruppi g2
                                       WHERE g2.type = gr.type AND g2.ord = gr.ord)
),
-- quanto dista da casa il baricentro dell'isola potata
lontananza AS (
  SELECT p.isola, p.dal, p.al,
         6371*acos(least(1,greatest(-1,
           sin(radians(c.la))*sin(radians(percentile_cont(0.5) WITHIN GROUP (ORDER BY ev.lat)))
           + cos(radians(c.la))*cos(radians(percentile_cont(0.5) WITHIN GROUP (ORDER BY ev.lat)))
           * cos(radians(percentile_cont(0.5) WITHIN GROUP (ORDER BY ev.lon) - c.lo))))) km_da_casa
  FROM potato p JOIN ev ON ev.isola = p.isola CROSS JOIN casa c
  WHERE ev.g BETWEEN p.dal AND p.al AND ev.lat IS NOT NULL
  GROUP BY p.isola, p.dal, p.al, c.la, c.lo
),
-- Un'occasione puo' stare in UN SOLO GIORNO dentro settimane di vita normale, e
-- allora sul periodo intero le sue prove sono minoranza e sparisce: un concerto
-- di 8 foto, con palco e folla al 75% di quella giornata, annegava in tre
-- settimane da 20 foto e veniva scartato (Caparezza, 4 settembre).
--
-- Quindi le stesse regole si valutano anche giorno per giorno, ma SOLO nei
-- periodi a casa che non sono gia' diventati un evento. Dentro un viaggio no:
-- altrimenti i tre giorni a Caserta, che contengono un concerto, si
-- spezzerebbero in due album - ed e' proprio cio' che non si vuole.
dim_giorno AS (SELECT isola, g, count(DISTINCT aid) n FROM ev GROUP BY isola, g),
comp_giorno AS (
  SELECT ev.isola, ev.g, f.word,
         round(count(DISTINCT f.aid)::numeric / max(d.n), 3) quota
  FROM ev
  JOIN forti f ON f.aid = ev.aid
  JOIN dim_giorno d ON d.isola = ev.isola AND d.g = ev.g
  GROUP BY ev.isola, ev.g, f.word
),
occasioni_giorno AS (
  SELECT c.isola, c.g
  FROM comp_giorno c
  JOIN gruppi gr ON gr.parola = c.word AND c.quota >= (SELECT required_share FROM cfg)
  WHERE gr.months IS NULL OR extract(month FROM c.g)::int = ANY(gr.months)
  GROUP BY c.isola, c.g, gr.type, gr.ord
  HAVING count(DISTINCT gr.parola) = (SELECT count(DISTINCT g2.parola) FROM gruppi g2
                                       WHERE g2.type = gr.type AND g2.ord = gr.ord)
),
-- i periodi che diventano album da soli: i loro giorni non vanno ripescati
eventi_periodo AS (
  SELECT l.isola
  FROM lontananza l JOIN ev ON ev.isola = l.isola AND ev.g BETWEEN l.dal AND l.al
  GROUP BY l.isola, l.dal, l.al, l.km_da_casa
  HAVING count(DISTINCT ev.aid) >= (SELECT min_photos FROM cfg)
     AND l.al - l.dal <= (SELECT max_span FROM cfg)
     AND (coalesce(l.km_da_casa, 0) > (SELECT home_km FROM cfg)
          OR EXISTS (SELECT 1 FROM occasioni o WHERE o.isola = l.isola))
),
giornate AS (
  SELECT og.isola, og.g
  FROM occasioni_giorno og
  JOIN lontananza l ON l.isola = og.isola
  WHERE coalesce(l.km_da_casa, 0) <= (SELECT home_km FROM cfg)
    AND NOT EXISTS (SELECT 1 FROM eventi_periodo ep WHERE ep.isola = og.isola)
)
SELECT l.dal::text AS from_date, l.al::text AS to_date,
       count(DISTINCT ev.aid) AS photos,
       mode() WITHIN GROUP (ORDER BY ev.city) FILTER (WHERE ev.city IS NOT NULL) AS city,
       (SELECT json_object_agg(c.word, c.quota) FROM comp c WHERE c.isola = l.isola) AS concepts,
       json_agg(DISTINCT ev.aid) AS ids,
       -- se esiste gia' un album a cavallo di queste date lo si allunga invece
       -- di crearne un secondo quasi identico
       (SELECT aa.album_id FROM autopilot_albums aa
         WHERE aa.to_date >= l.dal - (SELECT gap_days FROM cfg) AND aa.from_date <= l.al + (SELECT gap_days FROM cfg)
         ORDER BY aa.to_date DESC LIMIT 1) AS album_to_extend,
       (SELECT json_agg(json_build_object('type', r.type, 'required', r.required,
                                          'evidence', r.evidence, 'against', r.against))
          FROM autopilot_rules r WHERE r.active) AS rules,
       (SELECT max(value) FROM autopilot_config WHERE key='margin')::numeric AS margin,
       (SELECT max(value) FROM autopilot_config WHERE key='min_presence')::numeric AS min_presence,
       (SELECT max(value) FROM autopilot_config WHERE key='immich_url') AS immich_url
FROM lontananza l JOIN ev ON ev.isola = l.isola AND ev.g BETWEEN l.dal AND l.al
GROUP BY l.isola, l.dal, l.al, l.km_da_casa
HAVING count(DISTINCT ev.aid) >= (SELECT min_photos FROM cfg) AND l.al - l.dal <= (SELECT max_span FROM cfg)
   -- Lontano da casa basta il viaggio, anche piccolo. A casa serve un'occasione
   -- vera, e il segno di un'occasione e' una prova dominante: il compleanno ha
   -- palloncini all'80%, i giorni qualunque non passano il 26%. Il conteggio non
   -- bastava, perche' l'isola di vita quotidiana faceva esattamente 20 foto.
   --
   -- 40 km e non 100: Vieste, che e' una vacanza vera, dista 88 km, e in Puglia
   -- il mare e' vicino. Bari resta dentro casa a 17 km, ed e' giusto - andarci a
   -- fare una commissione non e' un evento.
   AND (coalesce(l.km_da_casa, 0) > (SELECT home_km FROM cfg)
        OR EXISTS (SELECT 1 FROM occasioni o WHERE o.isola = l.isola))

UNION ALL

-- le giornate-evento in mezzo alla vita normale: ognuna un album per se'
SELECT gi.g::text, gi.g::text,
       count(DISTINCT ev.aid),
       mode() WITHIN GROUP (ORDER BY ev.city) FILTER (WHERE ev.city IS NOT NULL),
       (SELECT json_object_agg(c.word, c.quota) FROM comp_giorno c
         WHERE c.isola = gi.isola AND c.g = gi.g),
       json_agg(DISTINCT ev.aid),
       (SELECT aa.album_id FROM autopilot_albums aa
         WHERE aa.to_date >= gi.g AND aa.from_date <= gi.g
         ORDER BY aa.to_date DESC LIMIT 1),
       (SELECT json_agg(json_build_object('type', r.type, 'required', r.required,
                                          'evidence', r.evidence, 'against', r.against))
          FROM autopilot_rules r WHERE r.active),
       (SELECT max(value) FROM autopilot_config WHERE key='margin')::numeric,
       (SELECT max(value) FROM autopilot_config WHERE key='min_presence')::numeric,
       (SELECT max(value) FROM autopilot_config WHERE key='immich_url')
FROM giornate gi
JOIN ev ON ev.isola = gi.isola AND ev.g = gi.g
GROUP BY gi.isola, gi.g
HAVING count(DISTINCT ev.aid) >= (SELECT min_photos FROM cfg)
ORDER BY 1;
