CREATE TABLE IF NOT EXISTS autopilot_riepiloghi (
  album_id    uuid PRIMARY KEY,
  testo       text NOT NULL,
  foto_viste  int NOT NULL,
  foto_totali int NOT NULL,
  scritto     timestamptz NOT NULL DEFAULT now()
);
SELECT '  autopilot_riepiloghi: ' || count(*) || ' righe' FROM autopilot_riepiloghi;
