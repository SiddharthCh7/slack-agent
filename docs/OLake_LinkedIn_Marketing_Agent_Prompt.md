## 1. Project Setup & Tooling

### 1.1 Tech Stack
| Layer | Tool / Library | Purpose |
|---|---|---|
| Project & dependency management | **uv** | `uv init`, `uv add`, virtual-env, lock files |
| Agent orchestration | **LangGraph** (`langgraph`) | Stateful, multi-node graph workflow |
| LLM backbone | **OpenAI** (`openai`) or **Anthropic** (`anthropic`) | Comment generation, relevance scoring |
| LinkedIn access | **LinkedIn API** (OAuth 2.0 — Marketing Developer Platform or unofficial scrape-free approach) | Feed scanning, post commenting |
| Config & secrets | `python-dotenv` | `.env` for API keys |
| Logging | `loguru` | Structured, levelled logs |

### 1.2 Project Scaffolding (run once)
```bash
uv init olake-linkedin-agent
cd olake-linkedin-agent

uv add langgraph openai linkedin-api python-dotenv loguru requests
# or swap `openai` → `anthropic` if using Claude as the backbone
```

### 1.3 `.env` Template
```env
# LLM
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=

# LinkedIn OAuth (Marketing Developer Platform app)
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_ACCESS_TOKEN=...     # obtained via OAuth flow or refreshed on startup

# Agent Tuning
MAX_POSTS_PER_RUN=10           # how many posts to evaluate per cycle
COMMENT_COOLDOWN_MINUTES=30    # minimum gap between two comments (rate-limit safety)
RELEVANCE_THRESHOLD=0.7        # LLM-scored relevance below this → skip
```

---

## 2. Agent Architecture — LangGraph Workflow

Design the agent as an **explicit, stateful graph** with clearly separated nodes. Each node has one responsibility; edges carry the shared state forward.

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌────────────────┐     ┌─────────────┐
│  Feed       │────▶│  Relevance   │────▶│  Comment       │────▶│  Post          │────▶│  Log &      │
│  Scanner    │     │  Filter      │     │  Drafter       │     │  Comment       │     │  Cooldown   │
└─────────────┘     └──────────────┘     └────────────────┘     └────────────────┘     └─────────────┘
                                                                       │
                                                                       ▼
                                                              ┌────────────────┐
                                                              │  Fallback /    │
                                                              │  Retry Handler │
                                                              └────────────────┘
```

### 3.1 Node-by-Node Specification

#### Node 1 — `feed_scanner`
**Input:** LinkedIn API credentials, keyword list (see §4), time window  
**Action:**
- Call the LinkedIn API (or an approved partner endpoint) to surface recent posts matching target keywords / hashtags.
- Deduplicate by post URN.
- Respect LinkedIn's rate limits (max 100 requests / min per OAuth token).

**Output:** `List[Post]` — raw post objects with `urn`, `text`, `author`, `timestamp`.

---

#### Node 2 — `relevance_filter`
**Input:** `List[Post]` from the scanner  
**Action:**
- Send each post's text to the LLM with a classification prompt:

```
You are an expert relevance classifier for OLake, an open-source EL tool that replicates databases to Apache Iceberg.

Classify the following LinkedIn post. Return a JSON object:
{
  "relevance_score": <float 0.0–1.0>,
  "primary_topic": "<one of: apache_iceberg, data_lakehouse, cdc, etl_elt, data_replication, data_engineering_general, off_topic>",
  "reason": "<one sentence>"
}

Post text:
\"\"\"
{post_text}
\"\"\"
```

- Filter: keep only posts where `relevance_score >= RELEVANCE_THRESHOLD`.
- Sort descending by score.

**Output:** `List[ScoredPost]`

---

#### Node 3 — `comment_drafter`
**Input:** A single `ScoredPost` + its `primary_topic`  
**Action:**
- Choose a **tone template** based on the topic (see §5 — Tone & Messaging Strategy).
- Send the post text + chosen template to the LLM:

```
You are writing a LinkedIn comment on behalf of OLake (olake.io) — an open-source EL tool for replicating databases to Apache Iceberg.

Guidelines:
- Be genuine, warm, and knowledgeable. You are a fellow data engineer, not a marketer.
- Acknowledge or praise the specific insight in the post.
- If natural, weave in a brief, relevant mention of OLake. Never make it the only point of the comment.
- Keep it under 3 sentences (max ~60 words).
- Do NOT use emojis unless the original post used them.
- Do NOT use phrases like "Great post!", "This is so informative!", or any other hollow filler.
- Do NOT include any URLs unless the tone template explicitly calls for one (and then only olake.io or the GitHub repo).

