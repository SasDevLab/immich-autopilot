#!/usr/bin/env python3
"""Build the n8n workflows from the SQL in this project.

The workflows carry no addresses and no thresholds: the queries read those from
autopilot_config, so a change there takes effect without touching a node. What
cannot travel in a file is credentials, which n8n resolves by internal id -
those are left as placeholders and connected once, by hand, after importing.

Usage:  generate-workflows.py [--chat <telegram chat id>]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT = "SET_YOUR_CHAT_ID"
if "--chat" in sys.argv:
    CHAT = sys.argv[sys.argv.index("--chat") + 1]

PG = {"postgres": {"id": "REPLACE_POSTGRES", "name": "Immich Postgres"}}
API = {"httpHeaderAuth": {"id": "REPLACE_API", "name": "Immich API key"}}
TG = {"telegramApi": {"id": "REPLACE_TELEGRAM", "name": "Telegram"}}


def sql(name):
    return open(os.path.join(HERE, "sql", name), encoding="utf-8").read()


def telegram(name, text, pos):
    return {"parameters": {"chatId": CHAT, "text": text, "additionalFields": {}},
            "id": "tg", "name": name, "type": "n8n-nodes-base.telegram",
            "typeVersion": 1.2, "position": pos, "credentials": TG}


# --- workflow 1: albums by event ---------------------------------------------

CODE_EVENTI = r"""// Decide what kind of event a period was, from what it is made of.
//
// Rules come from the database (autopilot_rules), not from here: they change
// with an UPDATE and no workflow edit. Thresholds arrive with the query, which
// reads them from autopilot_config.
//
// Each rule has three parts:
//   required : lists of words; at least one from EVERY list must be present.
//                Without a church it is not a baptism, however many babies
//                appear. This is the difference between a compatible hint and
//                evidence, and it is what makes the scoring trustworthy.
//   evidence      : words that reinforce, weighted by how widespread they are.
//   against    : words that, when stronger than every piece of evidence,
//                contradict the rule outright.
const MONTHS = ['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio',
                'agosto','settembre','ottobre','novembre','dicembre'];

function asList(x) { return typeof x === 'string' ? JSON.parse(x) : x; }

function decide(c, rules, presence) {
  const out = [];
  for (const r of rules) {
    const need = asList(r.required), evid = asList(r.evidence);
    const against = asList(r.against || []);
    if (!need.every(g => g.some(p => (c[p] || 0) >= presence))) continue;
    const found = evid.filter(p => (c[p] || 0) >= presence);
    if (!found.length) continue;
    const contra = Math.max(0, ...against.map(p => c[p] || 0));
    if (contra > Math.max(...found.map(p => c[p]))) continue;
    // a word present in 4% of photos is a hint, one in 40% is a fact: counting
    // them equally let three weak hints beat two overwhelming ones
    const score = found.reduce((s, p) =>
      s + Math.min(c[p], 0.4) + 0.25 * Math.min(1, c[p] / 0.12), 0);
    out.push({ score, tipo: r.tipo, found });
  }
  out.sort((a, b) => b.score - a.score);
  if (!out.length) return { tipo: null, found: [], margin: 0 };
  const m = out.length === 1 ? out[0].score : out[0].score - out[1].score;
  return { tipo: out[0].tipo, found: out[0].found, margin: m };
}

