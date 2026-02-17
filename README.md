# OLake Slack Community Agent

An intelligent AI agent that manages the OLake community in Slack. The agent handles support questions, technical issues, and discussions by deeply reasoning through problems, searching documentation, and providing accurate solutions with citations.

## 🚀 Features

- **Deep Reasoning**: Multi-iteration analysis for accurate problem-solving
- **Context-Aware**: Learns from user history and patterns
- **Documentation Search**: Retrieves relevant documentation automatically
- **Smart Routing**: Determines whether to answer, clarify, or escalate
- **Structured Logging**: Comprehensive event logging for all interactions
- **User Profiling**: Tracks user knowledge level and interaction patterns

## 📋 Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Slack App with Bot Token
- Google Gemini or OpenAI API key
- ngrok (for local development)

## 🛠️ Installation

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Setup Slack App**:
   - Go to [api.slack.com/apps](https://api.slack.com/apps)
   - Create a new app or use existing
   - Enable **Event Subscriptions**
   - Subscribe to bot events: `message.channels`, `message.groups`, `message.im`, `app_mention`
   - Install app to workspace
   - Copy Bot Token (xoxb-...) and Signing Secret to `.env`

## 🏃 Usage

### Start the Agent

```bash
# Start webhook server
uv run python -m agent.main

# Custom port
uv run python -m agent.main --port 3000

# Validate configuration
uv run python -m agent.main --validate-config

# View statistics
uv run python -m agent.main --stats
```

### Local Development with ngrok

```bash
# Start ngrok tunnel
ngrok http 3000

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# Set as Request URL in Slack: https://abc123.ngrok.io/slack/events
```

## 🏗️ Architecture

```
┌─────────────────┐
│ Slack Message   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Intent Analyzer │ (Classify: question/issue/discussion)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Context Builder │ (Load user history + thread context)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Doc Retriever   │ (Search documentation)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Deep Reasoner   │ (Multi-iteration analysis, 2-5 iterations)
└────────┬────────┘
         │
         ├─[high confidence]─────▶ Solution Provider
         │
         ├─[needs clarification]─▶ Clarification Asker
         │
         └─[low confidence]──────▶ Escalation Handler
```

## ⚙️ Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (xoxb-...) |
| `SLACK_SIGNING_SECRET` | For webhook verification |
| `LLM_PROVIDER` | "gemini" or "openai" |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | LLM API key |
| `MAX_REASONING_ITERATIONS` | Max iterations for deep reasoning (default: 5) |
| `CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY` | Confidence threshold (default: 0.75) |
| `ENABLE_DEEP_REASONING` | Enable multi-iteration reasoning |
| `ENABLE_USER_LEARNING` | Enable user profiling |

## 📁 Project Structure

```
agent/
├── __init__.py
├── config.py              # Configuration management
├── state.py               # State definitions
├── llm.py                 # LLM utilities (Gemini/OpenAI)
├── slack_client.py        # Slack API client
├── persistence.py         # Database layer
├── logger.py              # Structured logging
├── graph.py               # LangGraph workflow
├── main.py                # Flask webhook server
└── nodes/
    ├── intent_analyzer.py
    ├── context_builder.py
    ├── doc_retriever.py
    ├── deep_reasoner.py
    ├── solution_provider.py
    ├── clarification_asker.py
    └── escalation_handler.py
```

## 📊 Logging

The agent creates structured logs in the `logs/` directory:

- `events.jsonl`: All events (messages, reasoning, responses)
- `errors.jsonl`: Error logs
- `reasoning.jsonl`: Detailed reasoning iterations
- `agent.log`: Standard log file

## 🔍 How It Works

1. **Message Received**: User sends message in Slack
2. **Intent Classification**: LLM classifies as question/issue/discussion
3. **Context Loading**: Retrieves user's history and thread context
4. **Documentation Search**: Searches OLake docs for relevant information
5. **Deep Reasoning**: 2-5 iterations of analysis to understand the problem
6. **Response Decision**:
   - **High Confidence (≥0.75)**: Provides solution with citations
   - **Needs Info**: Asks clarifying questions
   - **Low Confidence**: Escalates to human team

## 🎯 Future Enhancements

- Vector search for documentation (ChromaDB/Pinecone)
- GitHub issue integration
- Automated testing framework
- Analytics dashboard
- Multi-language support

## 📝 License

MIT

## 🔗 Links

- [OLake Docs](https://olake.io/docs/)
- [OLake GitHub](https://github.com/datazip-inc/olake)
- [Slack API](https://api.slack.com/)
- [LangGraph](https://python.langchain.com/docs/langgraph/)
