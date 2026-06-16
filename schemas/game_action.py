from typing import List, Optional

from pydantic import BaseModel, Field


class CheckRequest(BaseModel):
    attribute: str = Field(description="属性英文名: strength/dexterity/constitution/intelligence/wisdom/charisma")
    dc: int = Field(description="难度等级，通常 10-25")


class GameAction(BaseModel):
    narrative: str = Field(description="DM 叙事文本，不含任何标签或元数据")
    check: Optional[CheckRequest] = Field(default=None)
    exp_reward: Optional[int] = Field(default=None)
    inspiration: Optional[int] = Field(default=None)
    breakthrough: Optional[str] = Field(default=None)
    quick_actions: List[str] = Field(default_factory=list)
    scene: Optional[str] = Field(default=None)
    scene_summary: Optional[str] = Field(default=None, description="场景结束时由 AI 提供的 100-200 字摘要，平时为 None")


class SceneSummary(BaseModel):
    scene_name: str = Field(description="场景名称")
    summary: str = Field(description="场景摘要内容")
    ended_at_turn: Optional[int] = Field(default=None, description="场景结束时的回合数")
