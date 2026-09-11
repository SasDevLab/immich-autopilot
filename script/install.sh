#!/bin/bash
# Installazione del curatore su un'istanza Immich esistente.
#
# Non modifica Immich: crea alcune tabelle con prefisso proprio nel suo database
# e lascia che i workflow n8n facciano il resto passando dalle API.
#
# Prerequisiti verificati qui sotto, perche' scoprirli a meta' installazione e'
# peggio che non partire.
set -u

DB=${IMMICH_DB:-immich_postgres}
SRV=${IMMICH_SERVER:-immich_server}
UTENTE=${IMMICH_DB_USER:-postgres}
NOME=${IMMICH_DB_NAME:-immich}
QUI=$(cd "$(dirname "$0")/.." && pwd)

errore() { echo "  ERRORE: $*"; exit 1; }
ok()     { echo "  ok  $*"; }

echo "=== verifica dei prerequisiti ==="

docker inspect "$DB" >/dev/null 2>&1 || errore "container '$DB' non trovato (IMMICH_DB per cambiarlo)"
ok "database: $DB"
docker inspect "$SRV" >/dev/null 2>&1 || errore "container '$SRV' non trovato (IMMICH_SERVER per cambiarlo)"
ok "server:   $SRV"

# pgvector: senza, niente confronti fra vettori
V=$(docker exec "$DB" psql -U "$UTENTE" -d "$NOME" -A -t \
      -c "SELECT extversion FROM pg_extension WHERE extname='vector';" 2>/dev/null)
[ -n "$V" ] || errore "estensione pgvector assente nel database"
ok "pgvector: $V"

# il modello deve essere multilingua, altrimenti le parole italiane non
# significano nulla per il modello e il riconoscimento e' casuale
M=$(docker exec "$DB" psql -U "$UTENTE" -d "$NOME" -A -t \
      -c "SELECT value #>> '{machineLearning,clip,modelName}' FROM system_metadata WHERE key='system-config';" 2>/dev/null)
M=${M:-ViT-B-32__openai}
echo "  modello CLIP di Immich: $M"
case "$M" in
  *i18n*|*nllb*|*xlm*|*XLM*|*multilingual*) ok "e' multilingua" ;;
  *) echo "  ATTENZIONE: '$M' e' addestrato solo in inglese."
     echo "  Un dizionario italiano su un modello inglese non funziona: le parole"
     echo "  non corrispondono a nulla e il riconoscimento diventa casuale."
     echo "  Cambia modello in Immich (Amministrazione > Impostazioni > Machine"
     echo "  Learning), rilancia l'indicizzazione, poi torna qui."
     read -r -p "  Proseguire lo stesso? [s/N] " r
     [ "$r" = "s" ] || exit 1 ;;
esac

FOTO=$(docker exec "$DB" psql -U "$UTENTE" -d "$NOME" -A -t -c "SELECT count(*) FROM smart_search;" 2>/dev/null)
[ "${FOTO:-0}" -gt 0 ] || errore "nessuna foto indicizzata: lancia prima 'Smart Search' fra i lavori di Immich"
ok "foto indicizzate: $FOTO"

echo
echo "=== creazione delle tabelle ==="
for f in "$QUI"/sql/01-schema.sql "$QUI"/sql/02-rules-it.sql; do
  docker cp "$f" "$DB:/tmp/$(basename "$f")" >/dev/null
  docker exec "$DB" psql -U "$UTENTE" -d "$NOME" -q -f "/tmp/$(basename "$f")" \
    || errore "fallito $(basename "$f")"
  ok "$(basename "$f")"
done

docker exec "$DB" psql -U "$UTENTE" -d "$NOME" -c \
  "UPDATE curator_config SET valore='$M' WHERE chiave='clip_model';" >/dev/null
ok "modello allineato a quello di Immich"

echo
echo "=== dizionario ==="
python3 "$QUI/script/build-dictionary.py" "${1:-$QUI/dictionaries/it.txt}" || exit 1

echo
echo "=== fatto. Restano tre cose da fare a mano in n8n ==="
cat <<'FINE'
  1. Creare le credenziali:
       - Postgres  "Immich Postgres"  -> host del container del database, porta 5432
       - Header    "Immich API key"   -> nome 'x-api-key', valore: una chiave API
                                         creata dal profilo Immich
       - Telegram  (facoltativa)      -> solo per gli avvisi di errore
  2. Importare i workflow dalla cartella workflow/
  3. Aprire ogni workflow e collegare le credenziali ai nodi, poi attivarlo.

  Se n8n gira in un container separato, va collegato alla rete di Immich:
       docker network connect <rete-di-immich> <container-n8n>
FINE