const result = [];
for (const it of items) {
  const d = it.json;
  const ids = asList(d.ids);
  if (!ids || !ids.length) continue;
  const raw = asList(d.concepts) || {};
  const c = {}; for (const k in raw) c[k] = Number(raw[k]);
  const rules = asList(d.rules) || [];
  const presence = Number(d.presence), margin = Number(d.margin);

  const { tipo, found, margin: got } = decide(c, rules, presence);
  const from = new Date(d.dal), to = new Date(d.al);
  const month = MONTHS[from.getMonth()], year = from.getFullYear();
  let period;
  if (d.dal === d.al) period = from.getDate() + ' ' + month + ' ' + year;
  else if (from.getMonth() === to.getMonth())
    period = from.getDate() + '-' + to.getDate() + ' ' + month + ' ' + year;
  else period = from.getDate() + ' ' + month + ' - ' + to.getDate() + ' ' +
                MONTHS[to.getMonth()] + ' ' + year;

  const where = d.city ? (' a ' + d.city) : '';
  // no name when the evidence is thin: a wrong title is worse than none
  const name = (tipo && got >= margin)
      ? (tipo + where + ', ' + month + ' ' + year)
      : ((d.city ? d.city + ', ' : '') + period);

  result.push({ json: {
    azione: d.album_da_estendere ? 'estendi' : 'crea',
    album_id: d.album_da_estendere || null,
    immich_url: d.immich_url,
    nome: name, ids, dal: d.dal, al: d.al, quante: ids.length,
    riconosciuto: (tipo && got >= margin) ? tipo : null,
    evidence: found.map(p => p + ' ' + Math.round(c[p] * 100) + '%').join(', '),
    distacco: Math.round(got * 100) / 100,
  }});
}
return result;
"""

RACCOGLI = r"""// Carry the album id forward together with the dates, so the run can be recorded.
const out = [];
const before = $('Recognise and name').all();
for (let i = 0; i < items.length; i++) {
  const r = items[i].json;
  const o = before[i] ? before[i].json : {};
  const id = r.id || o.album_id;
  if (!id) continue;
  out.push({ json: { album_id: id, dal: o.dal, al: o.al, nome: o.name,
                     quante: o.quante, riconosciuto: o.riconosciuto, evidence: o.evidence } });
}
return out;"""

REG_ALBUM = ("INSERT INTO autopilot_albums (album_id, dal, al, updated)\n"
             "VALUES ('{{ $json.album_id }}', '{{ $json.dal }}', '{{ $json.al }}', now())\n"
             "ON CONFLICT (album_id) DO UPDATE SET from_date = LEAST(autopilot_albums.from_date, EXCLUDED.dal),\n"
             "  to_date = GREATEST(autopilot_albums.to_date, EXCLUDED.al), updated = now();")

wf_album = {
 "name": "Immich autopilot - albums by event",
 "active": False,
 "nodes": [
  {"parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 5, "triggerAtMinute": 15}]}},
   "id": "e1", "name": "Every night", "type": "n8n-nodes-base.scheduleTrigger",
   "typeVersion": 1.2, "position": [-660, 0]},
  {"parameters": {"operation": "executeQuery", "query": sql("03-events.sql"), "options": {}},
   "id": "e2", "name": "What the periods are made of", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [-440, 0], "credentials": PG, "onError": "continueErrorOutput"},
  {"parameters": {"jsCode": CODE_EVENTI},
   "id": "e3", "name": "Recognise and name", "type": "n8n-nodes-base.code",
   "typeVersion": 2, "position": [-220, 0], "onError": "continueErrorOutput"},
  {"parameters": {"conditions": {"options": {"caseSensitive": True, "version": 2},
                  "conditions": [{"leftValue": "={{ $json.azione }}", "rightValue": "crea",
                                  "operator": {"type": "string", "operation": "equals"}}],
                  "combinator": "and"}},
   "id": "e4", "name": "New album or extend one?", "type": "n8n-nodes-base.if",
   "typeVersion": 2, "position": [0, 0]},
  {"parameters": {"method": "POST", "url": "={{ $json.immich_url }}/api/albums",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ albumName: $json.name, assetIds: $json.ids }) }}",
                  "options": {}},
   "id": "e5", "name": "Create album", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [220, -110], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  {"parameters": {"method": "PUT",
                  "url": "={{ $json.immich_url }}/api/albums/{{ $json.album_id }}/assets",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ ids: $json.ids }) }}", "options": {}},
   "id": "e6", "name": "Extend existing album", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [220, 110], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  {"parameters": {"jsCode": RACCOGLI},
   "id": "e7", "name": "Collect outcome", "type": "n8n-nodes-base.code",
   "typeVersion": 2, "position": [440, 0], "onError": "continueErrorOutput"},
  {"parameters": {"operation": "executeQuery", "query": REG_ALBUM, "options": {}},
   "id": "e8", "name": "Record what was done", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [660, 0], "credentials": PG, "onError": "continueErrorOutput"},
  telegram("Alert ONLY on failure",
           "=[Immich autopilot] albums: failure.\n\n{{ JSON.stringify($json).slice(0,300) }}\n\nNo album was left half-written.",
           [660, 220]),
 ],
 "connections": {
   "Every night": {"main": [[{"node": "What the periods are made of", "type": "main", "index": 0}]]},
   "What the periods are made of": {"main": [[{"node": "Recognise and name", "type": "main", "index": 0}],
                                             [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Recognise and name": {"main": [[{"node": "New album or extend one?", "type": "main", "index": 0}],
                                   [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "New album or extend one?": {"main": [[{"node": "Create album", "type": "main", "index": 0}],
                                         [{"node": "Extend existing album", "type": "main", "index": 0}]]},
   "Create album": {"main": [[{"node": "Collect outcome", "type": "main", "index": 0}],
                             [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Extend existing album": {"main": [[{"node": "Collect outcome", "type": "main", "index": 0}],
                                      [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Collect outcome": {"main": [[{"node": "Record what was done", "type": "main", "index": 0}],
                                [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Record what was done": {"main": [[], [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
 },
 "settings": {"executionOrder": "v1", "saveDataErrorExecution": "all",
              "saveDataSuccessExecution": "all"},
}

# --- workflow 2: person covers ------------------------------------------------
#
# The change has to go through the API. Writing person."faceAssetId" straight
# into the database moves the pointer and leaves the old cropped JPEG on disk:
# the gallery looks exactly as it did, and nothing says why.
#
# One catch worth keeping: if the database already holds the desired value, the
# API sees no change and skips the side effect. Hence the deliberate clear
# before the set.

REG_COVER = ("INSERT INTO autopilot_covers (person_id, face_id, updated)\n"
             "SELECT id, \"faceAssetId\", now() FROM person WHERE id = '{{ $json.person_id }}'\n"
             "ON CONFLICT (person_id) DO UPDATE SET face_id = EXCLUDED.face_id, updated = now();")

wf_cover = {
 "name": "Immich autopilot - person covers",
 "active": False,
 "nodes": [
  {"parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 4, "triggerAtMinute": 45}]}},
   "id": "p1", "name": "Every night", "type": "n8n-nodes-base.scheduleTrigger",
   "typeVersion": 1.2, "position": [-660, 0]},
  {"parameters": {"operation": "executeQuery", "query": sql("04-covers.sql"), "options": {}},
   "id": "p2", "name": "Who needs a better cover", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [-440, 0], "credentials": PG, "onError": "continueErrorOutput"},
  {"parameters": {"method": "PUT",
                  "url": "={{ $json.immich_url }}/api/people/{{ $json.person_id }}",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ featureFaceAssetId: null }) }}",
                  "options": {"batching": {"batch": {"batchSize": 4, "batchInterval": 400}}}},
   "id": "p3", "name": "Clear current cover", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [-220, 0], "credentials": API,
   "onError": "continueErrorOutput"},
  {"parameters": {"method": "PUT",
                  "url": "={{ $('Who needs a better cover').item.json.immich_url }}/api/people/{{ $('Who needs a better cover').item.json.person_id }}",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ featureFaceAssetId: $('Who needs a better cover').item.json.asset_id }) }}",
                  "options": {"batching": {"batch": {"batchSize": 4, "batchInterval": 400}}}},
   "id": "p4", "name": "Set the chosen face", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [0, 0], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  {"parameters": {"jsCode": r"""// Pass the person id on, so the run can be recorded.
