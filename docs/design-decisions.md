# Design Decisions

Key architectural trade-offs and rationale behind the NovaCart Global Agentic RAG system.

---

## 1. LangGraph for Orchestration
**Decision:** Using LangGraph to define the multi-hop reasoning pipeline as a stateful, directed graph with conditional edges.

**Why:** The core requirement — a cyclic retrieve → evaluate → re-retrieve loop — is fundamentally a graph problem. LangGraph provides first-class cycle support via `add_conditional_edges`, typed shared state (`AgentState` TypedDict), and `astream_events(v2)` which emits fine-grained token/node events that map directly onto our SSE streaming needs. Vanilla LangChain chains only support linear pipelines, and multi-agent frameworks (CrewAI, AutoGen) add inter-agent overhead unjustified for a single-agent system with distinct processing stages.

## 2. Dynamic Model Discovery & Fallback
**Decision:** Query the Gemini API at startup to discover available models, build a prioritised fallback order, and cycle through models on retryable errors (429/404/500).

**Why:** Free-tier API keys have aggressive per-model rate limits (2–5 RPM). A single-model approach fails frequently. Discovery (`client.models.list()`) adapts automatically as Google adds/deprecates models. The system distinguishes rate-limits (429 — may recover) from unavailability (404 — skip permanently). `MAX_RETRY_ROUNDS=1` ensures fail-fast behaviour over hanging. With 8+ fallback models, trying the next model is almost always faster than waiting 30–60s for rate-limit recovery.

## 3. DLP: Regex over SLM
**Decision:** PII redaction uses regex (`dlp_filter_node`) positioned after retrieval but before any LLM calls, ensuring raw PII never reaches the Gemini API.

**Why regex:** Deterministic, zero-latency, zero-cost, and auditable. The pattern `\b(?:\d[ -]*?){13,16}\b` always redacts credit card sequences regardless of context — critical for a security-sensitive operation. An SLM/NER alternative would add 1–5s latency per chunk and consume API quota.

**Known gap:** Regex cannot catch contextual PII ("my card is four one one one…") or scale across diverse PII types (SSN, global phone numbers). The production path is a hybrid: regex first as a fast filter, then a small NER model (Presidio/spaCy) on flagged documents only.

## 4. SSE over WebSockets
**Decision:** Stream output via Server-Sent Events over HTTP POST, not WebSockets.

**Why:** The interaction is strictly unidirectional after the initial request — client sends a question, server streams back events. SSE maps perfectly to this: `text/event-stream` with `data:` JSON payloads, auto-reconnection built into client libraries, works over standard HTTP/1.1 with no upgrade handshake, and debuggable with `curl`. WebSockets would only be warranted for bidirectional mid-stream communication (e.g., user cancelling a hop or injecting context), which this design does not require.

## 5. ChromaDB as Vector Store
**Decision:** Use ChromaDB in persistent mode with `gemini-embedding-2` embeddings (falling back to `all-MiniLM-L6-v2` if no API key).

**Why:** Zero infrastructure — runs in-process with no external server, unlike Pinecone (account required) or Weaviate (Docker required). `PersistentClient` writes to `data/chroma_db/` so ingestion runs once and survives restarts. The embedding wrapper implements ChromaDB's `EmbeddingFunction` interface, enabling seamless online/offline switching. Scale ceiling: single-process, no concurrent writes — production would need a managed vector DB.

## 6. Heterogeneous Data Formats
**Decision:** Store documents in two formats — JSON (structured records) and Markdown with YAML frontmatter (unstructured text) — unified at ingestion into a single ChromaDB collection.

**Why:** Real enterprise data spans structured systems (order DBs exporting JSON) and unstructured channels (support tickets, emails as prose). Using both formats forces the system to handle format heterogeneity from the start, mirroring the real challenge of reasoning across `{"amount": 299.99}` and `"My NovaWatch won't charge"`.

## 7. Intentional Data Anomalies
**Decision:** Embed deliberate anomalies in the synthetic dataset as a built-in evaluation mechanism.

**Anomalies:** Duplicate records with typos (ticket 001 vs 002), missing foreign keys (refund with no order_id), conflicting internal data (procurement praises supplier that quality flags), chronological impossibility (refund predates purchase), phantom document reference ("Q3 Post-Mortem.pdf" doesn't exist), date format mismatch (DD/MM vs ISO 8601), and embedded PII (credit card number for DLP testing). A well-functioning agent should surface these in its synthesis without being explicitly asked.

## 8. Bounded Multi-Hop Reasoning
**Decision:** Cap at 3 hops with the planner generating at most 2 search queries.

**Why:** Unbounded loops in LLM systems are dangerous — a model that "always wants more evidence" loops indefinitely. The worst-case path is: Plan → (Retrieve → DLP → Judge) × 3 → Synthesise = 5 LLM calls, keeping latency and token cost controlled on free-tier APIs.

## 9. Selective Token Streaming
**Decision:** Stream only synthesis node tokens to the client; suppress planner/judge token events.

**Why:** Planner and judge nodes produce internal structured JSON (search plans, evaluations) that would confuse users if streamed as raw text. The SSE generator filters by `metadata.langgraph_node == "synthesize_and_cite"`, emitting status events for progress visibility, token events only during answer generation, and a structured complete event with citations and anomalies at the end.
