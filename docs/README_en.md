# TRPG Agent

[English](./README_en.md) | [简体中文](./README_zh.md) | [繁體中文](./README_zh_TW.md) | [日本語](./README_ja.md)

[中文路线图](./roadmap_zh.md) | [English Roadmap](./roadmap_en.md)

## Introduction

TRPG Agent is a local text-based tabletop role-playing game agent powered by large language models. The web interface is built with FastAPI, Jinja2, Vanilla JS, and SSE. AI narration streams through `/api/chat/stream`, and saves are stored as local JSON files under `saves/`.

The LLM layer uses **LangChain**'s `ChatOpenAI` to access GLM-series models through Zhipu AI's OpenAI-compatible endpoint, and uses Pydantic-based `GameAction` structured outputs to decouple AI narration from game mechanics — replacing the older Chinese tag-parsing approach.

The entry point is `TRPG_Agent/main.py`. Run `python main.py` in the project directory, then open `http://localhost:7860/main` or `http://127.0.0.1:7860/main`.

## Features

- Supports two world settings: DND and CNC
- AI acts as the DM/GM for narration and action feedback
- Streams chat responses through SSE (narration streamed first, then a structured JSON returns metadata such as checks, XP, and quick actions)
- Supports d20 checks, critical success, and critical failure
- Supports character creation, attribute allocation, XP, and leveling
- Supports local JSON save/load (legacy tag-format saves remain compatible)
- Model and rule settings pages with live `.env` hot-write
- Scene-level lifecycle management: once `SCENE_TURN_LIMIT` is hit, the AI emits a ≤200-character summary in its structured output, prior-scene context is compressed into a single system message to bound token usage, and relevant summaries are re-injected on save load

## Tech Stack

- **Backend**: FastAPI + Uvicorn + Jinja2
- **Frontend**: Vanilla JS + server-side rendering (no SPA, no build step)
- **LLM framework**: LangChain (`langchain-openai` + `langchain-core`)
- **Structured output**: Pydantic v2 + `ChatOpenAI.with_structured_output()`
- **Model provider**: Zhipu AI (GLM-4 and others) via the OpenAI-compatible endpoint

## Quick Start

```bash
cd TRPG_Agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Before starting, configure the required environment variable in `.env`:

```env
ZHIPU_API_KEY=your Zhipu API key
```

Open: `http://localhost:7860/main`

## Pages / Routes

| Route | Description |
|---|---|
| `/main` | World selection page |
| `/save` | Save management page |
| `/createCharacter` | Character creation page |
| `/game` | Game chat page |
| `/settings` | Settings entry |
| `/settings/model` | Model configuration page |
| `/settings/rules` | Rule configuration page |

Main streaming endpoint: `POST /api/chat/stream`, returning `text/event-stream`.

### SSE Event Types

