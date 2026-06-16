// 游戏规则参数页：当前为只读视图，仅提供拉取与重新载入

(function () {
  const C = window.SettingsCommon;

  const els = {
    initialAttributePoints: () => document.getElementById("initial-attribute-points"),
    expThreshold: () => document.getElementById("exp-threshold"),
    sceneTurnLimit: () => document.getElementById("scene-turn-limit"),
    resetBtn: () => document.getElementById("reset-btn"),
  };

  async function load() {
    C.clearStatus();
    const { ok, data } = await C.fetchJSON("/api/settings/rules");
    if (!ok) {
      C.setStatus("error", "加载配置失败");
      return;
    }
    els.initialAttributePoints().value = data.initial_attribute_points;
    els.expThreshold().value = data.exp_threshold;
    els.sceneTurnLimit().value = data.scene_turn_limit;
    C.fillBoundsHint(data.bounds || {});
  }

  document.addEventListener("DOMContentLoaded", () => {
    els.resetBtn().addEventListener("click", load);
    load();
  });
})();