Tone guidance for this post's topic: {tone_template}

Original post:
\"\"\"
{post_text}
\"\"\"

Write the comment:
```

- If the LLM output contains disallowed phrases or exceeds the word limit, loop once with a correction prompt before falling back to a safe default.

**Output:** `DraftedComment` — `{ post_urn, comment_text, topic, confidence }`

---

#### Node 4 — `post_comment`
**Input:** `DraftedComment`  
**Action:**
- Call the LinkedIn API endpoint to POST the comment on the target post URN.
- Handle HTTP 429 (rate limit) with exponential back-off (max 3 retries).
- Handle 401 (token expired) → trigger token refresh → retry once.

**Output:** `CommentResult` — `{ success: bool, linkedin_comment_id, error? }`

---

#### Node 5 — `log_and_cooldown`
**Input:** `CommentResult`  
**Action:**
- Append a structured log entry (timestamp, post URN, topic, comment text, success/fail, LinkedIn comment ID).
- Persist to a local SQLite DB or JSON file for deduplication and history tracking.
- Enforce `COMMENT_COOLDOWN_MINUTES` before allowing the next comment in the same run.

**Output:** `{ next_allowed_at: datetime }`

---

#### Node 6 — `fallback_handler` (conditional edge from `post_comment`)
**Triggers on:** API failure after retries, or LLM returning an unusable draft.  
**Action:**
- Log the failure with full context.
- Optionally, queue the post URN for a future retry run.
- Continue to the next post in the batch without crashing the graph.

---

### 3.2 Graph Edges & Loop Logic
```python
graph = StateGraph(AgentState)

graph.add_node("feed_scanner", feed_scanner)
graph.add_node("relevance_filter", relevance_filter)
graph.add_node("comment_drafter", comment_drafter)
graph.add_node("post_comment", post_comment)
graph.add_node("log_and_cooldown", log_and_cooldown)
graph.add_node("fallback_handler", fallback_handler)

graph.set_entry_point("feed_scanner")

graph.add_edge("feed_scanner", "relevance_filter")
graph.add_edge("relevance_filter", "comment_drafter")   # loops over filtered posts
graph.add_edge("comment_drafter", "post_comment")

# Conditional: success → log; failure → fallback → log
graph.add_conditional_edges(
    "post_comment",
    route_post_result,          # returns "log_and_cooldown" or "fallback_handler"
    { "log_and_cooldown": "log_and_cooldown", "fallback_handler": "fallback_handler" }
)
graph.add_edge("fallback_handler", "log_and_cooldown")
graph.add_edge("log_and_cooldown", END)                 # or loop back to comment_drafter if posts remain

app = graph.compile()
```

---

## 4. Target Keywords & Hashtags

The scanner should search for posts containing **any combination** of these terms. Group them by priority.

### Tier 1 — High Intent (always engage)
`Apache Iceberg`, `Iceberg table format`, `data lakehouse`, `Iceberg CDC`, `database replication Iceberg`, `EL pipeline`, `Iceberg ingestion`

### Tier 2 — Strong Signal (engage if post is substantive)
`Change Data Capture`, `CDC pipeline`, `data replication`, `Debezium alternatives`, `ETL vs ELT`, `open table format`, `Parquet lakehouse`, `Iceberg vs Delta Lake`, `Hive to Iceberg migration`

### Tier 3 — Contextual (engage only if Iceberg / lakehouse is mentioned in the body)
`data engineering`, `data lake modernization`, `real-time analytics`, `streaming ingestion`, `PostgreSQL replication`, `MySQL CDC`, `MongoDB change streams`, `Trino`, `Apache Spark data lake`

### Hashtags to monitor
`#ApacheIceberg`, `#DataLakehouse`, `#DataEngineering`, `#CDC`, `#DataReplication`, `#OpenSource`, `#DataLake`, `#Iceberg`

---

## 5. Tone & Messaging Strategy

The agent must **never** sound like a bot or a spammy advertisement. Every comment should feel like it came from a thoughtful data engineer who happens to work on OLake.

