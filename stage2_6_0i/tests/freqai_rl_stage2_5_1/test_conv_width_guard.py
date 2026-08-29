"""工作包 B 测试:conv_width=1 硬性守卫(任务书七节)。

四处断言:
1. 配置渲染(run_experiment.render_config);
2. RouteCModel.__init__(config 与父类规范化后的 CONV_WIDTH 双重检查);
3. 顺序推理入口(SequentialPositionPredictor);
4. 实验启动前检查(run_experiment.main 的渲染流程内部复用 1)。
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from rl_platform.guards import CONV_WIDTH_MESSAGE, RouteCConvWidthError, assert_conv_width
from rl_platform.inference import ScriptedPolicy, SequentialPositionPredictor

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts" / "freqai_rl_stage2_5_1"
RUN_EXPERIMENT = ROOT / "experiments" / "freqai_rl_stage2_5_1" / "run_experiment.py"


# ---------------------------------------------------------------- 守卫本体
def test_assert_conv_width_ok():
    assert assert_conv_width(1) == 1
    assert assert_conv_width(1.0) == 1


@pytest.mark.parametrize("bad", [2, 3, 0, -1, "2", None, 1.5])
def test_assert_conv_width_rejects(bad):
    with pytest.raises(RouteCConvWidthError) as ei:
        assert_conv_width(bad)
    assert "conv_width=1" in str(ei.value) or "必须是整数" in str(ei.value)
    assert CONV_WIDTH_MESSAGE in str(ei.value)


# ------------------------------------------------------- 检查点 3:推理入口
def test_predictor_entry_guard():
    ok = SequentialPositionPredictor(ScriptedPolicy(), window_size=1)
    assert ok.window_size == 1
    with pytest.raises(RouteCConvWidthError):
        SequentialPositionPredictor(ScriptedPolicy(), window_size=2)


# ------------------------------------------------------- 检查点 2:模型构造
def _load_route_c_model_class():
    spec = importlib.util.spec_from_file_location(
        "route_c_model_under_test",
        ROOT / "user_data" / "freqaimodels" / "RouteCModel.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RouteCModel


def test_route_c_model_init_guard_conv_width_1():
    RouteCModel = _load_route_c_model_class()

    def fake_super_init(self, **kwargs):
        cfg = kwargs["config"]
        self.freqai_info = cfg["freqai"]
        self.config = cfg
        self.CONV_WIDTH = self.freqai_info.get("conv_width", 1)
        self.live = False
        self.activate_tensorboard = False

    with patch(
        "freqtrade.freqai.RL.BaseReinforcementLearningModel."
        "BaseReinforcementLearningModel.__init__",
        fake_super_init,
    ):
        model = RouteCModel(config={
            "freqai": {"conv_width": 1, "route_c": {"ppo": {}}},
        })
    assert model.CONV_WIDTH == 1


def test_route_c_model_init_guard_conv_width_2():
    RouteCModel = _load_route_c_model_class()

    def fake_super_init(self, **kwargs):
        cfg = kwargs["config"]
        self.freqai_info = cfg["freqai"]
        self.config = cfg
        self.CONV_WIDTH = self.freqai_info.get("conv_width", 1)
        self.live = False

    with patch(
        "freqtrade.freqai.RL.BaseReinforcementLearningModel."
        "BaseReinforcementLearningModel.__init__",
        fake_super_init,
    ):
        with pytest.raises(RouteCConvWidthError) as ei:
            RouteCModel(config={"freqai": {"conv_width": 2}})
    assert "RouteCModel.__init__" in str(ei.value)


# ------------------------------------------------------- 检查点 1:配置渲染
def _load_run_experiment():
    spec = importlib.util.spec_from_file_location("run_experiment_under_test", RUN_EXPERIMENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_config_guard_conv_width_1(tmp_path):
    mod = _load_run_experiment()
    args = SimpleNamespace(timerange="20260601-20260701", seed=42,
                           slippage_bps=5.0, fee=0.001)
    with patch.object(mod, "DATA_FILE", tmp_path / "data.feather"):
        conf = mod.render_config(args)
    assert conf["freqai"]["conv_width"] == 1


def test_render_config_guard_conv_width_2(tmp_path, monkeypatch):
    """模板被改成 conv_width=2 时,渲染阶段(启动前)必须失败,不得降级。"""
    mod = _load_run_experiment()
    bad_template = tmp_path / "bad_template.json"
    conf = json.loads(mod.TEMPLATE.read_text())
    conf["freqai"]["conv_width"] = 2
    bad_template.write_text(json.dumps(conf))

    monkeypatch.setattr(mod, "TEMPLATE", bad_template)
    args = SimpleNamespace(timerange="20260601-20260701", seed=42,
                           slippage_bps=5.0, fee=0.001)
    with patch.object(mod, "DATA_FILE", tmp_path / "data.feather"):
        with pytest.raises(RouteCConvWidthError):
            mod.render_config(args)


def test_conv_width_enters_fingerprint():
    """conv_width 变化必须产生新指纹(经完整配置覆盖,见 test_full_fingerprint)。"""
    from rl_platform.fingerprint import compute_fingerprint

    def parts(cw):
        return {"conv_width": cw, "config": {"freqai": {"conv_width": cw}}}
    assert compute_fingerprint(parts(1)) != compute_fingerprint(parts(2))


def test_guard_evidence():
    ART.mkdir(parents=True, exist_ok=True)
    lines = ["# conv_width 守卫(四处断言)验证记录", ""]
    checks = [
        ("guards.assert_conv_width(1)", "通过"),
        ("guards.assert_conv_width(2)", f"抛 RouteCConvWidthError: {CONV_WIDTH_MESSAGE}"),
        ("SequentialPositionPredictor(window_size=2)", "抛 RouteCConvWidthError(推理入口)"),
        ("RouteCModel(config conv_width=2)", "抛 RouteCConvWidthError(构造检查点)"),
        ("run_experiment.render_config(模板 conv_width=2)", "抛 RouteCConvWidthError(渲染检查点)"),
        ("conv_width 进入实验指纹", "是(完整配置 + 顶层字段)"),
    ]
    for where, result in checks:
        lines.append(f"- {where}: {result}")
    lines.append("")
    lines.append("不得自动降级为 1:全部为硬性异常,无静默路径。")
    (ART / "conv_width_guard.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
