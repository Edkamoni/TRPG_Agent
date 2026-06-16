import os
import sys
import json
import time
import random
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.requests import Request
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from game_engine import GameEngine
from llm_client import LLMClient
from worlds import WORLD_REGISTRY
from config import Config, ENV_PATH
from rules.character import PRESET_CHARACTERS
from rules.events import ATTRIBUTE_CN
from storage import list_saves
from env_writer import upsert_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine = GameEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not Config.ZHIPU_API_KEY:
        logger.warning("ZHIPU_API_KEY is empty; LLM calls will fail.")

    os.makedirs(Config.SAVE_DIR, exist_ok=True)

    if not WORLD_REGISTRY:
        logger.warning("WORLD_REGISTRY is empty; no worlds available.")

    logger.info(f"TRPG running at http://127.0.0.1:7860/main")
    yield


BASE_DIR = Path(__file__).parent

app = FastAPI(title="TRPG Agent", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


class WorldSelectRequest(BaseModel):
    world_id: str


@app.get("/api/game-state")
async def api_game_state():
    """返回当前游戏流程状态，供前端导航判断。"""
    return {
        "phase": engine.phase,
        "has_world": engine.has_world,
        "has_character": engine.has_character,
    }


@app.get("/api/worlds")
async def list_worlds():
    return [
        {
            "id": w.world_id,
            "name": w.world_name,
            "emoji": w.world_emoji,
            "description": w.description,
            "tone": w.tone,
        }
        for w in WORLD_REGISTRY.values()
    ]


@app.post("/api/world/select")
async def select_world(body: WorldSelectRequest):
    if body.world_id not in WORLD_REGISTRY:
        return JSONResponse(status_code=400, content={"error": "unknown world"})
    if body.world_id == "cnc":
        return JSONResponse(status_code=400, content={"error": "暂不支持"})

    engine.switch_world(body.world_id)
    return {
        "ok": True,
        "world_id": body.world_id,
        "world_name": engine.world.world_name,
    }


@app.get("/api/scene")
async def api_scene():
    if not engine.has_character or not engine.has_world:
        return {"has_character": False}
    return {
        "has_character": True,
        "scene_name": engine.character.current_scene or "",
        "world_id": engine.world_id or "",
        "world_name": engine.world.world_name if engine.world else "",
        "world_emoji": getattr(engine.world, "world_emoji", ""),
        "hp": engine.character.hp,
        "hp_max": engine.character.max_hp,
        "level": engine.character.level,
        "inspiration": engine.character.inspiration,
        "breakthrough": engine.character.breakthrough_count,
        "inventory": engine.character.inventory,
    }


@app.get("/api/history")
async def api_history():
    messages = []
    quick_actions = list(engine.last_quick_actions)
    for msg in engine.messages:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        if role == "assistant":
            actions = LLMClient.parse_quick_actions(content)
            if actions:
                quick_actions = actions
            content = LLMClient.strip_tags(content)
        messages.append({"role": role, "content": content})
    return {"messages": messages, "actions": quick_actions}


def _nav_state() -> dict:
    """返回导航栏所需的游戏流程状态。"""
    phase = engine.phase
    return {
        "phase": phase,
        "has_world": engine.has_world,
        "has_character": engine.has_character,
    }


def _redirect_for_phase(target: str):
    """根据当前阶段判断 target 页面是否可访问，否则返回正确页面的重定向。"""
    phase = engine.phase
    # phase → 允许的页面
    allowed = {
        "no_world": {"main", "settings", "settings_model", "settings_rules"},
        "save_menu": {"main", "save", "createCharacter", "settings", "settings_model", "settings_rules"},
        "in_game": {"game", "settings", "settings_model", "settings_rules"},
    }
    if target in allowed.get(phase, set()):
        return None  # 允许访问
    # 返回该阶段应去的页面
    dest = {"no_world": "/main", "save_menu": "/save", "in_game": "/game"}.get(phase, "/main")
    return RedirectResponse(dest, status_code=302)


@app.get("/")
async def root():
    """智能重定向：根据当前阶段跳转到正确页面。"""
    dest = {"no_world": "/main", "save_menu": "/save", "in_game": "/game"}.get(engine.phase, "/main")
    return RedirectResponse(dest, status_code=302)


@app.get("/main")
async def main_page(request: Request):
    blocked = _redirect_for_phase("main")
    if blocked:
        return blocked
    return templates.TemplateResponse(request, "main.html", {
        "current_page": "main", "nav_state": _nav_state(),
    })


@app.get("/save")
async def save_page(request: Request):
    blocked = _redirect_for_phase("save")
    if blocked:
        return blocked
    return templates.TemplateResponse(request, "save.html", {
        "current_page": "save", "nav_state": _nav_state(),
    })


@app.get("/createCharacter")
async def character_page(request: Request):
    blocked = _redirect_for_phase("createCharacter")
    if blocked:
        return blocked
    return templates.TemplateResponse(request, "character.html", {
        "current_page": "createCharacter", "nav_state": _nav_state(),
    })


@app.get("/game")
async def game_page(request: Request):
    blocked = _redirect_for_phase("game")
    if blocked:
        return blocked
    return templates.TemplateResponse(request, "game.html", {
        "current_page": "game", "nav_state": _nav_state(),
    })


# ---------- 设置页面（任何阶段均可访问） ----------

@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request, "settings.html",
        {"current_page": "settings", "nav_state": _nav_state()},
    )


