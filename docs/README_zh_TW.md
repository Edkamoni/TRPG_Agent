# TRPG Agent

[English](./README_en.md) | [简体中文](./README_zh.md) | [繁體中文](./README_zh_TW.md) | [日本語](./README_ja.md)

[中文路线图](./roadmap_zh.md) | [English Roadmap](./roadmap_en.md)

## 簡介

TRPG Agent 是一個基於大模型的本地文字 TRPG Agent。專案使用 FastAPI + Jinja2 + Vanilla JS 建立網頁介面,透過 SSE `/api/chat/stream` 串流回傳 AI 敘事,並使用 `saves/` 下的 JSON 檔案保存本地存檔。

LLM 呼叫層使用 **LangChain** 的 `ChatOpenAI`,透過智譜 AI 的 OpenAI 相容端點存取 GLM 系列模型,並使用 Pydantic 的 `GameAction` 結構化輸出取代傳統的標籤解析,讓 AI 的敘事與遊戲機制能更穩定地解耦。

專案入口為 `TRPG_Agent/main.py`,在專案目錄中執行 `python main.py` 後,開啟 `http://localhost:7860/main` 或 `http://127.0.0.1:7860/main`。

## 功能

- 支援 DND 和 CNC 兩種世界觀
- AI 扮演 DM/GM,提供文字敘事與行動回饋
- 透過 SSE 串流輸出聊天內容(先串流輸出敘事,再以結構化 JSON 回傳檢定/經驗/快捷行動等元資料)
- 支援 d20 檢定、大成功和大失敗
- 支援角色建立、屬性分配、經驗和升級
- 支援 JSON 本地存檔讀取與保存(相容舊版標籤格式存檔)
- 提供模型設定和規則設定頁面,可線上熱改 `.env`
- 場景級生命週期管理:達到 `SCENE_TURN_LIMIT` 後由 AI 在結構化輸出中提供 ≤200 字摘要,舊場景上下文會被壓縮為單條系統訊息以控制 token 佔用,讀檔時依相關性回填摘要

## 技術棧

- **後端**:FastAPI + Uvicorn + Jinja2
- **前端**:Vanilla JS + 伺服器端渲染(無 SPA、無建置步驟)
- **LLM 框架**:LangChain(`langchain-openai` + `langchain-core`)
- **結構化輸出**:Pydantic v2 + `ChatOpenAI.with_structured_output()`
- **模型提供方**:智譜 AI(GLM-4 等),透過 OpenAI 相容端點存取

## 快速開始

```bash
cd TRPG_Agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

啟動前必須在 `.env` 中設定:

```env
ZHIPU_API_KEY=你的智譜 API Key
```

瀏覽器開啟:`http://localhost:7860/main`

## 頁面/路由

| 路由 | 說明 |
|---|---|
| `/main` | 世界觀選擇頁 |
| `/save` | 存檔管理頁 |
| `/createCharacter` | 角色建立頁 |
| `/game` | 遊戲對話頁 |
| `/settings` | 設定入口 |
| `/settings/model` | 模型設定頁 |
| `/settings/rules` | 規則設定頁 |

主要串流介面:`POST /api/chat/stream`,回傳 `text/event-stream`。

### SSE 事件類型

| 事件 | 說明 |
|---|---|
| `chunk` | 增量敘述文字(來自 AI 串流輸出) |
| `check_request` | 觸發檢定時通知前端彈出骰子介面 |
| `check` | 已解決的骰子檢定結果(屬性、DC、骰值、成功與否) |
| `actions` | 當前回合的快捷行動按鈕(最多 4 個) |
| `scene_change` | 場景切換通知,負載為 `{scene, summary}` |
| `done` | 串流正常結束 |
| `error` | 串流異常中止,負載中包含錯誤訊息 |

## 遊戲流程

1. 在 `/main` 選擇 DND 或 CNC 世界觀
2. 在 `/save` 讀取存檔或建立新遊戲
3. 在 `/createCharacter` 建立角色並分配屬性
4. 在 `/game` 與 AI 主持人對話並推進冒險
5. 觸發檢定時自動執行 d20 判定
6. 遊戲狀態可保存到 `saves/` JSON 存檔

## AI 輸出協議

AI 的回覆會被解析為如下結構化物件(`schemas/game_action.py:GameAction`):

```python
class GameAction(BaseModel):
    narrative: str                              # 乾淨的 DM 敘述文字(不含任何標籤)
    check: Optional[CheckRequest] = None        # 觸發的屬性檢定(attribute + dc)
    exp_reward: Optional[int] = None            # 經驗獎勵
    inspiration: Optional[int] = None           # 激勵骰(僅 DND)
    breakthrough: Optional[str] = None          # 突破屬性(僅 CNC)
    quick_actions: List[str] = []               # 快捷行動建議
    scene: Optional[str] = None                 # 當前場景描述
    scene_summary: Optional[str] = None         # 場景結束時由 AI 提供的 ≤200 字摘要,平時為 None
```