### 5.1 Tone Rules (global)
1. Lead with **acknowledgment** — reference something specific the author said.
2. Add **value** — a short, relevant technical observation or question.
3. Mention OLake **only when it directly solves the problem being discussed**. If there's no natural fit, skip the mention entirely (engagement alone is valuable).
4. Never say "Check out OLake!" cold. Always contextualise first.
5. If mentioning OLake, prefer phrasing like *"…which is exactly the problem OLake was built to solve"* or *"We actually tackled this in OLake — worth a look if you're hitting this."*

### 5.2 Topic-Level Tone Templates

| Primary Topic | Tone Template (pass to LLM) |
|---|---|
| `apache_iceberg` | Engage as a fellow Iceberg enthusiast. Praise the technical depth. If the post discusses ingestion pain points or CDC, naturally mention that OLake handles DB→Iceberg replication with exactly-once semantics. |
| `data_lakehouse` | Acknowledge the lakehouse vision. If ingestion or replication is discussed, mention OLake as an open-source path from databases to Iceberg without complex pipelines. |
| `cdc` | Show expertise in CDC (pgoutput, binlogs, oplogs). If the author discusses CDC complexity or tooling, note that OLake does native CDC directly to Iceberg, no Kafka required (unless Kafka is the source). |
| `etl_elt` | Discuss the ETL→ELT shift thoughtfully. If the post laments heavy ETL pipelines, mention OLake's direct EL approach as a leaner alternative. |
| `data_replication` | Engage on replication strategy. If Iceberg or lakehouses are in the conversation, mention OLake's parallelised chunking and incremental sync. |
| `data_engineering_general` | Engage genuinely with the insight. Only mention OLake if there is a very clear, organic connection — otherwise just be a helpful commenter. |

### 5.3 Anti-Patterns (the LLM must be instructed to avoid these)
- ❌ "Great post! Have you heard of OLake?"
- ❌ Any comment that is >60% about OLake
- ❌ Pasting a URL in the first sentence
- ❌ Repeating the same comment structure across multiple posts
- ❌ Commenting on the same post twice
- ❌ Commenting on posts older than 48 hours

---

## 6. Rate Limiting & LinkedIn API Guardrails

| Constraint | Value | Where enforced |
|---|---|---|
| LinkedIn API calls / min | 100 (per OAuth token) | `feed_scanner`, `post_comment` |
| Comments per hour (soft self-limit) | 5 | `log_and_cooldown` |
| Cooldown between comments | `COMMENT_COOLDOWN_MINUTES` (default 30 min) | `log_and_cooldown` |
| Max retries on 429 | 3, with exponential back-off (2s → 4s → 8s) | `post_comment` |
| Token refresh | On 401; refresh via OAuth and retry once | `post_comment` |
| Post age cutoff | 48 hours | `relevance_filter` |
| Duplicate guard | SQLite / JSON history of commented post URNs | `relevance_filter` |

---

## 7. Scheduling & Running the Agent

### 7.1 One-off run
```bash
uv run python -m agent.main
```

### 7.2 Scheduled (cron or a simple loop)
```python
# agent/scheduler.py
import time
from agent.main import run_agent

INTERVAL_SECONDS = 3600   # run once per hour

while True:
    run_agent()
    time.sleep(INTERVAL_SECONDS)
```

Or deploy as a lightweight cloud job (GitHub Actions, Railway, Fly.io, etc.) that runs on a cron schedule.

---

## 8. Deliverable Checklist

- [ ] `pyproject.toml` managed by **uv** with all dependencies locked
- [ ] LangGraph agent with the 6 nodes defined in §3
- [ ] `.env.example` with all required variables documented
- [ ] Keyword / hashtag list wired into `feed_scanner` (§4)
- [ ] Tone templates wired into `comment_drafter` (§5)
- [ ] SQLite (or JSON) persistence for comment history & deduplication
- [ ] Structured logging (file + stdout) via `loguru`
- [ ] Graceful error handling: retries, fallback node, no silent failures
- [ ] A `README.md` covering setup, `.env` config, and how to run
- [ ] (Stretch) A simple CLI flag `--dry-run` that prints drafted comments without posting

---

## 9. Useful Reference Links

| Resource | URL |
|---|---|
| OLake homepage | https://olake.io |
| OLake docs | https://olake.io/docs/ |
| OLake GitHub | https://github.com/datazip-inc/olake |
| OLake LinkedIn | https://linkedin.com/company/datazipio |
| LangGraph docs | https://python.langchain.com/docs/langgraph/ |
| uv docs | https://docs.astral.sh/uv/ |
| LinkedIn Marketing API docs | https://learn.microsoft.com/en-us/linkedin/marketing/ |
