#!/usr/bin/env python3
"""验证场景回合限制和上下文压缩功能的端到端测试脚本。

测试覆盖：
  1. 场景回合上限 - 超过上限时系统提示词包含强制收尾指令
  2. 场景切换后 scene_history 非空
  3. _trim_messages() 保留当前场景，压缩旧场景
  4. 存档包含 scene_summaries
  5. 加载旧格式存档（无 scene_summaries）不报错

用法：
  cd TRPG_Agent
  python scripts/verify_scene_features.py
"""

import json
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from game_engine import GameEngine
from schemas.game_action import GameAction, SceneSummary
from worlds.dnd import DNDWorld

passed = 0
failed = 0


def test(name: str, condition: bool, detail: str = ""):
    """记录单个测试结果。"""
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  -- {detail}")
        failed += 1


def main():
    global passed, failed

    print("=" * 60)
    print("场景回合限制 & 上下文压缩 - 端到端验证")
    print("=" * 60)

    # ================================================================
    # Test 1: 场景回合上限 - 强制收尾指令
    # ================================================================
    print("\n[Test 1] 场景回合上限 - 强制收尾指令")
    engine = GameEngine()
    engine.create_character("测试冒险者")
    engine.world = DNDWorld()
    engine.world_id = "dnd"

    # 模拟 11 回合（超过默认上限 10）
    engine.scene_turns = 11
    prompt = engine._build_system_prompt()

    test(
        "超过上限时系统提示词包含强制收尾指令",
        "⚠️ 当前场景已达到轮次上限" in prompt,
        f"prompt 中未找到强制收尾指令",
    )

    # 验证低于上限时不包含强制收尾指令
    engine.scene_turns = 5
    prompt_normal = engine._build_system_prompt()
    test(
        "低于上限时系统提示词不包含强制收尾指令",
        "⚠️ 当前场景已达到轮次上限" not in prompt_normal,
    )

    # 验证回合数不足时不触发（新场景保护）
    engine.scene_turns = 2
    prompt_early = engine._build_system_prompt()
    test(
        "回合数 < 3 时不触发强制收尾（新场景保护）",
        "⚠️ 当前场景已达到轮次上限" not in prompt_early,
    )

    # ================================================================
    # Test 2: 场景切换后 scene_history 非空
    # ================================================================
    print("\n[Test 2] 场景切换后 scene_history 非空")
    engine2 = GameEngine()
    engine2.create_character("测试冒险者")
    engine2.world = DNDWorld()
    engine2.world_id = "dnd"

    # 模拟若干轮对话
    engine2.messages = [
        {"role": "system", "content": "游戏开始"},
        {"role": "user", "content": "我走进酒馆"},
        {"role": "assistant", "content": "你推开了酒馆的木门，温暖的炉火照亮了大厅..."},
        {"role": "user", "content": "我找老板打听消息"},
        {"role": "assistant", "content": "老板低声告诉你，森林深处有一座被遗忘的古堡..."},
    ]
    engine2.scene_turns = 5
    engine2.character.current_scene = "酒馆"

    # 模拟 AI 返回的场景切换 action
    action = GameAction(
        narrative="你离开了酒馆，踏上了通往森林的小径，月光洒在脚下的石板路上...",
        scene="森林入口",
        scene_summary="玩家在酒馆中打听到了关于森林中隐藏宝藏的线索，并与酒馆老板建立了友好关系。",
    )

    # 手动模拟 process_input 中的场景切换逻辑
    old_scene = engine2.character.current_scene
    engine2._process_ai_output(action)
    new_scene = action.scene.strip() if action.scene else ""
    scene_changed = (
        (bool(new_scene) and new_scene != old_scene)
        or engine2.scene_turns >= Config.SCENE_TURN_LIMIT
    )

    if scene_changed and engine2.scene_turns >= 3:
        summary = SceneSummary(
            scene_name=new_scene or old_scene or "未知场景",
            summary=(action.scene_summary or "").strip(),
            ended_at_turn=engine2.scene_turns,
        )
        engine2.scene_history.append(summary)
        engine2.scene_turns = 0
        engine2.scene_start_idx = len(engine2.messages)

    test(
        "场景切换后 scene_history 非空",
        len(engine2.scene_history) > 0,
        f"scene_history 长度: {len(engine2.scene_history)}",
    )
    if engine2.scene_history:
        test(
            "SceneSummary 包含场景名称",
            bool(engine2.scene_history[0].scene_name),
        )
        test(
            "SceneSummary 包含摘要内容",
            bool(engine2.scene_history[0].summary),
        )
        test(
            "场景切换后 scene_turns 重置为 0",
            engine2.scene_turns == 0,
            f"scene_turns = {engine2.scene_turns}",
        )

    # ================================================================
    # Test 3: _trim_messages() 保留当前场景，压缩旧场景
    # ================================================================
    print("\n[Test 3] _trim_messages() 保留当前场景，压缩旧场景")
    engine3 = GameEngine()
    engine3.create_character("测试冒险者")
    engine3.world = DNDWorld()
    engine3.world_id = "dnd"

    # 设置场景历史摘要
    engine3.scene_history = [
        SceneSummary(
            scene_name="酒馆",
            summary="玩家在酒馆中打听到了重要线索，与老板建立了友谊。",
            ended_at_turn=5,
        ),
        SceneSummary(
            scene_name="森林",
            summary="玩家穿越了危险的森林，击败了一只巨狼，找到了古堡入口。",
            ended_at_turn=8,
        ),
    ]

    # 设置消息：旧场景消息 + 当前场景消息
    engine3.messages = [
        {"role": "system", "content": "游戏开始"},
        {"role": "user", "content": "我走进酒馆"},
        {"role": "assistant", "content": "你推开了酒馆的木门，温暖的炉火照亮了大厅..."},
        {"role": "user", "content": "我进入森林"},
        {"role": "assistant", "content": "森林中阴暗潮湿，远处传来狼嚎..."},
        {"role": "user", "content": "我继续前进"},
        {"role": "assistant", "content": "前方出现了一座爬满藤蔓的古老城堡..."},
    ]
    engine3.scene_start_idx = 6  # 当前场景从索引 6 开始

    engine3._trim_messages()

    test(
        "裁剪后消息包含场景摘要",
        any("场景摘要" in m.get("content", "") for m in engine3.messages),
        f"消息数: {len(engine3.messages)}",
    )
    test(
        "裁剪后保留当前场景消息",
        any("古堡" in m.get("content", "") for m in engine3.messages),
    )
    test(
        "裁剪后旧场景消息被移除",
        not any("酒馆的木门" in m.get("content", "") for m in engine3.messages),
    )
    test(
        "裁剪后 scene_start_idx 更新为摘要数量",
        engine3.scene_start_idx == len(engine3.scene_history),
        f"scene_start_idx={engine3.scene_start_idx}, 预期={len(engine3.scene_history)}",
    )

    # 边界情况：无旧场景时 _trim_messages 不改变消息
    engine3b = GameEngine()
    engine3b.create_character("测试冒险者")
    engine3b.world = DNDWorld()
    engine3b.world_id = "dnd"
    engine3b.messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，冒险者！"},
    ]
    engine3b.scene_start_idx = 0
    engine3b.scene_history = []
    engine3b._trim_messages()
    test(
        "无旧场景时 _trim_messages 不改变消息",
        len(engine3b.messages) == 2,
        f"消息数: {len(engine3b.messages)}",
    )

    # ================================================================
    # Test 4: 存档包含 scene_summaries
    # ================================================================
    print("\n[Test 4] 存档包含 scene_summaries")
    engine4 = GameEngine()
    engine4.create_character("存档测试者")
    engine4.world = DNDWorld()
    engine4.world_id = "dnd"
    engine4.messages = [
        {"role": "user", "content": "测试消息"},
        {"role": "assistant", "content": "测试回复"},
    ]
    engine4.scene_history = [
        SceneSummary(
            scene_name="测试场景A",
            summary="这是一个测试场景的摘要内容。",
            ended_at_turn=5,
        ),
    ]

    # 保存游戏
    save_path = engine4.save()
    test(
        "save() 返回有效路径",
        os.path.exists(save_path),
        f"路径: {save_path}",
    )

    # 检查 JSON 内容
    with open(save_path, "r", encoding="utf-8") as f:
        save_data = json.load(f)

    test(
        "存档 JSON 包含 scene_summaries 字段",
        "scene_summaries" in save_data,
    )
    test(
        "scene_summaries 包含正确的摘要数据",
        len(save_data.get("scene_summaries", [])) == 1
        and save_data["scene_summaries"][0]["scene_name"] == "测试场景A",
        f"scene_summaries: {save_data.get('scene_summaries')}",
    )

    # 清理测试存档
    os.remove(save_path)

    # ================================================================
    # Test 5: 加载旧格式存档（无 scene_summaries）不报错
    # ================================================================
    print("\n[Test 5] 加载旧格式存档（无 scene_summaries）不报错")
    engine5 = GameEngine()
    engine5.create_character("旧存档测试者")
    engine5.world = DNDWorld()
    engine5.world_id = "dnd"

    # 确保存档目录存在
    os.makedirs(Config.SAVE_DIR, exist_ok=True)

    # 创建旧格式存档（不含 scene_summaries）
    old_save_path = os.path.join(Config.SAVE_DIR, "_test_old_format.json")
    old_data = {
        "character": engine5.character.to_dict(),
        "world_id": "dnd",
        "messages": [
            {"role": "user", "content": "旧存档测试"},
            {"role": "assistant", "content": "这是旧格式存档的回复"},
        ],
        "saved_at": "2025-01-01T00:00:00",
    }
    with open(old_save_path, "w", encoding="utf-8") as f:
        json.dump(old_data, f, ensure_ascii=False, indent=2)

    # 加载旧格式存档
    try:
        status = engine5.load(old_save_path)
        test(
            "加载旧格式存档不抛出异常",
            True,
        )
        test(
            "加载后 scene_history 为空列表",
            engine5.scene_history == [],
            f"scene_history: {engine5.scene_history}",
        )
        test(
            "加载后 _pending_summary_injection 为 False",
            engine5._pending_summary_injection is False,
            f"_pending_summary_injection: {engine5._pending_summary_injection}",
        )
        test(
            "加载后角色数据正确恢复",
            engine5.character.name == "旧存档测试者",
            f"角色名: {engine5.character.name}",
        )
    except Exception as e:
        test(
            "加载旧格式存档不抛出异常",
            False,
            f"异常: {e}",
        )

    # 清理
    os.remove(old_save_path)

    # ================================================================
    # 结果汇总
    # ================================================================
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"结果: {passed}/{total} 通过")
    if failed == 0:
        print("ALL PASSED")
        print("=" * 60)
        return 0
    else:
        print(f"{failed} 个测试失败")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
