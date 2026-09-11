# Immich curator

Works out **what kind of event** a group of photos was — a wedding, a christening,
a week by the sea — and creates the album with that name.

Not a themed album ("every beach photo"): the event is recognised from **what it
is made of**. A church, a bride, a tiered cake and people dancing across the same
two days are a wedding.

```
create album "Matrimonio a Giovinazzo, luglio 2021"   827 photos, 2021-07-18 -> 2021-07-21
     evidence: chiesa 12%, ballo 11%, altare 10%, banchetto 10%, torta 9%, anello 8%
     margin over the runner-up: 1.58
```

Every decision carries the evidence it rests on. When the evidence is thin the
period **keeps its date instead of taking a name**: a wrong title is worse than
none.

## Three jobs

**Albums by event** — groups unfiled photos into periods and names them.

**Filing into albums that already exist** — a photo that belongs to an album
someone already made should not start a new one.

**Person covers** — Immich picks whichever face crop scored highest at detection,
which has nothing to do with whether the picture is any good. This picks a face
that is sharp, uncropped, alone in frame, in colour, and recognisably that
person.

## How it works

Immich turns every photo into a vector of 768 numbers. The curator does the same
with a **dictionary of ordinary words** — common terms, not phrases written while
looking at one particular library — and compares.

A photo "contains" a concept when it stands 1.5 standard deviations above that
**word's own average** across the library. The normalisation matters: without it
the words that sit close to everything win every time.

Then time groups photos into periods, and **composition** decides what each was.

### The two rules that earn their place

**Evidence can be necessary.** Without a church it is not a baptism, however many
babies appear. That single constraint corrected four events out of eight while
this was being tuned.

**Abstention.** When first and second hypotheses are close, it does not decide.

### Filing: content says what, dates say which

Assigning a photo to an existing album is not done by distance to the album's
average. An album holding a church, a dance and a cake has its average somewhere
between the three, resembling none of them. Measured on a real library, that
approach put **20%** of photos belonging to no album into one anyway.

Nearest neighbours work better — but not well enough on their own (12%), because
two studio shoots two years apart genuinely are the same pixels.

What fixes it is requiring the neighbours to be close **in time** as well. Same
library, same test: **zero false positives**, 99.9% precision, 88% of photos
filed. Note this is the *neighbours'* dates, not the album's range — albums that
collect photos over years accept anything.

## What you need

- Immich with **pgvector** and photos already indexed (the Smart Search job)
- A **multilingual CLIP model**, unless your dictionary is English:
  `ViT-B-16-SigLIP-i18n-256__webli` or one of the `nllb-clip` family. With the
  default `ViT-B-32__openai` a non-English dictionary does not work at all: the
  words match nothing and recognition becomes random. Changing model means
  **reindexing everything**.
- **n8n**, reachable from Immich's network
- An Immich **API key**

## Install

```sh
./script/install.sh
```

Checks the prerequisites, creates the tables (all prefixed `curator_`, which
Immich ignores), loads the rules and builds the dictionary. Creating the n8n
credentials and importing the workflows is left to you; the script prints what
to do.

## Before letting it run on its own

```sh
./script/preview.py              what it would do tonight, changing nothing
./script/preview.py --all        ignore the "unfiled only" filter: this is how
                                 you tune the rules, by comparing its answers
                                 with albums you filed by hand
./script/preview.py --photo <id> how close one photo sits to every word
```

Preview reads the **same** queries and the **same** rules as the nightly run:
what you see here is what will happen. On a large library it is the difference
between knowing and hoping.

## Tuning

Everything lives in two tables, changed with an `UPDATE`, no workflow edit.

`curator_config` — the knobs:

| key | default | effect |
|---|---|---|
| `word_threshold` | 1.5 | how far a photo must stand out to "contain" a word |
| `min_presence` | 0.04 | below this share, a concept is not evidence |
| `margin` | 0.30 | minimum gap before a name is given |
| `min_photos` | 20 | below this, a period does not become an album |
| `gap_days` | 2 | days of silence that separate two events |
| `max_span_days` | 21 | beyond this it is ordinary life, not an event |
| `assign_days` | 30 | how close in time the neighbours must be |
| `assign_agreement` | 0.8 | what share of neighbours must agree |
| `owner_email` | *(empty)* | which user to work on; empty means all |

`curator_rules` — what makes an event that kind of event. Adding a type means
adding a row, and adding the words it names to the dictionary.

## Dictionaries

`dictionaries/it.txt` is a plain text file. Replace it, or build one from a public
frequency list:

```sh
./script/fetch-dictionary.py --lang it --keep 400
```

That downloads a word list and keeps only the words that **discriminate** — close
to some photos and far from others. A vague word sits at the same distance from
everything, and its spread across the library is nearly zero. It makes the
dictionary fit the library it is installed on.

## Limits, plainly

**The vocabulary is human.** The model compares images and words; it cannot
invent words. It recognises only what somebody described. An unforeseen event is
not misnamed, it is **not recognised**.

**It works on events, not on everyday life.** Someone who photographs daily has
no gaps in the calendar, and periods merge - which is why `max_span_days` exists,
discarding them rather than producing one album spanning years. The right signal
there would be location, and that requires photos to carry it.

**It adds, it never removes.** A photo that stops matching stays where it is.

**Manual choices win.** The curator records what it did; anything changed by hand
afterwards is left alone from then on.

## Credit

The preview mode was borrowed from
[immich-smart-albums](https://github.com/tahnau/immich-smart-albums), the
per-photo diagnosis from
[immich_auto_album](https://github.com/emmertex/immich_auto_album). Both build
themed albums from keywords, and both settle the threshold problem with a fixed
cutoff per keyword, tuned by hand. Here each word is normalised against its own
average instead, once.

## Note

The default dictionary and the event type names are Italian, because the type
names end up in album titles. Everything else — code, comments, configuration —
is English.