@app.get("/settings/model")
async def settings_model_page(request: Request):
    return templates.TemplateResponse(
        request, "settings_model.html",
        {"current_page": "settings", "nav_state": _nav_state()},
    )


@app.get("/settings/rules")
async def settings_rules_page(request: Request):
    return templates.TemplateResponse(
        request, "settings_rules.html",
        {"current_page": "settings", "nav_state": _nav_state()},
    )


@app.post("/api/session/exit")
async def api_session_exit():
    """退出当前游戏会话，重置到世界选择阶段。"""
    engine.reset_session()
    return {"ok": True}


class CreateCharacterRequest(BaseModel):
    name: str
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    background: str = ""


@app.get("/api/character/presets")
async def get_character_presets():
    return PRESET_CHARACTERS


@app.post("/api/character/create")
async def create_character(req: CreateCharacterRequest):
    if not req.name.strip():
        return JSONResponse(status_code=400, content={"ok": False, "error": "Character name cannot be empty"})

    attrs = [req.strength, req.dexterity, req.constitution, req.intelligence, req.wisdom, req.charisma]
    if any(value < 0 or value > 20 for value in attrs):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Attributes must be between 0 and 20"})

    if sum(attrs) != 80:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Attribute total must be 80"})

    engine.create_character(
        name=req.name,
        strength=req.strength,
        dexterity=req.dexterity,
        constitution=req.constitution,
        intelligence=req.intelligence,
        wisdom=req.wisdom,
        charisma=req.charisma,
        background=req.background,
    )
    return {"ok": True, "character": engine.character.to_dict()}


@app.get("/api/character")
async def get_character():
    if engine.has_character:
        wid = engine.world_id or "dnd"
        return {
            "has_character": True,
            "character": engine.character.to_dict(),
            "card_html": engine.character.card_html(wid),
        }
    return {"has_character": False}


class LoadSaveBody(BaseModel):
    filepath: str


@app.get("/api/saves")
async def api_list_saves():
    return list_saves()


