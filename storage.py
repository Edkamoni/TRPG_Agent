from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import Config
from rules.character import Character
from schemas.game_action import SceneSummary


def _ensure_save_dir() -> None:
    os.makedirs(Config.SAVE_DIR, exist_ok=True)


def save_game(
    character: Character,
    world_id: str,
    messages: List[Dict[str, str]],
    scene_summaries: Optional[List[SceneSummary]] = None,
) -> str:
    """Save game state to JSON file. Returns file path."""
    _ensure_save_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = character.name.replace(" ", "_") or "unnamed"
    filename = f"{safe_name}_{timestamp}.json"
    filepath = os.path.join(Config.SAVE_DIR, filename)

    data = {
        "character": character.to_dict(),
        "world_id": world_id,
        "messages": messages,
        "saved_at": datetime.now().isoformat(),
    }

    if scene_summaries is not None:
        data["scene_summaries"] = [s.model_dump() for s in scene_summaries]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


def load_game(filepath: str) -> Dict[str, Any]:
    """Load game state from JSON file. Returns dict with character, world_id, messages, scene_summaries."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["character"] = Character.from_dict(data["character"])
    data["scene_summaries"] = data.get("scene_summaries", [])
    return data


def list_saves() -> List[Dict[str, Any]]:
    """List all save files with metadata."""
    _ensure_save_dir()
    saves = []
    save_dir = Path(Config.SAVE_DIR)

    for fp in sorted(save_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            saves.append({
                "filepath": str(fp),
                "filename": fp.name,
                "character_name": data.get("character", {}).get("name", "???"),
                "level": data.get("character", {}).get("level", 1),
                "world_id": data.get("world_id", "?"),
                "saved_at": data.get("saved_at", "?"),
            })
        except (json.JSONDecodeError, KeyError):
            continue

    return saves
