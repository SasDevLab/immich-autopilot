#!/usr/bin/env python3
"""Genera il workflow n8n a partire dalle query SQL di questo progetto.

Il workflow non contiene indirizzi ne' parametri: la query li legge da
curatore_config e il codice li usa. Restano da collegare solo le credenziali,
che in n8n sono riferimenti per nome e non possono stare in un file condiviso.

Uso:  genera-workflow.py [--chat <id telegram>]
"""
import json
import os
import sys

QUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT = "INSERIRE_CHAT_ID"
if "--chat" in sys.argv:
    CHAT = sys.argv[sys.argv.index("--chat") + 1]

SQL = open(os.path.join(QUI, "sql", "03-eventi.sql"), encoding="utf-8").read()

CODE = r"""// Decide che tipo di evento e' un periodo, guardando di cosa e' fatto.
//
// Le regole arrivano dal database (curatore_regole), non da qui: si cambiano
// con un UPDATE senza ritoccare il workflow. Anche le soglie arrivano dalla
// query, che le legge da curatore_config.
//
// Ogni regola ha tre parti:
//   necessarie : liste di parole, di ognuna almeno una deve esserci. Senza una
//                chiesa non e' un battesimo, per quante foto di neonati ci siano.
//   prove      : parole che rafforzano, pesate su quanto sono diffuse.
//   escluse    : parole che, se piu' forti di ogni prova, smentiscono la regola.
const MESI = ['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio',
              'agosto','settembre','ottobre','novembre','dicembre'];

function comeLista(x) { return typeof x === 'string' ? JSON.parse(x) : x; }

function decidi(c, regole, presenza) {
  const esiti = [];
  for (const r of regole) {
    const nec = comeLista(r.necessarie), pro = comeLista(r.prove);
    const esc = comeLista(r.escluse || []);
    if (!nec.every(g => g.some(p => (c[p] || 0) >= presenza))) continue;
    const prove = pro.filter(p => (c[p] || 0) >= presenza);
    if (!prove.length) continue;
    const forzaEscl = Math.max(0, ...esc.map(p => c[p] || 0));
    if (forzaEscl > Math.max(...prove.map(p => c[p]))) continue;
    const punti = prove.reduce((s, p) =>
      s + Math.min(c[p], 0.4) + 0.25 * Math.min(1, c[p] / 0.12), 0);
    esiti.push({ punti, tipo: r.tipo, prove });
  }
  esiti.sort((a, b) => b.punti - a.punti);
  if (!esiti.length) return { tipo: null, prove: [], distacco: 0 };
  const d = esiti.length === 1 ? esiti[0].punti : esiti[0].punti - esiti[1].punti;
  return { tipo: esiti[0].tipo, prove: esiti[0].prove, distacco: d };
}

const fuori = [];
for (const it of items) {
  const d = it.json;
  const ids = comeLista(d.ids);
  if (!ids || !ids.length) continue;
  const c0 = comeLista(d.concetti) || {};
  const c = {}; for (const k in c0) c[k] = Number(c0[k]);
  const regole = comeLista(d.regole) || [];
  const presenza = Number(d.presenza), margine = Number(d.margine);

  const { tipo, prove, distacco } = decidi(c, regole, presenza);
  const dal = new Date(d.dal), al = new Date(d.al);
  const mese = MESI[dal.getMonth()], anno = dal.getFullYear();
  let periodo;
  if (d.dal === d.al) periodo = dal.getDate() + ' ' + mese + ' ' + anno;
  else if (dal.getMonth() === al.getMonth())
    periodo = dal.getDate() + '-' + al.getDate() + ' ' + mese + ' ' + anno;
  else periodo = dal.getDate() + ' ' + mese + ' - ' + al.getDate() + ' ' +
                 MESI[al.getMonth()] + ' ' + anno;

  const luogo = d.citta ? (' a ' + d.citta) : '';
  // niente nome quando le prove non bastano: un titolo sbagliato e' peggio
  const nome = (tipo && distacco >= margine)
      ? (tipo + luogo + ', ' + mese + ' ' + anno)
      : ((d.citta ? d.citta + ', ' : '') + periodo);

  fuori.push({ json: {
    azione: d.album_da_estendere ? 'estendi' : 'crea',
    album_id: d.album_da_estendere || null,
    immich_url: d.immich_url,
    nome, ids, dal: d.dal, al: d.al, quante: ids.length,
    riconosciuto: (tipo && distacco >= margine) ? tipo : null,
    prove: prove.map(p => p + ' ' + Math.round(c[p] * 100) + '%').join(', '),
    distacco: Math.round(distacco * 100) / 100,
  }});
}
return fuori;
"""

RACCOGLI = r"""const fuori = [];
const orig = $('Riconosci e dai un nome').all();
for (let i = 0; i < items.length; i++) {
  const r = items[i].json;
  const o = orig[i] ? orig[i].json : {};
  const id = r.id || o.album_id;
  if (!id) continue;
  fuori.push({ json: { album_id: id, dal: o.dal, al: o.al, nome: o.nome,
                       quante: o.quante, riconosciuto: o.riconosciuto, prove: o.prove } });
}
return fuori;"""

