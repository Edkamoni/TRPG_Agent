# TRPG Agent

[English](docs/README_en.md) | [简体中文](docs/README_zh.md) | [繁體中文](docs/README_zh_TW.md) | [日本語](docs/README_ja.md)

[路线图](docs/roadmap_zh.md) | [Roadmap](docs/roadmap_en.md)

## 背景

跑团推广最大的难点一直在于，需要多人 + 长时间投入来进行。因此一直在考虑想找一个办法让跑团能变成一个单人的事情。

## 简介

TRPG Agent 是一个基于大模型的本地文字 TRPG Agent。项目使用 FastAPI + Jinja2 + Vanilla JS 构建网页界面，通过 SSE `/api/chat/stream` 流式返回 AI 叙事，并使用 `saves/` 下的 JSON 文件保存本地存档。

LLM 调用层使用 **LangChain** 的 `ChatOpenAI`，通过智谱 AI 的 OpenAI 兼容端点访问 GLM 系列模型，并使用 Pydantic 的 `GameAction` 结构化输出代替传统的标签解析，让 AI 的叙事与游戏机制更稳定地解耦。

项目入口为 `TRPG_Agent/main.py`，在项目目录中运行 `python main.py` 后访问 `http://localhost:7860/main` 或 `http://127.0.0.1:7860/main`。

## 功能

- 支持 DND 和 CNC 两种世界观
- AI 扮演 DM/GM，提供文字叙事与行动反馈
- 通过 SSE 流式输出聊天内容（先流式输出叙事，再以结构化 JSON 返回检定/经验/快捷行动等元数据）
- 支持 d20 检定、大成功和大失败
- 支持角色创建、属性分配、经验和升级
- 支持 JSON 本地存档读取与保存（兼容旧版标签格式存档）
- 提供模型设置和规则设置页面，可在线热改 `.env`

## 技术栈

- **后端**：FastAPI + Uvicorn + Jinja2
- **前端**：Vanilla JS + 服务端渲染（无 SPA、无构建步骤）
- **LLM 框架**：LangChain（`langchain-openai` + `langchain-core`）
- **结构化输出**：Pydantic v2 + `ChatOpenAI.with_structured_output()`
- **模型提供方**：智谱 AI（GLM-4 等），通过 OpenAI 兼容端点访问

## 快速开始

```bash
cd TRPG_Agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

启动前必须在 `.env` 中配置：

```env
ZHIPU_API_KEY=你的智谱 API Key
```

浏览器打开：`http://localhost:7860/main`

## 页面/路由

| 路由 | 说明 |
|---|---|
| `/main` | 世界观选择页 |
| `/save` | 存档管理页 |
| `/createCharacter` | 角色创建页 |
| `/game` | 游戏对话页 |
| `/settings` | 设置入口 |
| `/settings/model` | 模型配置页 |
| `/settings/rules` | 规则配置页 |

主要流式接口：`POST /api/chat/stream`，返回 `text/event-stream`。

### SSE 事件类型

| 事件 | 说明 |
|---|---|
| `chunk` | 增量叙述文本（来自 AI 流式输出） |
| `check_request` | 触发检定时通知前端弹出骰子界面 |
| `check` | 已解决的骰子检定结果（属性、DC、骰值、成功与否） |
| `actions` | 当前回合的快捷行动按钮（最多 4 个） |
| `done` | 流正常结束 |
| `error` | 流异常中止，负载中包含错误信息 |

## 游戏流程

1. 在 `/main` 选择 DND 或 CNC 世界观
2. 在 `/save` 读取存档或新建游戏
3. 在 `/createCharacter` 创建角色并分配属性
4. 在 `/game` 与 AI 主持人对话并推进冒险
5. 触发检定时自动执行 d20 判定
6. 游戏状态可保存到 `saves/` JSON 存档

## AI 输出协议

AI 的回复会被解析为如下结构化对象（`schemas/game_action.py:GameAction`）：

```python
class GameAction(BaseModel):
    narrative: str                              # 干净的 DM 叙述文本（不含任何标签）
    check: Optional[CheckRequest] = None        # 触发的属性检定（attribute + dc）
    exp_reward: Optional[int] = None            # 经验奖励
    inspiration: Optional[int] = None           # 激励骰（仅 DND）
    breakthrough: Optional[str] = None          # 突破属性（仅 CNC）
    quick_actions: List[str] = []               # 快捷行动建议
    scene: Optional[str] = None                 # 当前场景描述
```

