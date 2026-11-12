# C7 — Memory & Context Management

## 1. Memory tiers
| Tier | Content | Store | Lifetime |
|------|---------|-------|----------|
| Working (per run) | Tool results, plan, scratch | LangGraph state (+ checkpoint in PG) | Run |
| Short-term (per chat) | Recent messages + rolling summary | Supabase PG (`messages`, `chat_summaries`), Redis prompt cache | Chat lifetime |
| Long-term (per user) | ≤ 20 facts/preferences (e.g., "prefers tables in USD", "works in EMEA finance") | `user_facts` (+ Redis hot copy) | Until user deletes |
| Organisational | Enterprise docs, catalog | RAG, catalog | Managed by admins |

## 2. Context assembly (token budget, prompt-cache friendly)
Order = most static first so provider prompt caching hits:
`[system rules ≈ 800] [tool schemas ≈ 1,200] [user facts ≤ 300] [chat summary ≤ 800] [current time/user locale ≈ 30] [recent messages ≤ 3,000 (last N turns)] [attachments/selected sources list ≈ 150] [tool results/RAG context ≤ 2,500]`.
Budget manager enforces per-section caps and logs the section sizes per run (visible in the insight panel). Overflow policy: trim oldest recent messages first (they remain in summary), then shrink RAG context (top-k), never system/tool sections.

## 3. Compaction (rolling summary)
- Trigger: next prompt would exceed **40% of the model context window** or > 20 messages since last summary.
- Background job (Celery task on the `maintenance` queue, or in-worker async after run) writes `chat_summaries(version+1)` covering messages up to `N − 2`; the newest 2 messages stay verbatim. **No messages are deleted** (UI shows full history).
- Summariser (fast-class LLM) preserves: user goals, decisions, entities (dataset/source names), constraints, open questions, key numbers *with the artifact id they came from*.
- Lock: Redis `lock:compact:{chat}` (120 s TTL) + `chats.summary_version` optimistic check; failure → retry later, never block the turn (fall back to trimming).
- Manual "Compact now" button optional (DocLens-style).

## 4. Long-term facts
- Extraction job: after a chat is idle 24 h (Celery beat sweeper every 5 min claims due chats with a single `UPDATE … RETURNING`; EventBridge in Phase 2) and after compaction; reads only messages beyond `facts_read_to_msg_no`.
- Extractor (fast-class LLM) proposes add/update only; **never deletes** and **never stores** secrets, credentials, personal sensitive data, or enterprise confidential values; PII filter on output.
- Cap 20 facts/user (transactional check). Users view/edit/delete in "Memory" modal; facts are included in prompts as data, labelled "user preferences (untrusted)".
- Facts never grant access; they influence style/defaults only.

## 5. Pre-warming
On chat open / new chat, `POST /chats/{id}/memory/prepare` builds the static prompt prefix (facts + summary + tools) into Redis (`ctx:{chat}:{facts_v}:{last_msg_no}`, 15 min) and warms the LLM provider connection (LiteLLM keep-alive); valid only if `facts_v` and `last_msg_no` unchanged. Saves ~100–300 ms TTFT.

## 6. Conversation state & scaling
Active-turn state in Redis Streams; durable truth in PG. Any worker can serve any chat (stateless). Chat list/history served from Supabase PG (read replicas in Phase 2) with keyset pagination (`msg_no`).

## 7. Privacy & retention
Chats owner-only; admin has no default read access to content (break-glass with audit). Retention configurable (default 365 d for chats; personal docs until deleted). User "delete my data" cascades chats, facts, docs, datasets, artifacts, vectors, S3 objects (async, audited). Traces store redacted inputs (PII scrubber) with short retention (30 d).

## 8. Tests
Budget manager (golden section sizes), compaction idempotence under races, summary fidelity eval (key facts retained), facts cap concurrency, prompt-cache ordering test (static prefix byte-identical across turns).