REG = ("INSERT INTO curatore_album (album_id, dal, al, aggiornato)\n"
       "VALUES ('{{ $json.album_id }}', '{{ $json.dal }}', '{{ $json.al }}', now())\n"
       "ON CONFLICT (album_id) DO UPDATE SET dal = LEAST(curatore_album.dal, EXCLUDED.dal),\n"
       "  al = GREATEST(curatore_album.al, EXCLUDED.al), aggiornato = now();")

PG = {"postgres": {"id": "REPLACE_POSTGRES", "name": "Immich Postgres"}}
API = {"httpHeaderAuth": {"id": "REPLACE_API", "name": "Immich API key"}}
TG = {"telegramApi": {"id": "REPLACE_TELEGRAM", "name": "Telegram"}}

wf = {
 "name": "Curatore Immich - album per evento",
 "active": False,
 "nodes": [
  {"parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 5, "triggerAtMinute": 15}]}},
   "id": "c1", "name": "Ogni notte", "type": "n8n-nodes-base.scheduleTrigger",
   "typeVersion": 1.2, "position": [-660, 0]},
  {"parameters": {"operation": "executeQuery", "query": SQL, "options": {}},
   "id": "c2", "name": "Di cosa sono fatti gli eventi", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [-440, 0], "credentials": PG,
   "onError": "continueErrorOutput"},
  {"parameters": {"jsCode": CODE},
   "id": "c3", "name": "Riconosci e dai un nome", "type": "n8n-nodes-base.code",
   "typeVersion": 2, "position": [-220, 0], "onError": "continueErrorOutput"},
  {"parameters": {"conditions": {"options": {"caseSensitive": True, "version": 2},
                  "conditions": [{"leftValue": "={{ $json.azione }}", "rightValue": "crea",
                                  "operator": {"type": "string", "operation": "equals"}}],
                  "combinator": "and"}},
   "id": "c4", "name": "Nuovo o da allungare?", "type": "n8n-nodes-base.if",
   "typeVersion": 2, "position": [0, 0]},
  {"parameters": {"method": "POST", "url": "={{ $json.immich_url }}/api/albums",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ albumName: $json.nome, assetIds: $json.ids }) }}",
                  "options": {}},
   "id": "c5", "name": "Crea album", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [220, -110], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  {"parameters": {"method": "PUT",
                  "url": "={{ $json.immich_url }}/api/albums/{{ $json.album_id }}/assets",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ ids: $json.ids }) }}", "options": {}},
   "id": "c6", "name": "Allunga album esistente", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [220, 110], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  {"parameters": {"jsCode": RACCOGLI},
   "id": "c7", "name": "Raccogli esito", "type": "n8n-nodes-base.code",
   "typeVersion": 2, "position": [440, 0], "onError": "continueErrorOutput"},
  {"parameters": {"operation": "executeQuery", "query": REG, "options": {}},
   "id": "c8", "name": "Annota l album", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [660, 0], "credentials": PG,
   "onError": "continueErrorOutput"},
  {"parameters": {"chatId": CHAT,
                  "text": "=[Curatore Immich] errore.\n\n{{ JSON.stringify($json).slice(0,300) }}\n\nNessun album e' stato lasciato a meta'.",
                  "additionalFields": {}},
   "id": "c9", "name": "Avvisa SOLO se fallisce", "type": "n8n-nodes-base.telegram",
   "typeVersion": 1.2, "position": [660, 220], "credentials": TG},
 ],
 "connections": {
   "Ogni notte": {"main": [[{"node": "Di cosa sono fatti gli eventi", "type": "main", "index": 0}]]},
   "Di cosa sono fatti gli eventi": {"main": [[{"node": "Riconosci e dai un nome", "type": "main", "index": 0}],
                                              [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
   "Riconosci e dai un nome": {"main": [[{"node": "Nuovo o da allungare?", "type": "main", "index": 0}],
                                        [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
   "Nuovo o da allungare?": {"main": [[{"node": "Crea album", "type": "main", "index": 0}],
                                      [{"node": "Allunga album esistente", "type": "main", "index": 0}]]},
   "Crea album": {"main": [[{"node": "Raccogli esito", "type": "main", "index": 0}],
                           [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
   "Allunga album esistente": {"main": [[{"node": "Raccogli esito", "type": "main", "index": 0}],
                                        [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
   "Raccogli esito": {"main": [[{"node": "Annota l album", "type": "main", "index": 0}],
                               [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
   "Annota l album": {"main": [[], [{"node": "Avvisa SOLO se fallisce", "type": "main", "index": 0}]]},
 },
 "settings": {"executionOrder": "v1", "saveDataErrorExecution": "all",
              "saveDataSuccessExecution": "all"},
}

os.makedirs(os.path.join(QUI, "workflow"), exist_ok=True)
dest = os.path.join(QUI, "workflow", "curatore-album-per-evento.json")
open(dest, "w", encoding="utf-8").write(json.dumps([wf], indent=2, ensure_ascii=False))
print("  scritto:", dest)
print("  nodi:", len(wf["nodes"]))
print()
print("  Dopo l'importazione in n8n, collegare le credenziali ai nodi:")
print("    Postgres  ->  'Di cosa sono fatti gli eventi', 'Annota l album'")
print("    API key   ->  'Crea album', 'Allunga album esistente'")
print("    Telegram  ->  'Avvisa SOLO se fallisce'" +
      ("  (chat id gia' impostato)" if CHAT != "INSERIRE_CHAT_ID" else "  (e impostare il chat id)"))
