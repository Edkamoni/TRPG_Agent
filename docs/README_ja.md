# TRPG Agent

[English](./README_en.md) | [简体中文](./README_zh.md) | [繁體中文](./README_zh_TW.md) | [日本語](./README_ja.md)

[中文路线图](./roadmap_zh.md) | [English Roadmap](./roadmap_en.md)

## 概要

TRPG Agent は、大規模言語モデルを利用したローカル向けテキスト TRPG Agent です。Web インターフェースは FastAPI + Jinja2 + Vanilla JS で構成され、SSE `/api/chat/stream` によって AI のナレーションをストリーミングします。セーブデータは `saves/` 配下のローカル JSON ファイルとして保存されます。

LLM 呼び出し層には **LangChain** の `ChatOpenAI` を使用し、智譜 AI の OpenAI 互換エンドポイント経由で GLM シリーズのモデルにアクセスします。さらに Pydantic ベースの `GameAction` 構造化出力を採用することで、従来のタグ解析方式に代わり、AI のナレーションとゲーム機構をより安定して分離しています。

エントリーポイントは `TRPG_Agent/main.py` です。プロジェクトディレクトリで `python main.py` を実行し、`http://localhost:7860/main` または `http://127.0.0.1:7860/main` を開いてください。

## 機能

- DND と CNC の 2 つの世界観に対応
- AI が DM/GM として叙述と行動フィードバックを提供
- SSE によるチャット内容のストリーミング(まずナレーションをストリーミングし、その後構造化 JSON で判定/経験値/クイックアクションなどのメタデータを返却)
- d20 判定、クリティカル成功、クリティカル失敗に対応
- キャラクター作成、属性配分、経験値、レベルアップに対応
- JSON 形式のローカルセーブとロードに対応(旧バージョンのタグ形式セーブとも互換)
- モデル設定ページとルール設定ページを提供し、`.env` をホットリロードで書き換え可能
- シーン単位のライフサイクル管理:`SCENE_TURN_LIMIT` に達すると AI が構造化出力で 200 文字以内のシーン要約を生成し、旧シーンのコンテキストは単一のシステムメッセージへ圧縮されてトークン消費を抑制。セーブのロード時には関連性に応じて要約を再注入

## 技術スタック

- **バックエンド**:FastAPI + Uvicorn + Jinja2
- **フロントエンド**:Vanilla JS + サーバーサイドレンダリング(SPA なし、ビルド工程なし)
- **LLM フレームワーク**:LangChain(`langchain-openai` + `langchain-core`)
- **構造化出力**:Pydantic v2 + `ChatOpenAI.with_structured_output()`
- **モデルプロバイダ**:智譜 AI(GLM-4 など)、OpenAI 互換エンドポイント経由

## クイックスタート

```bash
cd TRPG_Agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

起動前に `.env` で必須環境変数を設定してください:

```env
ZHIPU_API_KEY=your Zhipu API key
```

ブラウザで開く:`http://localhost:7860/main`

## ページ/ルート

| ルート | 説明 |
|---|---|
| `/main` | 世界観選択ページ |
| `/save` | セーブ管理ページ |
| `/createCharacter` | キャラクター作成ページ |
| `/game` | ゲーム会話ページ |
| `/settings` | 設定入口 |
| `/settings/model` | モデル設定ページ |
| `/settings/rules` | ルール設定ページ |

主なストリーミング API:`POST /api/chat/stream`、戻り値は `text/event-stream` です。

### SSE イベント種別

| イベント | 説明 |
|---|---|
| `chunk` | 増分のナレーションテキスト(AI のストリーミング出力由来) |
| `check_request` | 判定が発生した際にフロントへダイス入力 UI を表示するよう通知 |
| `check` | 解決済みのダイス判定結果(属性、DC、出目、成否) |
| `actions` | 現ターンのクイックアクションボタン(最大 4 個) |
| `scene_change` | シーン遷移通知。ペイロードは `{scene, summary}` |
| `done` | ストリーム正常終了 |
| `error` | ストリーム異常終了、ペイロードにエラー情報を含む |

## ゲームの流れ

1. `/main` で DND または CNC を選択
2. `/save` でセーブをロードするか新規ゲームを開始
3. `/createCharacter` でキャラクターを作成し属性を配分
4. `/game` で AI ゲームマスターと会話して冒険を進行
5. 判定が発生すると d20 判定を自動実行
6. ゲーム状態は `saves/` の JSON セーブに保存可能

## AI 出力プロトコル

AI の応答は次の構造化オブジェクトに解析されます(`schemas/game_action.py:GameAction`):

```python
class GameAction(BaseModel):
    narrative: str                              # クリーンな DM ナレーション(タグなし)
    check: Optional[CheckRequest] = None        # 発動した属性判定(attribute + dc)
    exp_reward: Optional[int] = None            # 経験値報酬
    inspiration: Optional[int] = None           # インスピレーションダイス(DND のみ)
    breakthrough: Optional[str] = None          # ブレイクスルー属性(CNC のみ)
    quick_actions: List[str] = []               # クイックアクションの提案
    scene: Optional[str] = None                 # 現在のシーン描写
    scene_summary: Optional[str] = None         # シーン終了時に AI が出力する 200 文字以内の要約。通常は None
```

