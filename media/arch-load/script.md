# EagleEye video 2: script (approved 2026-11-18)

**Video:** "How EagleEye works, and how it scales." About 6:00 (Part 1 about 3:00, Part 2 about
3:00). 4K, Narrator (`ballad`, 1.25×), no subtitles. Diagram and hacker-movie scenes are animated;
the windows and the admin console are real recordings from the run.

## 0 · Opening (0:00–0:08)
**Screen:** the EagleEye logo fades in slowly on the dark title background; beneath it, typed:
"How it works, and how it scales".
- **Narrator:** "In the first video you saw what EagleEye can do. Here is how it works, and how it holds up when the whole company logs in at once."

## Part 1 · The architecture

## 1 · The big picture (0:08–0:35)
**Screen:** the layers build left to right, each node appearing with its logo: people → Vercel and
Clerk → CloudFront → API, Redis, workers, data gateway → Postgres, Qdrant, S3, the operations database
→ OpenAI, Docling, the Lambda sandbox. The colour legend appears.
- **Narrator:** "EagleEye is a web app in front, a set of services on AWS in the middle, and the company's data underneath. Every request you are about to see travels this map."
- **Narrator:** "The web app runs on Vercel. Sign-in is handled by Clerk. Everything else, the API, the queue, the workers and the data, lives on AWS."

## 2 · Signing in (0:35–0:50)
**Screen:** a violet pulse: Employee → Clerk → back with a token → API (a check mark on the API).
- **Narrator:** "When someone signs in, Clerk checks who they are and issues a short-lived token. Every request to the API carries it, and the API checks it, and the person's role, every time."

## 3 · A document arrives (0:50–1:25)
**Screen:** amber pulses:
- Employee → API → S3 (the file is stored) → Redis (a job is queued) → Ingest worker;
- inside the worker, Docling splits the text, tables and charts; a white pulse to OpenAI's vision model
  for each chart, which comes back as a description;
- embeddings → Qdrant; a tick goes back to the browser ("Ready").
- **Narrator:** "When a document is uploaded, the file goes to secure storage and a job joins the queue, so the upload returns at once."
- **Narrator:** "An ingest worker reads it: the text, the tables, even the charts, which a vision model describes in words. Every passage is turned into a vector and indexed for search."

## 4 · A question (1:25–2:20)
**Screen:** blue pulses Employee → API → Redis → Agent worker. Inside the worker the steps light in
turn:
1. **safety check** (white pulse to OpenAI);
2. **planner** (white pulse);
3. **tools fan out in parallel:**
   - document search → Qdrant;
   - database question → data gateway → operations database (green, a "read-only" badge);
   - notebook → S3 → Lambda sandbox ("no network" badge);
   - chart;
4. **writer** (white pulse);
5. **citations and figure checks;**
6. the answer **streams** back word by word along the blue path to the browser.

Small pulses also go to Postgres (usage recorded) and CloudWatch (logs).
- **Narrator:** "A question takes the same road. The API places it on the queue and an agent worker picks it up."
- **Narrator:** "First a safety check reads it. Then a planner decides what it needs: a document search, a database query, a notebook analysis, or all of them at once."
- **Narrator:** "Database questions go through a gateway that only allows read-only queries, limited to what the person may see. Analysis code runs in an isolated sandbox with no internet access."
- **Narrator:** "Finally the answer is written from the results, every figure is checked against them, and the answer streams back with its citations."

## 5 · Guardrails (2:20–2:40)
**Screen:**
- a red pulse (a malicious prompt) stops at the safety check, with a shield icon;
- a second red pulse (a request for HR data) reaches the data gateway and stops there with a lock icon;
- both leave a small record in Postgres (security events).
- **Narrator:** "A malicious request stops at the safety check. A request for data someone isn't allowed to see stops at the gateway. Both are recorded for the administrators."

## 6 · Scaling (2:40–3:05)
**Screen:** the API, Redis and worker boxes move inside an "ECS Fargate" frame with a load balancer in
front. A user counter climbs, and the boxes multiply to the real counts from the test (API 2 → 4,
agent workers 3 → 11). A CloudWatch gauge shows the queue metric driving it.
- **Narrator:** "For a handful of users, one small server is enough. When the whole company arrives, the same services run on a cluster that grows on its own: the more questions waiting in the queue, the more workers it starts."
- **Narrator:** "Let's put that to the test."

## Part 2 · The load test

## 7 · Mission briefing (3:05–3:20)
**Screen:** cut to black. Green terminal text types out:
```
EAGLEEYE LOAD TEST
TARGET: 1 → 50 → 1,000 → 2,000 CONCURRENT USERS
MIX: 90% DOCUMENT QUESTIONS · 6% DATABASE & CHARTS · 3% ATTACKS · 1% NOTEBOOKS
```
Then the real `terraform apply` and ECS services starting, sped up. A small note: "model simulated
for the load test".
- **Narrator:** "The test: two thousand simulated employees, each signing in and asking real questions. Nine in ten are about documents, some query the database, some try to break the rules, and a few ask for a full analysis."

