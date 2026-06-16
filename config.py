import logging
import os
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"


class Config:
    # ---- LLM 相关 ----
    ZHIPU_API_KEY: str = os.getenv("ZHIPU_API_KEY", "")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "glm-4")
    MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "20"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.85"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2048"))
    STREAM_TIMEOUT: int = int(os.getenv("STREAM_TIMEOUT", "60"))

    # ---- 存档 ----
    SAVE_DIR: str = str(BASE_DIR / os.getenv("SAVE_DIR", "saves"))

    # ---- 游戏规则 ----
    EXP_THRESHOLD: int = int(os.getenv("EXP_THRESHOLD", "100"))
    INITIAL_ATTRIBUTE_POINTS: int = int(os.getenv("INITIAL_ATTRIBUTE_POINTS", "20"))
    SCENE_TURN_LIMIT: int = int(os.getenv("SCENE_TURN_LIMIT", "10"))

    @classmethod
    def _validate_scene_turn_limit(cls) -> None:
        val = cls.SCENE_TURN_LIMIT
        if val < 5 or val > 30:
            logger.warning(
                "SCENE_TURN_LIMIT=%d is out of range [5, 30], falling back to 10", val
            )
            cls.SCENE_TURN_LIMIT = 10

    # ---- DC 默认参考值（当前未在代码路径中读取，仅供后续扩展） ----
    DC_EASY: int = 10
    DC_MEDIUM: int = 15
    DC_HARD: int = 20
    DC_EXTREME: int = 25


# 导入时触发范围校验
Config._validate_scene_turn_limit()