シーンライフサイクル:`process_input()` ごとに `scene_turns` をインクリメントし、`action.scene` がキャラクターの現在シーンと異なり、かつ `scene_turns >= 3` の場合にシーン遷移とみなす。旧シーンのメッセージは単一の `[场景摘要: ...]` システムメッセージへ圧縮され、`scene_history`(`SceneSummary` リスト)へアーカイブされる。`SCENE_TURN_LIMIT`(既定値 10)に到達すると、システムプロンプトに強制締めくくり指示が付与され、次ターンで AI に `scene_summary` フィールドの出力を要求する。セーブをロードすると、次のユーザー入力時に `filter_relevant_summaries()` が呼び出され、関連する過去要約が選択的に再注入される。

流れ:`narrative` テキストを SSE でストリーミング → ストリーム終了後に一度だけ構造化解析を実行して完全な `GameAction` を取得 → 対応するゲーム機構(判定、経験値付与、クイックボタン更新など)をトリガー。

旧バージョンのタグ形式セーブ(`[检定:...]` や `[快捷:...]` などの中国語タグを含む)も、保持された `strip_tags()` と `parse_quick_actions()` 関数によって正常にロード・解析されます。

## 世界観

### DND

DND は叙事的で荘厳な中世ファンタジー世界観です。AI は `GameAction.check` フィールドを通じて属性判定を発動します。

### CNC

CNC は軽快でツッコミ調の中国ファンタジー世界観です。AI は `GameAction.check` フィールドでチャレンジを、`GameAction.breakthrough` フィールドで属性ブレイクスルーを発動します。

## ルール

### d20 判定

判定式:`d20 + 属性修正値 >= DC`

- ナチュラル 20:クリティカル成功
- ナチュラル 1:クリティカル失敗
- その他の出目は式に従って成功可否を判定

主な DC:

| DC | 難易度 |
|---|---|
| 10 | 簡単 |
| 15 | 普通 |
| 20 | 困難 |
| 25 | 極難 |

### キャラクター属性

キャラクターは 6 つの属性を使用し、内部フィールド名は次の通りです:

| フィールド | 意味 |
|---|---|
| `strength` | 筋力 |
| `dexterity` | 敏捷力 |
| `constitution` | 耐久力 |
| `intelligence` | 知力 |
| `wisdom` | 判断力 |
| `charisma` | 魅力 |

属性修正値は `(値 - 10) // 2` で計算します。

## 設定

設定は `.env` と `config.py` から読み込まれます。`ZHIPU_API_KEY` は必須です。

| 変数 | 既定値 | 説明 |
|---|---|---|
| `ZHIPU_API_KEY` | — | 智譜 API Key、必須 |
| `MODEL_NAME` | `glm-4` | モデル名 |
| `MAX_HISTORY` | `20` | 履歴に保持する会話ターン数 |
| `INITIAL_ATTRIBUTE_POINTS` | `20` | 初期属性ポイント |
| `TEMPERATURE` | `0.85` | モデルのサンプリング温度 |
| `MAX_TOKENS` | `2048` | 1 回の応答の最大 token 数 |
| `MAX_RETRIES` | `3` | API 呼び出しのリトライ回数 |
| `STREAM_TIMEOUT` | `60` | ストリーミング応答タイムアウト(秒) |
| `EXP_THRESHOLD` | `100` | レベルアップ経験値しきい値の基数 |
| `SCENE_TURN_LIMIT` | `10` | シーン当たりのターン数ソフト上限(範囲 5-30、範囲外は 10 にフォールバック) |

設定ページではランタイムでの編集に加え、「`.env` にも書き込む」をオンにすると `env_writer.upsert_env()` を介して永続化できます(元のファイルの行順とコメントは保持されます)。`MODEL_NAME` や `ZHIPU_API_KEY` を変更すると、次回のチャット時に `LLMClient` インスタンスが自動的に再構築されます。

## プロジェクト構成

```text
TRPG_Agent/
├── main.py              # uvicorn エントリポイント
├── app.py               # FastAPI ルート、SSE エンドポイント、JSON API
├── config.py            # 設定ロード
├── game_engine.py       # ゲーム状態、メッセージ履歴、判定実行
├── llm_client.py        # LangChain ChatOpenAI + 構造化出力
├── storage.py           # JSON セーブ I/O
├── env_writer.py        # .env ホットライト
├── schemas/             # Pydantic 構造化出力モデル
│   └── game_action.py
├── rules/               # ダイス、キャラクター、判定ルール
├── worlds/              # 世界観(DND、CNC)+ system prompt
├── templates/           # Jinja2 HTML テンプレート
├── static/              # CSS + JS
├── saves/               # JSON セーブデータ
├── scripts/             # 補助スクリプト(`verify_scene_features.py` によるシーン機能の E2E 検証を含む)
├── docs/                # 多言語 README + ロードマップ
├── requirements.txt
└── .env.example
```

## 開発メモ/注意事項

- 現在の Web UI は FastAPI、Jinja2、Vanilla JS、SSE を使用します
- `main.py` は uvicorn を起動し、既定で `127.0.0.1:7860` を単一ワーカー(`workers=1`)で待ち受けます
- 各ページはサーバー側の Jinja2 テンプレートでレンダリングされ、フロントエンドのビルドはありません
- チャットストリーミングは `/api/chat/stream` を使用します
- セーブデータは `saves/` 配下の JSON ファイルです
- 利用可能な世界観は DND と CNC です
- モデルやルール設定は、設定ページまたは `.env` で調整してください
- 複数のブラウザタブは単一の `GameEngine` インスタンスを共有します(ローカルシングルユーザー設計)
- `llm_client.py` に残されている `_LEGACY_*` 正規表現定数、`strip_tags()`、`parse_quick_actions()` は、旧バージョンのタグ形式セーブとの後方互換性のためにのみ保持されています

## ロードマップリンク

- [中文路线图](./roadmap_zh.md)
- [English Roadmap](./roadmap_en.md)
