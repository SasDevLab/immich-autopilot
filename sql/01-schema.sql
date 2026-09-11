-- Curatore per Immich - tabelle di supporto
--
-- Vivono nello stesso database di Immich ma con un prefisso proprio, e Immich
-- le ignora: non tocca tabelle che non conosce. Restano intatte attraverso gli
-- aggiornamenti, e si rimuovono con un DROP se si cambia idea.

-- Parametri regolabili --------------------------------------------------------
CREATE TABLE IF NOT EXISTS curatore_config (
  chiave     text PRIMARY KEY,
  valore     text NOT NULL,
  descrizione text
);

INSERT INTO curatore_config (chiave, valore, descrizione) VALUES
 ('proprietario', '',
  'Email dell utente Immich da gestire. Vuoto = tutti gli utenti. Attenzione: la chiave API appartiene a un utente solo, e scrivere sulle persone di un altro fallisce.'),
 ('fuso_orario', 'Europe/Rome',
  'Con quale fuso si stabilisce a che giorno appartiene una foto.'),
 ('soglia_scena', '1.5',
  'Di quante deviazioni standard una foto deve staccarsi dalla media di una parola per "contenerla". Piu alto = meno concetti per foto, piu selettivo.'),
 ('presenza_minima', '0.04',
  'Sotto questa quota di foto dell evento, un concetto non conta come prova.'),
 ('margine', '0.30',
  'Distacco minimo fra prima e seconda ipotesi per dare un nome. Sotto, l evento tiene solo la data: un titolo sbagliato e peggio di nessun titolo.'),
 ('foto_minime', '20',      'Sotto questo numero di foto un periodo non diventa album.'),
 ('vuoto_giorni', '2',      'Giorni senza foto che separano due eventi.'),
 ('durata_massima', '21',
  'Oltre questi giorni non e un evento ma vita quotidiana: si ignora. Senza questo limite, su un archivio fitto uscirebbe un unico album lungo anni.'),
 ('modello_clip', 'ViT-B-16-SigLIP-i18n-256__webli',
  'Deve coincidere con il modello impostato in Immich, altrimenti i vettori non sono confrontabili.'),
 ('immich_url', 'http://immich_server:2283',
  'Come n8n raggiunge Immich. Il workflow lo legge da qui, cosi non restano indirizzi scritti dentro i nodi.')
ON CONFLICT (chiave) DO NOTHING;

-- Dizionario: una parola, il suo vettore ---------------------------------------
CREATE TABLE IF NOT EXISTS curatore_dizionario (
  parola  text PRIMARY KEY,
  vettore vector(768) NOT NULL,
  modello text NOT NULL,
  creato  timestamptz NOT NULL DEFAULT now()
);

-- Regole: che cosa rende un evento quel tipo di evento -------------------------
CREATE TABLE IF NOT EXISTS curatore_regole (
  tipo       text PRIMARY KEY,
  necessarie jsonb NOT NULL,  -- liste di parole: di ogni lista almeno una deve esserci
  prove      jsonb NOT NULL,  -- parole che rafforzano, pesate su quanto sono diffuse
  escluse    jsonb NOT NULL DEFAULT '[]'::jsonb,  -- se piu forti di ogni prova, smentiscono
  attiva     boolean NOT NULL DEFAULT true
);

-- Memoria: cosa ha fatto il curatore, per non rifarlo e per rispettare
-- le modifiche manuali dell utente
CREATE TABLE IF NOT EXISTS curatore_album (
  album_id   uuid PRIMARY KEY,
  dal        date NOT NULL,
  al         date NOT NULL,
  aggiornato timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS curatore_copertine (
  person_id  uuid PRIMARY KEY,
  face_id    uuid NOT NULL,
  aggiornato timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS curatore_colore (
  asset_id      uuid PRIMARY KEY,
  scarto        numeric NOT NULL,
  bianco_e_nero boolean NOT NULL,
  calcolato     timestamptz NOT NULL DEFAULT now()
);
