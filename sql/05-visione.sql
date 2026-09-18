-- Cosa ha visto moondream in ogni fotografia.
--
-- Una riga per foto, con lo STATO: senza, una foto che va storta sparisce e non
-- se ne accorge nessuno. E si tengono due colonne per la categoria - quella
-- grezza detta dal modello e quella armonizzata - perche' il modello dira'
-- "viaggio", "viaggi", "gita" e "vacanza" per la stessa cosa.
CREATE TABLE IF NOT EXISTS autopilot_visione (
  asset_id         uuid PRIMARY KEY,
  stato            text NOT NULL DEFAULT 'da_fare',   -- da_fare | fatta | fallita
  inglese          text,           -- quello che ha detto moondream, com'e'
  descrizione      text,           -- la riga in italiano
  categoria_grezza text,           -- la parola scelta dal modello, libera
  categoria        text,           -- la stessa, armonizzata
  tentativi        int NOT NULL DEFAULT 0,
  errore           text,
  guardata         timestamptz,
  aggiunta         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS visione_da_fare ON autopilot_visione (stato, aggiunta);
CREATE INDEX IF NOT EXISTS visione_categoria ON autopilot_visione (categoria);

-- Le corrispondenze fra parola grezza e parola buona. E' PERMANENTE apposta:
-- armonizzando a blocchi, senza memoria, oggi "gita" finirebbe sotto "viaggi" e
-- domani sotto "vacanze", e l'etichetta tornerebbe inutile. Una volta deciso,
-- resta deciso.
CREATE TABLE IF NOT EXISTS autopilot_categorie (
  grezza   text PRIMARY KEY,
  buona    text NOT NULL,
  decisa   timestamptz NOT NULL DEFAULT now()
);

SELECT '  autopilot_visione: ' || count(*) || ' righe' FROM autopilot_visione;
SELECT '  autopilot_categorie: ' || count(*) || ' corrispondenze' FROM autopilot_categorie;