場景生命週期:每次 `process_input()` 遞增 `scene_turns`;當 `action.scene` 與角色當前場景不一致且 `scene_turns >= 3` 時即視為場景切換,舊場景訊息會被壓縮為單條 `[场景摘要: ...]` 系統訊息並歸檔到 `scene_history`(`SceneSummary` 清單)。達到 `SCENE_TURN_LIMIT`(預設 10)時系統提示詞會追加強制收尾指令,要求 AI 在下一輪透過 `scene_summary` 欄位輸出摘要。讀檔後下一次輸入會觸發 `filter_relevant_summaries()` 選擇性回填相關摘要。

流程為:串流輸出 `narrative` 文字到 SSE → 串流結束後呼叫一次結構化解析以取得完整 `GameAction` → 觸發對應的遊戲機制(檢定、加經驗、刷新快捷按鈕等)。

舊版標籤存檔(含 `[检定:...]`、`[快捷:...]` 等中文標籤)仍可正常載入,透過保留的 `strip_tags()` 與 `parse_quick_actions()` 函式清理並解析。

## 世界觀

### DND

DND 是偏史詩、莊重的中世紀奇幻世界觀。AI 透過 `GameAction.check` 欄位觸發屬性檢定。

### CNC

CNC 是偏輕鬆、吐槽風格的國產奇幻世界觀。AI 透過 `GameAction.check` 欄位觸發挑戰、透過 `GameAction.breakthrough` 欄位觸發屬性突破。

## 規則

### d20 檢定

檢定公式:`d20 + 屬性調整值 >= DC`

- 自然 20:大成功
- 自然 1:大失敗
- 其他點數依公式判斷是否成功

常見 DC:

| DC | 難度 |
|---|---|
| 10 | 簡單 |
| 15 | 中等 |
| 20 | 困難 |
| 25 | 極難 |

### 角色屬性

角色使用 6 項屬性,內部欄位名如下:

| 欄位 | 中文 |
|---|---|
| `strength` | 力量 |
| `dexterity` | 敏捷 |
| `constitution` | 體質 |
| `intelligence` | 智力 |
| `wisdom` | 感知 |
| `charisma` | 魅力 |

屬性調整值按 `(屬性值 - 10) // 2` 計算。

## 配置

配置透過 `.env` 和 `config.py` 讀取。`ZHIPU_API_KEY` 為必填。

| 變數 | 預設值 | 說明 |
|---|---|---|
| `ZHIPU_API_KEY` | — | 智譜 API Key,必填 |
| `MODEL_NAME` | `glm-4` | 模型名稱 |
| `MAX_HISTORY` | `20` | 保留的歷史對話輪數 |
| `INITIAL_ATTRIBUTE_POINTS` | `20` | 初始屬性點 |
| `TEMPERATURE` | `0.85` | 模型取樣溫度 |
| `MAX_TOKENS` | `2048` | 單次回覆最大 token 數 |
| `MAX_RETRIES` | `3` | API 呼叫重試次數 |
| `STREAM_TIMEOUT` | `60` | 串流回應逾時(秒) |
| `EXP_THRESHOLD` | `100` | 升級經驗閾值基數 |
| `SCENE_TURN_LIMIT` | `10` | 場景輪次軟上限(範圍 5-30,超出範圍會回退到 10) |

設定頁支援執行時熱改並可勾選「同時寫入 `.env`」,由 `env_writer.upsert_env()` 持久化(保留原檔案行序與註解)。修改 `MODEL_NAME` 或 `ZHIPU_API_KEY` 後,下一次聊天會自動重建 `LLMClient` 實例。

## 專案結構

```text
TRPG_Agent/
├── main.py              # uvicorn 入口
├── app.py               # FastAPI 路由、SSE 端點、JSON API
├── config.py            # 配置載入
├── game_engine.py       # 遊戲狀態、訊息歷史、檢定執行
├── llm_client.py        # LangChain ChatOpenAI + 結構化輸出
├── storage.py           # JSON 存檔讀寫
├── env_writer.py        # .env 熱寫入
├── schemas/             # Pydantic 結構化輸出模型
│   └── game_action.py
├── rules/               # 骰子、角色、檢定規則
├── worlds/              # 世界觀(DND、CNC)+ system prompt
├── templates/           # Jinja2 HTML 模板
├── static/              # CSS + JS
├── saves/               # JSON 存檔
├── scripts/             # 輔助指令稿(含 `verify_scene_features.py` 場景特性 E2E 驗證)
├── docs/                # 多語言 README + 路線圖
├── requirements.txt
└── .env.example
```

## 開發說明/注意事項

- 目前 Web UI 基於 FastAPI、Jinja2、Vanilla JS 和 SSE
- `main.py` 啟動 uvicorn,預設監聽 `127.0.0.1:7860`,單行程(`workers=1`)
- 所有頁面由伺服器端 Jinja2 模板渲染,無前端建置
- 聊天串流使用 `/api/chat/stream`
- 存檔為 `saves/` 目錄下的 JSON 檔案
- 世界觀包括 DND 和 CNC
- 修改模型或規則配置時,優先透過設定頁面或 `.env` 調整
- 多個瀏覽器分頁共用同一個 `GameEngine` 單例(本地單使用者設計)
- `llm_client.py` 中保留的 `_LEGACY_*` 正則常數、`strip_tags()`、`parse_quick_actions()` 僅用於舊版標籤存檔的向後相容

## 路線圖連結

- [中文路线图](./roadmap_zh.md)
- [English Roadmap](./roadmap_en.md)
