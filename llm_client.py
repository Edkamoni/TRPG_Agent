from __future__ import annotations

import logging
import re
import time
from typing import Callable, Dict, Generator, List, TypeVar

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import Config
from schemas.game_action import GameAction, SceneSummary

logger = logging.getLogger(__name__)

# ---- _LEGACY: 正则标签解析（向后兼容） ----
PATTERN_CHECK = re.compile(r"\[(?:检定|挑战):(\w+)\s+DC=(\d+)\]")
PATTERN_EXP = re.compile(r"\[经验:(\d+)\]")
PATTERN_INSPIRATION = re.compile(r"\[激励骰:(\d+)\]")
PATTERN_BREAKTHROUGH = re.compile(r"\[突破:(\w+)\]")
PATTERN_QUICK_ACTION = re.compile(r"\[快捷:(.+?)\]")

T = TypeVar("T")


def _retry_with_backoff(
    fn: Callable[..., T],
    *args,
    max_retries: int | None = None,
    **kwargs,
) -> T:
    """自定义重试包装器：指数退避，最多 MAX_RETRIES 次。"""
    if max_retries is None:
        max_retries = Config.MAX_RETRIES
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"LLM request attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"LLM request failed after {max_retries} retries: {e}"
                )


class LLMClient:
    def __init__(self):
        if not Config.ZHIPU_API_KEY:
            raise ValueError("ZHIPU_API_KEY is not set. Please configure .env file.")
        self.client = ChatOpenAI(
            openai_api_key=Config.ZHIPU_API_KEY,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
            model=Config.MODEL_NAME,
            streaming=True,
            temperature=Config.TEMPERATURE,
            max_tokens=Config.MAX_TOKENS,
        )
        self.model = Config.MODEL_NAME

    @staticmethod
    def _convert_messages(messages: List[Dict[str, str]]) -> List[BaseMessage]:
        """将 List[Dict[str,str]] 转为 List[BaseMessage]（HumanMessage/AIMessage/SystemMessage）。"""
        converted: List[BaseMessage] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                converted.append(HumanMessage(content=content))
            elif role == "assistant":
                converted.append(AIMessage(content=content))
            elif role == "system":
                converted.append(SystemMessage(content=content))
        return converted

    def chat_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
    ) -> Generator[str, None, None]:
        """
        流式聊天补全，带重试逻辑。
        逐块产出文本。
        """
        converted = [SystemMessage(content=system_prompt)] + self._convert_messages(messages)

        for attempt in range(Config.MAX_RETRIES):
            try:
                for chunk in self.client.stream(converted):
                    if chunk.content:
                        yield chunk.content
                return
            except Exception as e:
                logger.warning(f"LLM request attempt {attempt + 1} failed: {e}")
                if attempt < Config.MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"LLM request failed after {Config.MAX_RETRIES} retries: {e}"
                    )

    def chat_structured(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
    ) -> GameAction:
        """
        非流式结构化输出调用，返回 GameAction 对象。
        使用 function_calling 模式自动回退。
        """
        structured_llm = self.client.with_structured_output(GameAction, method="function_calling")
        converted = [SystemMessage(content=system_prompt)] + self._convert_messages(messages)

        def _invoke() -> GameAction:
            return structured_llm.invoke(converted)

        return _retry_with_backoff(_invoke)

    def filter_relevant_summaries(
        self,
        current_scene: str,
        summaries: List[SceneSummary],
    ) -> List[SceneSummary]:
        """
        让 LLM 判断哪些历史场景摘要与当前场景相关。
        返回相关摘要列表；LLM 调用失败时返回空列表（安全降级）。
        """
        if not summaries:
            return []

        summary_lines = "\n".join(
            f"[{i}] {s.scene_name}: {s.summary}"
            for i, s in enumerate(summaries)
        )
        prompt = (
            f"当前场景：{current_scene}\n\n"
            f"以下是从旧场景提取的摘要列表。请判断哪些摘要与当前场景可能相关"
            f"（如 NPC、任务线索、物品）。\n"
            f"只返回相关摘要的编号列表，格式：[0, 2]\n\n"
            f"{summary_lines}"
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            result = self.chat_structured(
                system_prompt="你是一个 TRPG 游戏助手，负责判断场景摘要的相关性。",
                messages=messages,
            )
            # 尝试从 result 的 narrative 字段解析编号列表
            text = result.narrative.strip()
            # 匹配 [0, 2] 或 [0,2] 格式
            if text.startswith("[") and text.endswith("]"):
                import json
                indices = json.loads(text)
                if isinstance(indices, list):
                    return [summaries[i] for i in indices if 0 <= i < len(summaries)]
        except Exception as e:
            logger.warning(f"filter_relevant_summaries LLM 调用失败，安全降级返回空列表: {e}")

        # 第二次尝试：用普通 chat 解析纯文本回复
        try:
            text_result = ""
            for chunk in self.chat_stream(
                system_prompt="你是一个 TRPG 游戏助手，负责判断场景摘要的相关性。只返回编号列表，格式：[0, 2]",
                messages=messages,
            ):
                text_result += chunk
            text_result = text_result.strip()
            if text_result.startswith("[") and text_result.endswith("]"):
                import json
                indices = json.loads(text_result)
                if isinstance(indices, list):
                    return [summaries[i] for i in indices if 0 <= i < len(summaries)]
        except Exception as e:
            logger.warning(f"filter_relevant_summaries 回退解析也失败: {e}")

        return []

    # ---- _LEGACY: 向后兼容方法 ----

    @staticmethod
    def parse_quick_actions(text: str) -> List[str]:
        """解析 AI 输出中的快捷行动建议，如 [快捷:搜查房间里的橡木书桌]。"""
        return [m.group(1).strip() for m in PATTERN_QUICK_ACTION.finditer(text)]

    @staticmethod
    def strip_tags(text: str) -> str:
        """从显示文本中移除所有标签命令。"""
        cleaned = PATTERN_CHECK.sub("", text)
        cleaned = PATTERN_EXP.sub("", cleaned)
        cleaned = PATTERN_INSPIRATION.sub("", cleaned)
        cleaned = PATTERN_BREAKTHROUGH.sub("", cleaned)
        cleaned = PATTERN_QUICK_ACTION.sub("", cleaned)
        return cleaned.strip()



