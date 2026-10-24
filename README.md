# project-poltergeist

**GHOST OS // Container #001** is a local four-pane terminal command center for three AI personas: AURA, GHOST, and GASPARÍN. It uses a JSONL shared context bus, an Ollama-compatible chat-completions endpoint, and an optional sequential Kokoro-FastAPI voice queue.

## Requirements

- Python 3.10 or newer
- Docker Compose (only needed for local Kokoro speech)
- A local Ollama server for live model replies; without it, the app uses clearly labeled mock replies
- A working host audio output device for speech playback

## Install and launch

From this repository directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d kokoro
python app.py
```

The app starts with speech disabled. Use `/voice tts --init-all` in the input bar to enable speech and queue the three-persona voice check. Use `/voice set <agent> <voice_id>` to change a voice, and `/wallet add <amount>` to update the in-memory treasury counter.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_ENDPOINT` | `http://localhost:11434/v1/chat/completions` | Ollama or other OpenAI-compatible chat endpoint |
| `LLM_MODEL` | `llama3.2` | Model name sent with each chat request |
| `KOKORO_ENDPOINT` | `http://localhost:8880/v1/audio/speech` | Kokoro-FastAPI speech endpoint |
| `SHARED_BUS_PATH` | `workspace/shared_bus.jsonl` | Append-only conversation log |
| `PERSONAS_PATH` | `AGENTS.md` | Persona prompt definitions |

The bus is created on first launch. Its last 25 entries are included in each agent request. The container publishes Kokoro on host port `8880`; the app connects to Ollama on host port `11434`.

## Commands

```text
/voice tts --init-all
/voice set <agent> <voice_id>
/wallet add <amount>
```

Supported agent names are `AURA`, `GHOST`, and `GASPARIN` (also `CASPER` for the voice command). Mention an agent in a message with `@AURA`, `@GHOST`, or `@GASPARIN`; messages without a mention start the default AURA → GASPARÍN → GHOST sequence. Each user prompt is limited to three agent replies.
