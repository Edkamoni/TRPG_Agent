from __future__ import annotations

import logging
import random
from typing import Dict, Generator, List, Optional, Tuple

from config import Config
from llm_client import LLMClient
from rules.character import Character
from rules.events import make_check_with_roll, CheckResult, ATTRIBUTE_CN
from schemas.game_action import GameAction, SceneSummary
from storage import save_game, load_game
from worlds import get_world, WORLD_REGISTRY
from worlds.base import WorldBase

logger = logging.getLogger(__name__)


class GameEngine:
    def __init__(self):
        self.character: Optional[Character] = None
        self.world_id: Optional[str] = None
        self.world: Optional[WorldBase] = None
        self.messages: List[Dict[str, str]] = []
        self.last_quick_actions: List[str] = []
        self.last_game_action: Optional[GameAction] = None
        self.llm: Optional[LLMClient] = None
        self._initialized = False
        self.pending_check: Optional[Dict] = None
        self._pending_exp: Optional[Tuple[int, bool]] = None
        self.scene_turns: int = 0
        self.scene_start_idx: int = 0
        self.scene_history: List[SceneSummary] = []
        self._pending_summary_injection: bool = False

    def _ensure_llm(self) -> LLMClient:
        if self.llm is None:
            self.llm = LLMClient()
        return self.llm

    def set_pending_check(self, attribute: str, dc: int) -> None:
        """记录待处理的检定请求，等待前端骰子结果。"""
        modifier_value = self.character.get_modifier(attribute) if self.has_character else 0
        self.pending_check = {
            "attribute": attribute,
            "dc": dc,
            "attribute_label": ATTRIBUTE_CN.get(attribute, attribute),
            "modifier": modifier_value,
        }

    def resolve_check(
        self,
        roll_value: int,
        use_inspiration: bool = False,
        inspiration_roll: int = 0,
    ) -> Tuple[CheckResult, str]:
        """
        使用前端传来的骰子结果执行检定。
        调用 make_check_with_roll()，处理世界特效，返回 (CheckResult, narrative_desc)。
        """
        if not self.has_character:
            raise ValueError("No character to perform check")
        if self.pending_check is None:
            raise ValueError("No pending check to resolve")
        if self.world is None:
            raise ValueError("No world selected")

        attr = self.pending_check["attribute"]
        dc = self.pending_check["dc"]

        result = make_check_with_roll(
            self.character, attr, dc,
            roll_value=roll_value,
            use_inspiration=use_inspiration,
            inspiration_roll=inspiration_roll,
        )

        if result.is_critical_success:
            desc = self.world.describe_critical_success(attr)
            effect = self.world.on_critical_success(self.character)
            if effect == "breakthrough":
                desc += "\n🌟 修仙突破触发！即将获得属性提升！"
            elif effect:
                desc += f"\n{effect}"
        elif result.is_critical_failure:
            desc = self.world.describe_critical_failure(attr)
            effect = self.world.on_critical_failure(self.character)
            if effect:
                desc += f"\n{effect}"
        elif result.success:
            desc = self.world.describe_check_success(attr, result.total, dc)
        else:
            desc = self.world.describe_check_failure(attr, result.total, dc)

        full_desc = f"{result.description}\n{desc}"
        return result, full_desc

    def hidden_exp_gain(self) -> Optional[Tuple[int, bool]]:
        """
        隐藏经验获取：每次交互 30% 概率获得 5-25 经验。
        返回 (amount, leveled) 或 None。
        """
        if not self.has_character:
            return None
        if random.random() < 0.3:
            amount = random.randint(5, 25)
            leveled = self.character.gain_exp(amount)
            logger.info(f"Hidden exp gained: {amount}, leveled up: {leveled}")
            return (amount, leveled)
        return None

    @property
    def has_character(self) -> bool:
        return self.character is not None and self.character.name != ""

    def create_character(
        self,
        name: str,
        strength: int = 10,
        dexterity: int = 10,
        constitution: int = 10,
        intelligence: int = 10,
        wisdom: int = 10,
        charisma: int = 10,
        background: str = "",
    ) -> Character:
        """Create a new character with given attributes."""
        c = Character(name=name, background=background)
        c.attribute_points = 0
        c.strength = strength
        c.dexterity = dexterity
        c.constitution = constitution
        c.intelligence = intelligence
        c.wisdom = wisdom
        c.charisma = charisma

        self.character = c
        self.messages = []
        self.last_quick_actions = []
        self.last_game_action = None
        self._initialized = False
        self.pending_check = None
        self._pending_exp = None
        self.scene_turns = 0
        self.scene_start_idx = 0
        self.scene_history = []
        self._pending_summary_injection = False
        return c

    @property
    def has_world(self) -> bool:
        return self.world is not None

    @property
    def phase(self) -> str:
        """返回当前游戏流程阶段：no_world / save_menu / in_game"""
        if not self.has_world:
            return "no_world"
        if not self.has_character:
            return "save_menu"
        return "in_game"

    def reset_session(self) -> None:
        """重置游戏会话，回到世界选择阶段。"""
        self.character = None
        self.world_id = None
        self.world = None
        self.messages = []
        self.last_quick_actions = []
        self.last_game_action = None
        self._initialized = False
        self.pending_check = None
        self._pending_exp = None
        self.scene_turns = 0
        self.scene_start_idx = 0
        self.scene_history = []
        self._pending_summary_injection = False

    def switch_world(self, world_id: str) -> str:
        """Switch world, keep character, clear conversation."""
        if world_id not in WORLD_REGISTRY:
            return f"Unknown world: {world_id}"

        self.world_id = world_id
        self.world = get_world(world_id)
        self.messages = []
        self.last_quick_actions = []
        self.last_game_action = None
        self._initialized = False
        self.pending_check = None
        self._pending_exp = None
        self.scene_turns = 0
        self.scene_start_idx = 0
        self.scene_history = []
        self._pending_summary_injection = False
        return f"Switched to {self.world.world_name}"

    def _build_system_prompt(self) -> str:
        if self.world is None:
            return ""
        if not self.has_character:
            prompt = self.world.get_system_prompt(Character())
        else:
            prompt = self.world.get_system_prompt(self.character)
        prompt += f"""
【场景管理】
- 每个场景大约持续 {Config.SCENE_TURN_LIMIT} 轮交互
- 当前场景已进行 {self.scene_turns}/{Config.SCENE_TURN_LIMIT} 轮
- 当场景自然收尾或达到轮次上限时，请在 narrative 中自然过渡，设置新的 scene 字段，并在 scene_summary 中提供本场景 100-200 字摘要
- 摘要应包含：关键事件、重要 NPC 互动、获得的物品或线索
- 不要突兀地切场，过渡要符合叙事逻辑
"""
        if self.scene_turns >= Config.SCENE_TURN_LIMIT and self.scene_turns >= 3:
            prompt += (
                "\n⚠️ 当前场景已达到轮次上限，请在本次回复中完成场景收尾，"
                "自然过渡到新场景，并务必填写 scene 和 scene_summary 字段。\n"
            )
        return prompt

    def _trim_messages(self) -> None:
        """场景感知的消息裁剪：保留当前场景完整消息，旧场景替换为摘要系统消息。"""
        max_rounds = Config.MAX_HISTORY

        # 构建旧场景摘要消息
        summary_msgs: List[Dict[str, str]] = []
        if self.scene_start_idx > 0 and self.scene_history:
            for s in self.scene_history:
                summary_msgs.append({
                    "role": "system",
                    "content": f"[场景摘要: {s.scene_name}] {s.summary}",
                })

        # 保留当前场景消息
        current_scene_msgs = self.messages[self.scene_start_idx:]

        # 合并：摘要 + 当前场景
        self.messages = summary_msgs + current_scene_msgs
        self.scene_start_idx = len(summary_msgs)

        # 安全兜底：如果当前场景消息过多，按 MAX_HISTORY 裁剪
        if len(self.messages) > max_rounds * 2:
            # 保留摘要消息 + 最近的当前场景消息
            keep_from = len(self.messages) - (max_rounds * 2)
            if keep_from > len(summary_msgs):
                self.messages = summary_msgs + self.messages[keep_from:]
            else:
                self.messages = self.messages[-(max_rounds * 2):]
            self.scene_start_idx = len(summary_msgs)

    def _init_game(self) -> None:
        if self._initialized:
            return
        self._initialized = True

    def _restore_quick_actions(self) -> None:
        self.last_quick_actions = []
        for msg in self.messages:
            if msg.get("role") != "assistant":
                continue
            actions = LLMClient.parse_quick_actions(msg.get("content", ""))
            if actions:
                self.last_quick_actions = actions

    def process_input(self, user_input: str) -> Generator[str, None, None]:
        """
        Process user input and yield response chunks.
        流式输出纯文本 → 完成后 chat_structured() 获取 GameAction → 处理游戏效果。
        包含场景回合追踪、摘要注入、场景切换检测。
        """
        if not self.has_character:
            yield "⚠️ Please create a character first!"
            return
        if self.world is None:
            yield "⚠️ No world selected!"
            return

        self._init_game()

        llm = self._ensure_llm()

        # Step 1: 注入待处理的场景摘要（来自存档加载）
        if self._pending_summary_injection:
            current_scene = self.character.current_scene or ""
            relevant = llm.filter_relevant_summaries(current_scene, self.scene_history)
            for s in relevant:
                self.messages.insert(self.scene_start_idx, {
                    "role": "system",
                    "content": f"[场景摘要: {s.scene_name}] {s.summary}",
                })
                self.scene_start_idx += 1
            self._pending_summary_injection = False

        # Step 2: 添加用户消息
        self.messages.append({"role": "user", "content": user_input})
        self._trim_messages()

        # Step 3: 场景回合计数
        self.scene_turns += 1

        # Step 4: 构建系统提示词（含场景回合信息 + 强制收尾指令）
        system_prompt = self._build_system_prompt()

        # Step 5: 流式输出纯文本
        full_response = ""
        try:
            for chunk in llm.chat_stream(system_prompt, self.messages):
                full_response += chunk
                yield chunk
        except RuntimeError as e:
            error_msg = f"\n\n⚠️ AI service error: {e}"
            yield error_msg
            full_response += error_msg

        # Step 6: 结构化解析，获取 GameAction
        try:
            action = llm.chat_structured(system_prompt, self.messages)
        except Exception as e:
            logger.warning(f"chat_structured failed: {e}, falling back to raw text")
            # 回退：创建仅含 narrative 的 GameAction
            action = GameAction(narrative=full_response)

        # Step 7: 存入 messages 的是干净的 narrative（不含标签）
        self.messages.append({"role": "assistant", "content": action.narrative})

        # Step 8: 记录旧场景名（处理前），再处理 AI 输出
        old_scene = self.character.current_scene if self.has_character else ""

        self._process_ai_output(action)
        self.last_game_action = action
        self.last_quick_actions = action.quick_actions
        self._pending_exp = self.hidden_exp_gain()

        # Step 9: 检测场景切换
        new_scene = action.scene.strip() if action.scene else ""
        scene_changed = (
            (bool(new_scene) and new_scene != old_scene)
            or self.scene_turns >= Config.SCENE_TURN_LIMIT
        )

        if scene_changed and self.scene_turns >= 3:
            summary_text = (action.scene_summary or "").strip()
            scene_name = new_scene or old_scene or "未知场景"
            summary = SceneSummary(
                scene_name=scene_name,
                summary=summary_text,
                ended_at_turn=self.scene_turns,
            )
            self.scene_history.append(summary)
            self.scene_turns = 0
            self.scene_start_idx = len(self.messages)

    def _update_scene(self, text: str) -> None:
        """Extract scene description from AI output and update character.current_scene."""
        import re
        scene_match = re.search(r"【场景[：:]\s*(.+?)】", text)
        if not scene_match:
            scene_match = re.search(r"\[场景[：:]\s*(.+?)\]", text)
        if scene_match:
            self.character.current_scene = scene_match.group(1).strip()

    def _process_ai_output(self, action: GameAction) -> None:
        """从 GameAction 结构化字段处理 exp、inspiration、breakthrough、scene。"""
        if not self.has_character:
            return

        # 场景更新：优先使用 GameAction.scene，回退到正则解析
        if action.scene:
            self.character.current_scene = action.scene.strip()
        else:
            self._update_scene(action.narrative)

        # 经验奖励
        if action.exp_reward:
            leveled = self.character.gain_exp(action.exp_reward)
            logger.info(f"Character gained {action.exp_reward} exp. Leveled up: {leveled}")

        # 激励骰
        if action.inspiration:
            self.character.inspiration += action.inspiration
            logger.info(f"Character gained {action.inspiration} inspiration dice")

        # 突破
        if action.breakthrough:
            attr = action.breakthrough
            if hasattr(self.character, attr):
                current = getattr(self.character, attr)
                setattr(self.character, attr, current + 2)
                logger.info(f"Breakthrough! {attr} +2")

    def save(self) -> str:
        """Save current game. Returns file path."""
        if not self.has_character:
            raise ValueError("No character to save")
        wid = self.world_id or "dnd"
        return save_game(self.character, wid, self.messages, self.scene_history)

    def load(self, filepath: str) -> str:
        """Load game from file. Returns status message."""
        data = load_game(filepath)
        self.character = data["character"]
        self.world_id = data.get("world_id") or "dnd"
        self.world = get_world(self.world_id)
        self.messages = data.get("messages", [])
        self._restore_quick_actions()
        self._initialized = True
        self.pending_check = None
        self._pending_exp = None
        self.scene_turns = 0
        self.scene_start_idx = len(self.messages)
        # 恢复场景摘要历史
        raw_summaries = data.get("scene_summaries", [])
        self.scene_history = [
            SceneSummary(**s) if isinstance(s, dict) else s
            for s in raw_summaries
        ]
        self._pending_summary_injection = bool(self.scene_history)
        return f"Loaded: {self.character.name} (Lv.{self.character.level}) in {self.world.world_name}"