| Event | Description |
|---|---|
| `chunk` | Incremental narration text (from the AI's streaming output) |
| `check_request` | Notifies the frontend to open the dice prompt when a check is triggered |
| `check` | Resolved dice check result (attribute, DC, roll value, success flag) |
| `actions` | Quick action buttons for the current turn (up to 4) |
| `scene_change` | Scene transition notification with payload `{scene, summary}` |
| `done` | Stream finished normally |
| `error` | Stream aborted with an error payload |

## Game Flow

1. Choose DND or CNC on `/main`
2. Load a save or start a new game on `/save`
3. Create a character and allocate attributes on `/createCharacter`
4. Chat with the AI Game Master on `/game`
5. d20 checks are resolved automatically when triggered
6. Game state can be saved as JSON under `saves/`

## AI Output Protocol

The AI's reply is parsed into the following structured object (`schemas/game_action.py:GameAction`):

```python
class GameAction(BaseModel):
    narrative: str                              # Clean DM narration (no tags)
    check: Optional[CheckRequest] = None        # Triggered attribute check (attribute + dc)
    exp_reward: Optional[int] = None            # XP reward
    inspiration: Optional[int] = None           # Inspiration die (DND only)
    breakthrough: Optional[str] = None          # Breakthrough attribute (CNC only)
    quick_actions: List[str] = []               # Suggested quick actions
    scene: Optional[str] = None                 # Current scene description
    scene_summary: Optional[str] = None         # ≤200-char summary emitted by the AI when a scene ends; None otherwise
```

Scene lifecycle: each `process_input()` call increments `scene_turns`. When `action.scene` differs from the character's current scene and `scene_turns >= 3`, the engine treats it as a scene transition: the old scene's messages are compressed into a single `[场景摘要: ...]` system message and archived into `scene_history` (a `SceneSummary` list). Once `SCENE_TURN_LIMIT` (default 10) is reached, the system prompt appends a forced wrap-up instruction asking the AI to emit a `scene_summary` on the next turn. After loading a save, the next user input triggers `filter_relevant_summaries()` to selectively re-inject relevant prior summaries.

The flow is: stream `narrative` text through SSE → after streaming finishes, run a structured parse to obtain the full `GameAction` → trigger the corresponding game mechanics (checks, XP gain, refreshing quick action buttons, etc.).

Legacy tag-format saves (containing Chinese tags such as `[检定:...]` and `[快捷:...]`) remain loadable through the retained `strip_tags()` and `parse_quick_actions()` helpers.

## World Settings

### DND

DND is an epic, solemn medieval fantasy setting. The AI triggers attribute checks via the `GameAction.check` field.

### CNC

CNC is a lighthearted Chinese fantasy setting with a joking tone. The AI triggers challenges via `GameAction.check` and attribute breakthroughs via `GameAction.breakthrough`.

## Rules

### d20 Checks

Check formula: `d20 + attribute modifier >= DC`

- Natural 20: critical success
- Natural 1: critical failure
- Other rolls are resolved by the formula

Common DC values:

| DC | Difficulty |
|---|---|
| 10 | Easy |
| 15 | Medium |
| 20 | Hard |
| 25 | Extreme |

### Character Attributes

Characters use 6 attributes with these internal field names:

| Field | Meaning |
|---|---|
| `strength` | Strength |
| `dexterity` | Dexterity |
| `constitution` | Constitution |
| `intelligence` | Intelligence |
| `wisdom` | Wisdom |
| `charisma` | Charisma |

Attribute modifiers are calculated as `(score - 10) // 2`.

## Configuration

Configuration is loaded from `.env` and `config.py`. `ZHIPU_API_KEY` is required.

| Variable | Default | Description |
|---|---|---|
| `ZHIPU_API_KEY` | — | Zhipu API key, required |
| `MODEL_NAME` | `glm-4` | Model name |
| `MAX_HISTORY` | `20` | Conversation rounds kept in history |
| `INITIAL_ATTRIBUTE_POINTS` | `20` | Initial attribute points |
| `TEMPERATURE` | `0.85` | Model sampling temperature |
| `MAX_TOKENS` | `2048` | Maximum tokens per response |
| `MAX_RETRIES` | `3` | API retry count |
| `STREAM_TIMEOUT` | `60` | Streaming response timeout in seconds |
| `EXP_THRESHOLD` | `100` | Base XP threshold for leveling |
| `SCENE_TURN_LIMIT` | `10` | Soft cap on turns per scene (range 5-30; out-of-range values fall back to 10) |

The settings pages allow live edits and can optionally persist them to `.env` via `env_writer.upsert_env()` (preserving original line order and comments). After changing `MODEL_NAME` or `ZHIPU_API_KEY`, the `LLMClient` is rebuilt on the next chat call.

## Project Structure

```text
TRPG_Agent/
├── main.py              # uvicorn entry point
├── app.py               # FastAPI routes, SSE endpoint, JSON APIs
├── config.py            # Configuration loading
├── game_engine.py       # Game state, message history, check execution
├── llm_client.py        # LangChain ChatOpenAI + structured output
├── storage.py           # JSON save I/O
├── env_writer.py        # .env hot-write helper
├── schemas/             # Pydantic structured output models
│   └── game_action.py
├── rules/               # Dice, character, check rules
├── worlds/              # World settings (DND, CNC) + system prompts
├── templates/           # Jinja2 HTML templates
├── static/              # CSS + JS
├── saves/               # JSON saves
├── scripts/             # Helper scripts (includes `verify_scene_features.py` for end-to-end scene feature verification)
├── docs/                # Multilingual READMEs + roadmaps
├── requirements.txt
└── .env.example
```

## Development Notes

- The current web UI uses FastAPI, Jinja2, Vanilla JS, and SSE
- `main.py` starts uvicorn on `127.0.0.1:7860` by default with a single worker
- Pages are rendered by server-side Jinja2 templates; there is no frontend build
- Chat streaming uses `/api/chat/stream`
- Saves are JSON files under `saves/`
- Available worlds are DND and CNC
- Prefer the settings pages or `.env` for model and rule configuration
- All browser tabs share a single `GameEngine` instance (local single-user design)
- The `_LEGACY_*` regex constants, `strip_tags()`, and `parse_quick_actions()` in `llm_client.py` are retained solely for backward compatibility with legacy tag-format saves

## Roadmap Links

- [中文路线图](./roadmap_zh.md)
- [English Roadmap](./roadmap_en.md)