流程为：流式输出 `narrative` 文本到 SSE → 流结束后调用一次结构化解析获取完整 `GameAction` → 触发对应的游戏机制（检定、加经验、刷新快捷按钮等）。

旧版标签存档（含 `[检定:...]`、`[快捷:...]` 等中文标签）仍可正常加载，通过保留的 `strip_tags()` 与 `parse_quick_actions()` 函数清理并解析。

## 世界观

### DND

DND 是偏史诗、庄重的中世纪奇幻世界观。AI 通过 `GameAction.check` 字段触发属性检定。

### CNC

CNC 是偏轻松、吐槽风格的国产奇幻世界观。AI 通过 `GameAction.check` 字段触发挑战、通过 `GameAction.breakthrough` 字段触发属性突破。

## 规则

### d20 检定

检定公式：`d20 + 属性调整值 >= DC`

- 自然 20：大成功
- 自然 1：大失败
- 其他点数按公式判断是否成功

常见 DC：

| DC | 难度 |
|---|---|
| 10 | 简单 |
| 15 | 中等 |
| 20 | 困难 |
| 25 | 极难 |

### 角色属性

角色使用 6 项属性，内部字段名如下：

| 字段 | 中文 |
|---|---|
| `strength` | 力量 |
| `dexterity` | 敏捷 |
| `constitution` | 体质 |
| `intelligence` | 智力 |
| `wisdom` | 感知 |
| `charisma` | 魅力 |

属性调整值按 `(属性值 - 10) // 2` 计算。

## 配置

配置通过 `.env` 和 `config.py` 读取。`ZHIPU_API_KEY` 为必填。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ZHIPU_API_KEY` | — | 智谱 API Key，必填 |
| `MODEL_NAME` | `glm-4` | 模型名称 |
| `MAX_HISTORY` | `20` | 保留的历史对话轮数 |
| `INITIAL_ATTRIBUTE_POINTS` | `20` | 初始属性点 |
| `TEMPERATURE` | `0.85` | 模型采样温度 |
| `MAX_TOKENS` | `2048` | 单次回复最大 token 数 |
| `MAX_RETRIES` | `3` | API 调用重试次数 |
| `STREAM_TIMEOUT` | `60` | 流式响应超时（秒） |
| `EXP_THRESHOLD` | `100` | 升级经验阈值基数 |

设置页支持运行时热改并可勾选「同时写入 `.env`」，由 `env_writer.upsert_env()` 持久化（保留原文件行序与注释）。修改 `MODEL_NAME` 或 `ZHIPU_API_KEY` 后，下一次聊天会自动重建 `LLMClient` 实例。

## 项目结构

```text
TRPG_Agent/
├── main.py              # uvicorn 入口
├── app.py               # FastAPI 路由、SSE 端点、JSON API
├── config.py            # 配置加载
├── game_engine.py       # 游戏状态、消息历史、检定执行
├── llm_client.py        # LangChain ChatOpenAI + 结构化输出
├── storage.py           # JSON 存档读写
├── env_writer.py        # .env 热写入
├── schemas/             # Pydantic 结构化输出模型
│   └── game_action.py
├── rules/               # 骰子、角色、检定规则
├── worlds/              # 世界观（DND、CNC）+ system prompt
├── templates/           # Jinja2 HTML 模板
├── static/              # CSS + JS
├── saves/               # JSON 存档
├── docs/                # 多语言 README + 路线图
├── requirements.txt
└── .env.example
```

## 开发说明/注意事项

- 当前 Web UI 基于 FastAPI、Jinja2、Vanilla JS 和 SSE
- `main.py` 启动 uvicorn，默认监听 `127.0.0.1:7860`，单进程（`workers=1`）
- 所有页面由服务端 Jinja2 模板渲染，无前端构建
- 聊天流使用 `/api/chat/stream`
- 存档为 `saves/` 目录下的 JSON 文件
- 世界观包括 DND 和 CNC
- 修改模型或规则配置时，优先通过设置页面或 `.env` 调整
- 多浏览器标签页共享同一个 `GameEngine` 单例（本地单用户设计）
- `llm_client.py` 中保留的 `_LEGACY_*` 正则常量、`strip_tags()`、`parse_quick_actions()` 仅用于旧版标签存档的向后兼容

## 路线图

- [路线图](docs/roadmap_zh.md)
- [Roadmap](docs/roadmap_en.md)