const out = [];
const src = $('Who needs a better cover').all();
for (let i = 0; i < items.length; i++) {
  const o = src[i] ? src[i].json : null;
  if (o) out.push({ json: { person_id: o.person_id, nome: o.nome } });
}
return out;"""},
   "id": "p5", "name": "Collect outcome", "type": "n8n-nodes-base.code",
   "typeVersion": 2, "position": [220, 0], "onError": "continueErrorOutput"},
  {"parameters": {"operation": "executeQuery", "query": REG_COVER, "options": {}},
   "id": "p6", "name": "Record what was done", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [440, 0], "credentials": PG, "onError": "continueErrorOutput"},
  telegram("Alert ONLY on failure",
           "=[Immich autopilot] covers: failure.\n\n{{ JSON.stringify($json).slice(0,300) }}\n\nCovers are unchanged.",
           [440, 220]),
 ],
 "connections": {
   "Every night": {"main": [[{"node": "Who needs a better cover", "type": "main", "index": 0}]]},
   "Who needs a better cover": {"main": [[{"node": "Clear current cover", "type": "main", "index": 0}],
                                         [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Clear current cover": {"main": [[{"node": "Set the chosen face", "type": "main", "index": 0}],
                                    [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Set the chosen face": {"main": [[{"node": "Collect outcome", "type": "main", "index": 0}],
                                    [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Collect outcome": {"main": [[{"node": "Record what was done", "type": "main", "index": 0}],
                                [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Record what was done": {"main": [[], [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
 },
 "settings": {"executionOrder": "v1", "saveDataErrorExecution": "all",
              "saveDataSuccessExecution": "all"},
}

# --- workflow 3: file photos into albums that already exist -------------------
#
# Runs before the event job: a photo belonging to an album someone already made
# should not start a new one.
#
# Nothing is recorded afterwards. Album membership is itself the record, and a
# photo removed by hand simply becomes unfiled again - which the next run reads
# as "leave it alone", because its neighbours will now be split.

wf_assign = {
 "name": "Immich autopilot - file into existing albums",
 "active": False,
 "nodes": [
  {"parameters": {"rule": {"interval": [{"field": "days", "triggerAtHour": 5, "triggerAtMinute": 0}]}},
   "id": "a1", "name": "Every night", "type": "n8n-nodes-base.scheduleTrigger",
   "typeVersion": 1.2, "position": [-440, 0]},
  {"parameters": {"operation": "executeQuery", "query": sql("05-assign-to-albums.sql"), "options": {}},
   "id": "a2", "name": "Which photo belongs where", "type": "n8n-nodes-base.postgres",
   "typeVersion": 2.4, "position": [-220, 0], "credentials": PG, "onError": "continueErrorOutput"},
  {"parameters": {"method": "PUT",
                  "url": "={{ $json.immich_url }}/api/albums/{{ $json.album_id }}/assets",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ ids: [$json.asset_id] }) }}",
                  "options": {"batching": {"batch": {"batchSize": 4, "batchInterval": 300}}}},
   "id": "a3", "name": "Add to the album", "type": "n8n-nodes-base.httpRequest",
   "typeVersion": 4.2, "position": [0, 0], "credentials": API,
   "onError": "continueErrorOutput", "retryOnFail": True, "maxTries": 2},
  telegram("Alert ONLY on failure",
           "=[Immich autopilot] filing: failure.\n\n{{ JSON.stringify($json).slice(0,300) }}",
           [0, 200]),
 ],
 "connections": {
   "Every night": {"main": [[{"node": "Which photo belongs where", "type": "main", "index": 0}]]},
   "Which photo belongs where": {"main": [[{"node": "Add to the album", "type": "main", "index": 0}],
                                          [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
   "Add to the album": {"main": [[], [{"node": "Alert ONLY on failure", "type": "main", "index": 0}]]},
 },
 "settings": {"executionOrder": "v1", "saveDataErrorExecution": "all",
              "saveDataSuccessExecution": "all"},
}

os.makedirs(os.path.join(HERE, "workflow"), exist_ok=True)
for name, wf in (("albums-by-event", wf_album), ("person-covers", wf_cover),
                 ("assign-to-albums", wf_assign)):
    dest = os.path.join(HERE, "workflow", "%s.json" % name)
    open(dest, "w", encoding="utf-8").write(json.dumps([wf], indent=2, ensure_ascii=False))
    print("  written: %s  (%d nodes)" % (os.path.basename(dest), len(wf["nodes"])))

print()
print("  After importing in n8n, attach the credentials:")
print("    Postgres  ->  the two 'What ... / Who ...' and 'Record what was done' nodes")
print("    API key   ->  every HTTP node")
print("    Telegram  ->  'Alert ONLY on failure'" +
      ("" if CHAT != "SET_YOUR_CHAT_ID" else "   (and set the chat id)"))
