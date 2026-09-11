-- Italian rule pack: what makes an event that kind of event.
--
-- The words are Italian because they must match the Italian dictionary, and the
-- type names are Italian because they end up in album titles. Everything else
-- in this project is English.
--
-- Each rule has three parts:
--   required : lists of words; at least one from EVERY list must be present.
--              This is the difference between a compatible hint and evidence.
--              Without a church it is not a baptism, however many babies
--              appear - and that single constraint corrected four events out of
--              eight while this was being tuned.
--   evidence : words that reinforce, weighted by how widespread they are.
--   against  : words that, when stronger than every piece of evidence,
--              contradict the rule outright.
--
-- Change them with an UPDATE; no workflow edit is needed. Adding an event type
-- means adding a row here, and adding the words it names to the dictionary.

INSERT INTO autopilot_rules (type, required, evidence, against) VALUES

('Matrimonio',
 '[["sposa","sposo","bouquet","anello"],["chiesa","altare","cerimonia","banchetto"]]',
 '["chiesa","altare","cerimonia","sposa","sposo","anello","bouquet","torta","ballo","brindisi","banchetto","abito"]',
 '["battesimo","gravidanza"]'),

('Battesimo',
 '[["battesimo"]]',
 '["battesimo","neonato","bambino","chiesa","altare","prete","cerimonia","culla"]',
 '["gravidanza","sposa"]'),

('Nascita',
 '[["neonato"]]',
 '["neonato","culla","fasciatoio","peluche","scarpine","genitori","fratello"]',
 '["battesimo","gravidanza","chiesa"]'),

('Servizio di gravidanza',
 '[["gravidanza","pancione"]]',
 '["gravidanza","pancione","genitori","famiglia","campagna"]',
 '["battesimo","chiesa"]'),

('Vacanza al mare',
 '[["spiaggia","mare"]]',
 '["spiaggia","mare","onde","sabbia","ombrellone","barca","piscina","scogli","tramonto"]',
 '["chiesa","neve"]'),

('Vacanza in montagna',
 '[["montagna","neve"]]',
 '["montagna","neve","sci","bosco"]',
 '["spiaggia"]'),

('Compleanno',
 '[["compleanno","candeline"]]',
 '["compleanno","candeline","torta","regalo","palloncini","festa"]',
 '["sposa","battesimo","gravidanza"]'),

('Natale',
 '[["natale","presepe"]]',
 '["natale","presepe","albero","regalo","tavola","banchetto"]',
 '["battesimo","sposa","spiaggia"]'),

('Gita in citta',
 '[["monumento","museo","castello","piazza"]]',
 '["monumento","museo","castello","piazza","palazzo","ponte","viaggio"]',
 '["chiesa","neonato"]'),

('Laurea',
 '[["laurea","diploma"]]',
 '["laurea","diploma","scuola","classe","festa","brindisi"]',
 '["sposa","battesimo"]'),

('Concerto',
 '[["concerto","palco"]]',
 '["concerto","palco","musica","chitarra","luci","folla"]',
 '["chiesa","neonato"]'),

('Giornata di sport',
 '[["gara","calcio","squadra"]]',
 '["gara","calcio","squadra","pallone","corsa","medaglia","palestra"]',
 '["chiesa","sposa","neonato"]')

ON CONFLICT (type) DO NOTHING;