@app.post("/api/save/load")
async def api_load_save(body: LoadSaveBody):
    filepath = body.filepath
    if not os.path.abspath(filepath).startswith(os.path.abspath(Config.SAVE_DIR)):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    try:
        message = engine.load(filepath)
        return {
            "ok": True,
            "message": message,
            "character": engine.character.to_dict(),
            "world_id": engine.world_id,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/save")
async def api_save():
    if not engine.has_character:
        return JSONResponse({"error": "no character to save"}, status_code=400)
    try:
        filepath = engine.save()
        return {"ok": True, "filepath": filepath}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/session/exit")
async def api_session_exit():
    """退出当前游戏会话，重置到世界选择阶段。"""
    engine.reset_session()
    return {"ok": True}


SCENARIO_POOLS = {
    "dnd": [
        {"title": "失落矿坑的回声", "prompt": "你收到一封染血的求救信，指向北境山脉中一座重新传出敲击声的废弃矿坑。"},
        {"title": "雾港失踪案", "prompt": "港口城市连续有人在浓雾中失踪，唯一线索是一枚带有海盐味的黑色鳞片。"},
        {"title": "被诅咒的丰收节", "prompt": "丰收节前夜，村庄里的稻草人开始移动，田地深处传来孩子的笑声。"},
        {"title": "龙墓下的契约", "prompt": "一名贵族雇你寻找祖先遗失的契约，而契约据说埋在古龙墓穴的王座之下。"},
        {"title": "银月塔的求援", "prompt": "银月塔突然升起蓝色火焰，塔中法师只传出一句话：不要相信我的影子。"},
    ],
    "cnc": [
        {"title": "地铁末班车修仙事件", "prompt": "你坐上末班地铁，却发现下一站播报成了昆仑墟，车厢广告开始讲授吐纳法。"},
        {"title": "外卖订单：送到妖王洞", "prompt": "一笔高额跑腿订单要求你把奶茶送到城市地下三层的妖王洞，还备注少冰七分糖。"},
        {"title": "小区广场舞法阵", "prompt": "小区大妈们的广场舞突然引动灵气潮汐，物业请你查查音响里到底封了什么。"},
        {"title": "网红古井直播翻车", "prompt": "一场探灵直播中断后，主播账号仍在自动更新，画面里出现了你的背影。"},
        {"title": "便利店零点鬼促销", "prompt": "凌晨便利店推出买一送一灵异促销，收银员坚持说你昨天已经来过一次。"},
    ],
}


@app.get("/api/scenarios")
async def api_scenarios():
    wid = engine.world_id or "dnd"
    pool = SCENARIO_POOLS.get(wid) or SCENARIO_POOLS["dnd"]
    count = random.randint(1, min(3, len(pool)))
    return {"scenarios": random.sample(pool, count)}


class ChatStreamBody(BaseModel):
    message: str


class CheckResolveBody(BaseModel):
    roll: int
    use_inspiration: bool = False
    inspiration_roll: int = 0


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def api_chat_stream(body: ChatStreamBody, request: Request):
    if not engine.has_character:
        return JSONResponse({"error": "请先创建角色"}, status_code=400)

    message = (body.message or "").strip()
    if not message:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    async def event_generator():
        try:
            sync_gen = engine.process_input(message)
            async for chunk in iterate_in_threadpool(sync_gen):
                if chunk:
                    yield _sse("chunk", {"text": chunk})

                if await request.is_disconnected():
                    # Drain remaining chunks without emitting, per full-generation policy
                    pass

            action = engine.last_game_action

            # Scene change detection (after streaming, before check/actions)
            if action and action.scene and action.scene.strip() != engine.character.current_scene:
                yield _sse("scene_change", {
                    "scene": action.scene,
                    "summary": action.scene_summary or "",
                })

            if action and action.check:
                engine.set_pending_check(action.check.attribute, action.check.dc)
                yield _sse("check_request", {
                    "attribute": action.check.attribute,
                    "dc": action.check.dc,
                    "attribute_label": ATTRIBUTE_CN.get(action.check.attribute, action.check.attribute),
                    "modifier": engine.character.get_modifier(action.check.attribute),
                })
                # 跳过 follow-up LLM 调用，等待前端骰子结果
            else:
                actions = action.quick_actions if action else []
                engine.last_quick_actions = actions
                yield _sse("actions", {"actions": actions})
                yield _sse("done", {})
        except Exception as e:
            logger.exception("chat stream error")
            yield _sse("error", {"msg": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/check/resolve")
async def api_check_resolve(body: CheckResolveBody, request: Request):
    """前端骰子结果提交，执行检定并获取 AI 后续叙述。"""
    if not engine.has_character:
        return JSONResponse({"error": "请先创建角色"}, status_code=400)
    if engine.pending_check is None:
        return JSONResponse({"error": "没有待处理的检定"}, status_code=400)

    async def event_generator():
        try:
            llm = engine._ensure_llm()

            result, desc = engine.resolve_check(
                body.roll,
                use_inspiration=body.use_inspiration,
                inspiration_roll=body.inspiration_roll,
            )
            yield _sse("check", {
                "description": desc,
                "success": bool(result.success),
            })

            check_msg = f"[Check result: {desc}]"
            engine.messages.append({"role": "user", "content": check_msg})

            system_prompt = engine._build_system_prompt()

            action = llm.chat_structured(system_prompt, engine.messages)
            yield _sse("chunk", {"text": action.narrative})

            engine.messages.append({"role": "assistant", "content": action.narrative})
            engine._process_ai_output(action)
            engine.last_game_action = action
            engine.last_quick_actions = action.quick_actions
            yield _sse("actions", {"actions": action.quick_actions})

            # 隐藏经验增长
            pending_exp = engine._pending_exp
            engine._pending_exp = None
            if pending_exp:
                amount, leveled = pending_exp
                yield _sse("exp", {"amount": amount, "leveled": leveled})

            engine.pending_check = None
            yield _sse("done", {})
        except Exception as e:
            logger.exception("check resolve error")
            yield _sse("error", {"msg": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/check/skip")
async def api_check_skip():
    """跳过当前检定，直接继续对话。"""
    if engine.pending_check is None:
        return JSONResponse({"error": "没有待处理的检定"}, status_code=400)
    engine.pending_check = None
    engine._pending_exp = None
    return {"ok": True}


# ============================================================
# 设置 API：模型配置 + 游戏规则参数
# ============================================================

# 模型名预设下拉项；用户也可直接在输入框里写自定义名
MODEL_PRESETS = ["glm-4", "glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4-long"]

# 模型配置参数的合法范围（同时用于校验与前端 hint）
MODEL_FIELD_BOUNDS = {
    "temperature": (0.0, 2.0),
    "max_tokens": (128, 8192),
    "max_history": (1, 100),
    "max_retries": (1, 10),
    "stream_timeout": (5, 600),
}

# 规则参数的合法范围
RULES_FIELD_BOUNDS = {
    "initial_attribute_points": (0, 60),
    "exp_threshold": (10, 1000),
    "scene_turn_limit": (5, 30),
}


def _mask_api_key(key: str) -> str:
    """脱敏 API Key：前 4 + 中间星号 + 后 4。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


class ModelConfigUpdate(BaseModel):
    api_key: Optional[str] = Field(default=None, description="留空表示不修改")
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_history: Optional[int] = None
    max_retries: Optional[int] = None
    stream_timeout: Optional[int] = None
    persist_to_env: bool = False


class ModelTestRequest(BaseModel):
    api_key: Optional[str] = None
    model_name: Optional[str] = None


class RulesConfigUpdate(BaseModel):
    initial_attribute_points: Optional[int] = None
    exp_threshold: Optional[int] = None
    scene_turn_limit: Optional[int] = None
    persist_to_env: bool = False


def _validate_range(field: str, value, bounds: dict) -> Optional[str]:
    """范围校验。返回错误信息（None 表示通过）。"""
    if value is None:
        return None
    lo, hi = bounds[field]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{field} 必须为数字"
    if v < lo or v > hi:
        return f"{field} 必须在 [{lo}, {hi}] 范围内"
    return None


@app.get("/api/settings/model")
async def get_model_settings():
    return {
        "provider": "zhipuai",
        "api_key_masked": _mask_api_key(Config.ZHIPU_API_KEY),
        "api_key_present": bool(Config.ZHIPU_API_KEY),
        "model_name": Config.MODEL_NAME,
        "model_presets": MODEL_PRESETS,
        "temperature": Config.TEMPERATURE,
        "max_tokens": Config.MAX_TOKENS,
        "max_history": Config.MAX_HISTORY,
        "max_retries": Config.MAX_RETRIES,
        "stream_timeout": Config.STREAM_TIMEOUT,
        "bounds": MODEL_FIELD_BOUNDS,
        "env_file_path": str(ENV_PATH),
    }


@app.post("/api/settings/model")
async def update_model_settings(body: ModelConfigUpdate):
    # 1) 范围校验
    errors = {}
    for field in ("temperature", "max_tokens", "max_history", "max_retries", "stream_timeout"):
        msg = _validate_range(field, getattr(body, field), MODEL_FIELD_BOUNDS)
        if msg:
            errors[field] = msg
    if body.model_name is not None and not body.model_name.strip():
        errors["model_name"] = "模型名称不能为空"
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    # 2) 应用到 Config 类属性
    applied = {}
    llm_reinit_needed = False

    if body.api_key is not None and body.api_key != "":
        Config.ZHIPU_API_KEY = body.api_key
        applied["api_key"] = "<已更新>"
        llm_reinit_needed = True

    if body.model_name is not None:
        new_name = body.model_name.strip()
        if new_name != Config.MODEL_NAME:
            Config.MODEL_NAME = new_name
            llm_reinit_needed = True
        applied["model_name"] = Config.MODEL_NAME

    if body.temperature is not None:
        Config.TEMPERATURE = float(body.temperature)
        applied["temperature"] = Config.TEMPERATURE
    if body.max_tokens is not None:
        Config.MAX_TOKENS = int(body.max_tokens)
        applied["max_tokens"] = Config.MAX_TOKENS
    if body.max_history is not None:
        Config.MAX_HISTORY = int(body.max_history)
        applied["max_history"] = Config.MAX_HISTORY
    if body.max_retries is not None:
        Config.MAX_RETRIES = int(body.max_retries)
        applied["max_retries"] = Config.MAX_RETRIES
    if body.stream_timeout is not None:
        Config.STREAM_TIMEOUT = int(body.stream_timeout)
        applied["stream_timeout"] = Config.STREAM_TIMEOUT

    # 3) 模型名 / Key 变化 → 重置 LLM 实例，下一次 chat 重建
    if llm_reinit_needed:
        engine.llm = None

    # 4) 可选持久化到 .env
    persisted = False
    if body.persist_to_env:
        env_updates = {}
        if body.api_key is not None and body.api_key != "":
            env_updates["ZHIPU_API_KEY"] = body.api_key
        if body.model_name is not None:
            env_updates["MODEL_NAME"] = body.model_name.strip()
        if body.temperature is not None:
            env_updates["TEMPERATURE"] = str(float(body.temperature))
        if body.max_tokens is not None:
            env_updates["MAX_TOKENS"] = str(int(body.max_tokens))
        if body.max_history is not None:
            env_updates["MAX_HISTORY"] = str(int(body.max_history))
        if body.max_retries is not None:
            env_updates["MAX_RETRIES"] = str(int(body.max_retries))
        if body.stream_timeout is not None:
            env_updates["STREAM_TIMEOUT"] = str(int(body.stream_timeout))
        try:
            upsert_env(ENV_PATH, env_updates)
            persisted = True
        except OSError as e:
            return JSONResponse(
                {"ok": True, "applied": applied, "llm_reinitialized": llm_reinit_needed,
                 "persisted": False, "persist_error": str(e)},
                status_code=200,
            )

    return {
        "ok": True,
        "applied": applied,
        "llm_reinitialized": llm_reinit_needed,
        "persisted": persisted,
    }


@app.post("/api/settings/model/test")
async def test_model_connection(body: ModelTestRequest):
    """用临时参数 ping 一次模型，验证 Key 与模型名可用。不修改 Config。"""
    api_key = (body.api_key or "").strip() or Config.ZHIPU_API_KEY
    model_name = (body.model_name or "").strip() or Config.MODEL_NAME

    if not api_key:
        return JSONResponse({"ok": False, "error": "API Key 为空"}, status_code=400)

    try:
        from langchain_openai import ChatOpenAI

        client = ChatOpenAI(
            openai_api_key=api_key,
            model=model_name,
            max_tokens=8,
            temperature=0.1,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
        )
        t0 = time.time()
        resp = client.invoke([{"role": "user", "content": "ping"}])
        latency_ms = int((time.time() - t0) * 1000)
        sample = (resp.content or "").strip()[:60]
        return {"ok": True, "latency_ms": latency_ms, "sample": sample, "model": model_name}
    except Exception as e:
        logger.warning("model test failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


@app.get("/api/settings/rules")
async def get_rules_settings():
    return {
        "initial_attribute_points": Config.INITIAL_ATTRIBUTE_POINTS,
        "exp_threshold": Config.EXP_THRESHOLD,
        "scene_turn_limit": Config.SCENE_TURN_LIMIT,
        "bounds": RULES_FIELD_BOUNDS,
        "env_file_path": str(ENV_PATH),
    }


@app.post("/api/settings/rules")
async def update_rules_settings(body: RulesConfigUpdate):
    errors = {}
    for field in ("initial_attribute_points", "exp_threshold", "scene_turn_limit"):
        msg = _validate_range(field, getattr(body, field), RULES_FIELD_BOUNDS)
        if msg:
            errors[field] = msg
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    applied = {}
    if body.initial_attribute_points is not None:
        Config.INITIAL_ATTRIBUTE_POINTS = int(body.initial_attribute_points)
        applied["initial_attribute_points"] = Config.INITIAL_ATTRIBUTE_POINTS
    if body.exp_threshold is not None:
        Config.EXP_THRESHOLD = int(body.exp_threshold)
        applied["exp_threshold"] = Config.EXP_THRESHOLD
    if body.scene_turn_limit is not None:
        Config.SCENE_TURN_LIMIT = int(body.scene_turn_limit)
        applied["scene_turn_limit"] = Config.SCENE_TURN_LIMIT

    persisted = False
    if body.persist_to_env:
        env_updates = {}
        if body.initial_attribute_points is not None:
            env_updates["INITIAL_ATTRIBUTE_POINTS"] = str(int(body.initial_attribute_points))
        if body.exp_threshold is not None:
            env_updates["EXP_THRESHOLD"] = str(int(body.exp_threshold))
        if body.scene_turn_limit is not None:
            env_updates["SCENE_TURN_LIMIT"] = str(int(body.scene_turn_limit))
        try:
            upsert_env(ENV_PATH, env_updates)
            persisted = True
        except OSError as e:
            return JSONResponse(
                {"ok": True, "applied": applied, "persisted": False, "persist_error": str(e)},
                status_code=200,
            )

    return {"ok": True, "applied": applied, "persisted": persisted}

