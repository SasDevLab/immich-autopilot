# Curatore per Immich

Riconosce **che tipo di evento** è un gruppo di foto — un matrimonio, un
battesimo, una vacanza al mare — e crea l'album con il nome giusto.

Non è un album tematico ("tutte le foto di mare"): è il riconoscimento
dell'evento a partire da **ciò di cui è fatto**. Una chiesa, una sposa, una
torta a piani e gente che balla negli stessi due giorni sono un matrimonio.

```
crea album "Matrimonio a Giovinazzo, luglio 2021"    827 foto, 2021-07-18 -> 2021-07-21
     prove: chiesa 12%, ballo 11%, altare 10%, banchetto 10%, torta 9%, anello 8%
     distacco dalla seconda ipotesi: 1.58
```

Ogni decisione porta con sé le prove su cui si fonda. Quando le prove non
bastano, l'evento **tiene la data invece di prendere un nome**: un titolo
sbagliato è peggio di nessun titolo.

## Come funziona

Immich trasforma ogni foto in un vettore di 768 numeri. Il curatore fa la stessa
cosa con un **dizionario di parole comuni** — 175 termini ordinari, non frasi
scritte guardando un archivio particolare — e confronta.

Una foto "contiene" un concetto quando si stacca di 1,5 deviazioni standard
dalla media di **quella parola** su tutto l'archivio. La normalizzazione conta:
senza, le parole vicine un po' a tutto vincerebbero sempre.

Poi il tempo raggruppa le foto in periodi, e la **composizione** decide.

### Le due regole che fanno la differenza

**Prove necessarie.** Senza una chiesa non è un battesimo, per quante foto di
neonati ci siano. È la differenza fra indizio compatibile e prova. Questo solo
vincolo ha corretto quattro eventi su otto durante la messa a punto.

**Astensione.** Se la prima e la seconda ipotesi sono vicine, non decide.

## Cosa serve

- Immich con **pgvector** e le foto già indicizzate (lavoro «Smart Search»)
- Un **modello CLIP multilingua**, se il dizionario non è in inglese:
  `ViT-B-16-SigLIP-i18n-256__webli` o uno della famiglia `nllb-clip`.
  Con il modello predefinito `ViT-B-32__openai` un dizionario italiano non
  funziona: le parole non corrispondono a nulla e il riconoscimento è casuale.
  Cambiare modello impone di **reindicizzare tutto**.
- **n8n** per l'esecuzione periodica, raggiungibile dalla rete di Immich
- Una **chiave API** di Immich

## Installazione

```sh
./script/installa.sh
```

Verifica i prerequisiti, crea le tabelle (tutte con prefisso `curatore_`, Immich
le ignora), carica le regole e calcola il dizionario. Poi restano da creare le
credenziali in n8n e importare i workflow: lo script lo spiega alla fine.

## Prima di lasciarlo andare da solo

```sh
./script/prova.py            # cosa farebbe stanotte, senza fare nulla
./script/prova.py --tutte    # ignora il filtro sugli album: serve a tarare le
                             # regole confrontandole con gli album fatti a mano
./script/prova.py --foto <id>   # quanto una foto è vicina a ogni parola
```

La modalità prova legge le **stesse** query e le **stesse** regole del lavoro
notturno: quello che si vede qui è quello che accadrà. Su un archivio grande è
il modo per non scoprire dopo diecimila foto che il criterio era sbagliato.

## Regolazione

Tutto sta in due tabelle, modificabili con un `UPDATE` senza toccare i workflow.

`curatore_config` — le manopole:

| chiave | predefinito | effetto |
|---|---|---|
| `soglia_scena` | 1.5 | quanto una foto deve staccarsi per "contenere" una parola |
| `presenza_minima` | 0.04 | sotto questa quota un concetto non è una prova |
| `margine` | 0.30 | distacco minimo per dare un nome |
| `foto_minime` | 20 | sotto, un periodo non diventa album |
| `vuoto_giorni` | 2 | giorni di vuoto che separano due eventi |
| `durata_massima` | 21 | oltre, non è un evento ma vita quotidiana |
| `proprietario` | *(vuoto)* | email dell'utente da gestire; vuoto = tutti |

`curatore_regole` — cosa rende un evento quel tipo di evento. Aggiungere un tipo
significa aggiungere una riga e, se servono, le parole nel dizionario.

## Limiti, detti chiaramente

**Il vocabolario è umano.** Il modello sa confrontare immagini e parole, non
inventare parole: riconosce solo ciò che qualcuno ha descritto. Un evento non
previsto non viene sbagliato, viene **non riconosciuto**.

**Funziona sugli eventi, non sulla vita quotidiana.** Chi fotografa ogni giorno
non ha vuoti nel calendario, e i periodi si fondono: per questo esiste
`durata_massima`, che li scarta invece di produrre un album lungo anni. Il
segnale giusto in quel caso sarebbe la posizione (lontano da casa = viaggio),
e serve che le foto ce l'abbiano.

**Aggiunge, non toglie.** Se una foto smette di corrispondere, resta dov'è.

**Le scelte manuali vincono.** Il curatore annota cosa ha fatto: se un album è
stato modificato a mano, lo lascia stare da lì in avanti.

## Ringraziamenti

L'idea della modalità prova viene da
[immich-smart-albums](https://github.com/tahnau/immich-smart-albums); quella
della diagnosi per singola foto da
[immich_auto_album](https://github.com/emmertex/immich_auto_album). Entrambi
fanno album tematici a partire da parole chiave, ed entrambi risolvono il
problema delle soglie con soglie fisse per parola: qui si è preferito
normalizzare ogni parola sulla propria media, una volta sola.

## Nota

I commenti nel codice sono in italiano, come il dizionario predefinito. Il
dizionario è sostituibile: è un file di testo.
