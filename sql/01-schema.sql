-- Immich autopilot - supporting tables
--
-- These live in Immich's own database under their own prefix. Immich ignores
-- tables it does not know about, so they survive upgrades untouched, and a DROP
-- removes every trace if you change your mind.

-- Settings --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS autopilot_config (
  key         text PRIMARY KEY,
  value       text NOT NULL,
  description text
);

INSERT INTO autopilot_config (key, value, description) VALUES
 ('owner_email', '',
  'Immich user to work on. Empty means every user. Careful: an API key belongs to one user, and writing to another user''s people fails with 403.'),
 ('timezone', 'Europe/Rome',
  'Which timezone decides what day a photo belongs to.'),
 ('word_threshold', '1.5',
  'How many standard deviations a photo must stand above a word''s own average to "contain" it. Higher means fewer concepts per photo.'),
 ('min_presence', '0.04',
  'Below this share of an event''s photos, a concept is not evidence.'),
 ('margin', '0.30',
  'Minimum gap between first and second hypothesis before a name is given. Below it the event keeps its date: a wrong title is worse than none.'),
 ('min_photos', '20',
  'A period with fewer photos than this does not become an album.'),
 ('gap_days', '2',
  'Days without photos that separate one event from the next.'),
 ('max_span_days', '21',
  'Beyond this, a run is not an event but ordinary life, and is skipped. Without the cap, a dense library yields one album spanning years.'),
 ('clip_model', 'ViT-B-16-SigLIP-i18n-256__webli',
  'Must match the model set in Immich. Vectors from different models are not comparable.'),
 ('immich_url', 'http://immich_server:2283',
  'How n8n reaches Immich. The queries pass it through, so no address is written inside a node.'),
 ('cover_max_distance', '0.05',
  'How far a face may sit from that person''s average face and still be a cover candidate.'),
 ('cover_min_area', '0.45',
  'How much smaller a face may be than that person''s largest. Below it, the crop is too coarse.'),
 -- Filing an unfiled photo into an album that already exists. Measured on a
 -- real library, these four together gave zero false positives and 99.9%
 -- precision; without assign_days it was 12% wrong.
 ('assign_neighbours', '10',
  'How many already-filed photos to look at. Nearest neighbours, not distance to the album average: an album holding several kinds of scene has its average between them, resembling none.'),
 ('assign_similarity', '0.85',
  'How close the nearest neighbour must be before the question is even asked.'),
 ('assign_agreement', '0.8',
  'What share of those neighbours must agree on the same album.'),
 ('assign_days', '30',
  'The neighbours must also be this close in time. Content says what a photo is and cannot say which: two studio shoots two years apart are the same pixels. Note this is the NEIGHBOURS'' dates, not the album''s range - albums that collect photos over years accept anything.')
ON CONFLICT (key) DO NOTHING;

-- Dictionary: a word and its vector ---------------------------------------------
CREATE TABLE IF NOT EXISTS autopilot_dictionary (
  word    text PRIMARY KEY,
  vector  vector(768) NOT NULL,
  model   text NOT NULL,
  created timestamptz NOT NULL DEFAULT now()
);

-- Rules: what makes an event that kind of event ---------------------------------
CREATE TABLE IF NOT EXISTS autopilot_rules (
  type     text PRIMARY KEY,
  -- lists of words; at least one from every list must be present
  required jsonb NOT NULL,
  -- words that reinforce, weighted by how widespread they are
  evidence jsonb NOT NULL,
  -- words that, when stronger than every piece of evidence, contradict the rule
  against  jsonb NOT NULL DEFAULT '[]'::jsonb,
  active   boolean NOT NULL DEFAULT true
);

-- Memory: what the autopilot did.
-- Two purposes: not redoing settled work, and leaving alone anything a person
-- has since changed by hand. A manual choice wins for good.
CREATE TABLE IF NOT EXISTS autopilot_albums (
  album_id  uuid PRIMARY KEY,
  from_date date NOT NULL,
  to_date   date NOT NULL,
  updated   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS autopilot_covers (
  person_id uuid PRIMARY KEY,
  face_id   uuid NOT NULL,
  updated   timestamptz NOT NULL DEFAULT now()
);

-- Whether a photo is monochrome. Neither EXIF nor semantic search can tell:
-- a black and white JPEG still records itself as sRGB, and asking the model for
-- "black and white" returns colour photos among the top hits. Only the pixels
-- say so, which is why this is measured once and stored.
CREATE TABLE IF NOT EXISTS autopilot_colour (
  asset_id   uuid PRIMARY KEY,
  spread     numeric NOT NULL,
  monochrome boolean NOT NULL,
  measured   timestamptz NOT NULL DEFAULT now()
);
