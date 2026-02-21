# OLake Slack Community Agent — Tech Stack, Models, and Tools

This document outlines the end-to-end technology stack, the AI models, and the infrastructure tools used in the **OLake Slack Community Agent** project.

The application is structured in two main services:
1. **Agent Service:** Interacts with Slack, handles multi-iteration deep reasoning, and drives the system using a LangGraph-based workflow.
2. **RAG Microservice:** Handles chunking, local embeddings, cross-encoder re-ranking, and vector search operations.

---

## 🤖 AI Models

### 1. Large Language Models (LLMs)
The Agent Service relies on external API providers for intent classification, content generation, and multi-step reasoning. Provider is toggled via the `LLM_PROVIDER` environment variable.
- **Google Gemini:** `gemini-3-flash-preview` (default via the `google.genai` SDK)
- **OpenAI:** `gpt-4-turbo-preview` (via the `openai` SDK)

### 2. Embedding Model (Local)
Used by the RAG Microservice for embedding documentation content and queries for vector retrieval.
- **Model:** `nomic-ai/nomic-embed-text-v1.5`
- **Execution:** Runs locally natively via `sentence-transformers`. Pre-pends specific nomic task prefixes (e.g., `search_document: ` and `search_query: `) to inputs.
- **Dimensions:** Typically outputs 768 dimensions.

### 3. Re-Ranking Model (Local)
Following a bi-encoder vector search, a cross-encoder evaluates (query, passage) pairs jointly to provide a highly precise relevance score, yielding much better search accuracy.
- **Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Execution:** Runs locally via `sentence-transformers` relying on `CrossEncoder`.

---

## 🛠 Tech Stack

### Languages & Runtimes
- **Python:** `3.11+` (Core language for both Agent and RAG microservice)

### Agent Service
- **Agent Framework / Reasoning:**
  - `langchain` + `langgraph`: Powers the state machines, workflow graphing, and multi-iteration reasoning nodes (Intent Analyzer, Context Builder, Deep Reasoner, etc.).
- **Slack Integration:**
  - `slack-sdk`: Connects to Slack's APIs, posts replies, and verifies signatures.
  - `Flask`: Provides the webhook server (`agent.main`) to receive real-time Events API payloads from Slack.
- **LLM Clients:**
  - `google-genai` / `openai` / `python-dotenv`

### RAG Microservice
- **API Framework:** `FastAPI` combined with `uvicorn[standard]` to handle incoming HTTP/MCP RAG requests.
- **Model Context Protocol (MCP):** 
  - `fastmcp`: Exposes RAG tools standardized for seamless integration.
- **Embedding / Vector Manipulation:**
  - `sentence-transformers` & `einops`: Handles the model execution for both the bi-encoder (embeddings) and cross-encoder (re-ranker).
- **Vector Database Client:** 
  - `qdrant-client`: Interface for storing and searching vector spaces.

### Data persistence
- **Vector Database:** `Qdrant` (Running via Docker for handling embedded documentation vectors).
- **State Database:** `SQLite` (local path: `/app/data/slack_agent.db` track user conversations and event history).

---

## 🔧 Infrastructure & Tooling

### Package / Dependency Management
- **`uv`:** The ultra-fast Python package and environment manager (handling `uv.lock` and running tasks).
- **`hatchling`:** Primary build backend standardizing the package creation.

### Containerization & Deployment
- **Docker:** `Dockerfile` & `Dockerfile.agent` encapsulate the isolated runtime environments.
- **Docker Compose:** Maps networking volumes between the RAG microservice, the main Agent HTTP port, and spins up the Qdrant container automatically (`docker-compose.yml`). 

### Local Development
- **`ngrok`:** Exposes the local Flask webhook server (`localhost:3000` / `localhost:8080`) to the public internet so Slack API can deliver event webhooks securely during development testing.
- **`pytest` & `pytest-asyncio`:** Built-in tools for covering async tests and components.
