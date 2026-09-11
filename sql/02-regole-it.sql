-- Regole predefinite: cosa rende un evento quel tipo di evento.
--
-- Struttura di ogni regola:
--   necessarie : liste di parole; di OGNI lista almeno una deve essere presente.
--                E la differenza fra indizio compatibile e prova: senza una
--                chiesa non e un battesimo, per quante foto di neonati ci siano.
--   prove      : parole che rafforzano, pesate su quanto sono diffuse.
--   escluse    : parole che, se piu forti di ogni prova, smentiscono la regola.
--
-- Si modificano con un UPDATE, senza toccare i workflow. Aggiungere un tipo di
-- evento significa aggiungere una riga qui e le parole nel dizionario.

INSERT INTO curatore_regole (tipo, necessarie, prove, escluse) VALUES

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

ON CONFLICT (tipo) DO NOTHING;