## 8 · The first users (3:20–3:45)
**Screen:** one window opens: a user signs in and asks a question, and the answer streams. Then 2,
then 4, then 8 windows, each doubling a few seconds apart. The user counter ticks: 1 … 50. The k6
terminal scrolls at the side.
- **Narrator:** "One user. Then fifty."

## 9 · Five hundred: who is here (3:45–4:20)
**Screen:** the wall doubles to 16, 32, 64; the counter races past 500. **Freeze.** Cut to the admin
console (real recording). The camera moves from metric to metric, each marked by a gold outline:
1. **Online now** (Overview): about 500.
2. **Answers in progress** and **Queue: agent** (System & controls).
3. **Request volume and outcomes** (Overview chart), climbing.

An overlay graph shows servers per service starting to rise.
- **Narrator:** "Five hundred people at once. Online now counts everyone active in the last five minutes."
- **Narrator:** "Answers in progress are questions being worked on right now; the queue holds the ones waiting for a free worker. When that queue grows, the cluster adds workers."
- **Narrator:** "Request volume shows every question as it arrives, and how many succeeded."

**Efficiency overlay (after the admin console):** the response-time graph. The line rises as 500 users arrive on a single worker, then drops as workers are added. Callout: "500 users · [1] worker: [peak] s → [n] workers: [settled] s".
- **Narrator:** "Watch the response time. When five hundred people arrive at once, one worker can't keep up and answers slow down. Within a minute the cluster adds workers, and the time falls back."


## 10 · One thousand: still fast? (4:20–4:50)
**Screen:** the wall becomes a dense mosaic of hundreds of tiny windows. Counter: 1,000. Cut to the
admin console, with outlines in turn on:
1. **Average response time** and time to first word.
2. **Success rate** and **failure rate**.
3. **Slowest pipeline steps** (chart).
4. **Caching: hit rate**.

The servers graph overlay is higher.
- **Narrator:** "At a thousand users, the question is speed. Response time measures how long an answer takes, and time to first word how soon it starts appearing."
- **Narrator:** "The success rate stays near one hundred percent. The slowest-steps chart shows where the time goes, and the cache answers repeated questions instantly, taking load off the cluster."

**Efficiency overlay:** the graph continues. Doubling to 1,000 brings a smaller bump that settles faster, because more workers are already running. Callout: "1,000 users: [peak] s → [settled] s".
- **Narrator:** "At a thousand users the bump is smaller and shorter. More workers are already running, and the cluster only has to grow a little."


## 11 · Two thousand: safe, and the right mix (4:50–5:20)
**Screen:** the full mosaic, with a glitch effect. Counter: 2,000. Cut to the admin console at peak,
with outlines in turn on:
1. **Safety events by category** (Quality & safety): injection, jailbreak, data exfiltration, SQL
   injection and more, all blocked.
2. **SQL refused or failed** and **Sandbox runs**.
3. **Request routing distribution** (Overview chart), matching 90 / 6 / 3 / 1.
4. **LLM cost**: $0, with the note "model simulated".
- **Narrator:** "At two thousand, safety. Every attack is logged by type: prompt injection, jailbreaks, attempts to pull out personal data, even SQL slipped into a question. Every one was blocked."
- **Narrator:** "The routing chart confirms the mix: mostly document questions, with database queries, notebooks and the attacks in their expected shares."

**Efficiency overlay:** the full run on one graph, with response time against workers. Two values are marked: the settled time at 2,000 users, and the peak it reached before the cluster caught up. Callout: "2,000 users: [settled] s with [n] workers, against [peak] s before scaling".
- **Narrator:** "Two thousand users, and once the cluster has caught up, answers arrive as fast as they did for fifty. Without scaling, every one of them would be waiting in the queue."


## 12 · Stand down (5:20–5:40)
**Screen:**
- users ramp down; the servers graph falls back as the cluster shrinks;
- a results card with the real figures: peak users, total questions, p95 response time with and without
  scaling, answers per minute per worker, error rate, AWS cost for the test;
- `terraform destroy`.
- **Narrator:** "As the users leave, the cluster scales back down, and the bill stops with it. The whole test cost [cost] in cloud credit."

## 13 · What scaling changed (5:40–6:05)
**Screen:** replaces the "Built with" card. One animated summary of the run, drawn from the real
numbers (`raw/run/timeline.json`), built up in turn on a shared time axis (minutes of the test):
1. **Users** stepping 1 → 50 → 500 → 1,000 → 2,000 and back down.
2. **Servers per service** (agent workers, API) rising after each step and falling at the end.
3. **Response time** (average and p95): the rise after each user step and the drop once workers are
   added, with each drop labelled "before → after" (e.g. "71 s → 11 s").
4. A short row of headline figures: peak users, answers served, success rate, peak servers.

Separate small charts on the same time axis, not one chart with two scales.
- **Narrator:** "Here is the whole test in one picture. Each time more people arrived, answers slowed for a moment; the cluster added workers, and response times came back down. When the users left, the servers went with them."

## 14 · Close (6:05–6:15)
**Screen:** the EagleEye logo and name, then black, as in the product video.
- **Narrator:** "EagleEye. Built to answer with evidence, and built to scale."
