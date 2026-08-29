"""工作包 D 测试:完整实验指纹(任务书十一至十四节 + 三十节指纹变化清单)。"""

import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rl_platform.fingerprint import (
    code_tree_hash,
    compute_fingerprint,
    config_hash,
    data_scope_hash,
    dependency_versions,
    normalize_config,
    strip_runtime_config,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_EXPERIMENT = ROOT / "experiments" / "freqai_rl_stage2_5_1" / "run_experiment.py"


def base_parts(**over):
    parts = {
        "freqtrade_commit": "52bc96f" * 5,
        "code_tree": "a" * 64,
        "config": {"freqai": {"identifier": "x", "conv_width": 1, "fee": 0.001,
                              "route_c": {"slippage_bps": 0.0, "seed": 42,
                                          "ppo": {"gamma": 0.90, "n_steps": 128}},
                              "feature_parameters": {"include_timeframes": ["1h"]}}},
        "data_scope": {"sha256": "b" * 64},
        "dependencies": {"stable_baselines3": "2.9.0"},
        "resolved_ppo_params": {"runtime": {"seed": 42}, "constructor": {"n_steps": 128}},
        "conv_width": 1,
        "timerange": "20260601-20260701",
    }
    parts.update(over)
    return parts


# ------------------------------------------------------- 配置规范化
def test_strip_identifier_avoids_self_reference():
    conf = {"freqai": {"identifier": "stage251-rc-abc", "conv_width": 1}, "fee": 0.001}
    stripped = strip_runtime_config(conf)
    assert "identifier" not in stripped["freqai"]
    assert stripped["freqai"]["conv_width"] == 1
    # 原配置不被修改
    assert conf["freqai"]["identifier"] == "stage251-rc-abc"


def test_normalize_config_stable_and_sorted():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert normalize_config(a) == normalize_config(b)
    assert config_hash(a) == config_hash(b)
    c = {"a": {"x": 4, "y": 2}, "b": 1}
    assert config_hash(a) != config_hash(c)


# ------------------------------------------------------- 三十节:单变量指纹变化
def test_fingerprint_changes_single_field():
    """seed / fee / slippage / PPO n_steps / PPO gamma / conv_width /
    特征配置 / timerange / 依赖版本模拟值,任一变化 -> 新指纹。"""
    base_fp = compute_fingerprint(base_parts())
    variants = []

    def cfg_variant(mutate):
        import copy
        parts = base_parts()
        parts["config"] = copy.deepcopy(parts["config"])
        mutate(parts)
        variants.append(compute_fingerprint(parts))

    cfg_variant(lambda p: p["config"]["freqai"]["route_c"].update(seed=43))          # seed
    cfg_variant(lambda p: p["config"].update(fee=0.002))                             # fee
    cfg_variant(lambda p: p["config"]["freqai"]["route_c"].update(slippage_bps=5.0))  # slip
    cfg_variant(lambda p: p["config"]["freqai"]["route_c"]["ppo"].update(n_steps=64))  # n_steps
    cfg_variant(lambda p: p["config"]["freqai"]["route_c"]["ppo"].update(gamma=0.95))  # gamma
    cfg_variant(lambda p: p["config"]["freqai"].update(conv_width=2))               # conv_width
    cfg_variant(lambda p: p["config"]["freqai"]["feature_parameters"].update(
        include_timeframes=["1h", "4h"]))                                            # 特征
    cfg_variant(lambda p: p.update(timerange="20260601-20260615"))                   # timerange
    dep = dict(base_parts())
    dep["dependencies"] = {"stable_baselines3": "2.9.1"}                             # 依赖模拟
    variants.append(compute_fingerprint(dep))

    assert all(v != base_fp for v in variants), "存在未改变指纹的变体"
    assert len(set(variants)) == len(variants), "不同变体指纹冲突"


# ------------------------------------------------------- 代码树哈希(临时项目根)
def _make_min_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src" / "rl_platform").mkdir(parents=True)
    (root / "user_data" / "freqaimodels").mkdir(parents=True)
    (root / "user_data" / "strategies").mkdir(parents=True)
    (root / "experiments" / "freqai_rl_stage2_5" / "configs").mkdir(parents=True)
    (root / "experiments" / "freqai_rl_stage2_5_1" / "configs").mkdir(parents=True)
    shutil.copy(ROOT / "src/rl_platform/env.py", root / "src/rl_platform/env.py")
    shutil.copy(ROOT / "user_data/freqaimodels/RouteCModel.py",
                root / "user_data/freqaimodels/RouteCModel.py")
    shutil.copy(ROOT / "user_data/strategies/RouteCStrategy.py",
                root / "user_data/strategies/RouteCStrategy.py")
    shutil.copy(ROOT / "experiments/freqai_rl_stage2_5/run_experiment.py",
                root / "experiments/freqai_rl_stage2_5/run_experiment.py")
    shutil.copy(ROOT / "experiments/freqai_rl_stage2_5/configs/config_stage25.template.json",
                root / "experiments/freqai_rl_stage2_5/configs/config_stage25.template.json")
    shutil.copy(RUN_EXPERIMENT, root / "experiments/freqai_rl_stage2_5_1/run_experiment.py")
    shutil.copy(RUN_EXPERIMENT.parent / "configs/config_stage251.template.json",
                root / "experiments/freqai_rl_stage2_5_1/configs/config_stage251.template.json")
    # 排除项:不应进入树哈希
    (root / "src/rl_platform/__pycache__").mkdir()
    (root / "src/rl_platform/__pycache__/env.cpython-311.pyc").write_text("junk")
    (root / "experiments/freqai_rl_stage2_5/runtime").mkdir()
    (root / "experiments/freqai_rl_stage2_5/runtime/manifest.json").write_text("{}")
    return root


def test_code_tree_hash_covers_first_party_code(tmp_path):
    root = _make_min_project(tmp_path)
    tree = code_tree_hash(root)
    names = set(tree["files"])
    assert "src/rl_platform/env.py" in names
    assert "user_data/freqaimodels/RouteCModel.py" in names
    assert "user_data/strategies/RouteCStrategy.py" in names
    assert "experiments/freqai_rl_stage2_5/run_experiment.py" in names
    assert "experiments/freqai_rl_stage2_5/configs/config_stage25.template.json" in names
    assert "experiments/freqai_rl_stage2_5_1/run_experiment.py" in names
    assert not any("__pycache__" in n or "runtime" in n for n in names), names


@pytest.mark.parametrize("target", [
    "user_data/freqaimodels/RouteCModel.py",       # RouteCModel 代码
    "user_data/strategies/RouteCStrategy.py",      # RouteCStrategy 代码
    "experiments/freqai_rl_stage2_5_1/run_experiment.py",  # run_experiment.py
    "experiments/freqai_rl_stage2_5_1/configs/config_stage251.template.json",  # 配置模板
    "src/rl_platform/env.py",                      # 核心环境代码
])
def test_code_tree_hash_changes_on_file_edit(tmp_path, target):
    root = _make_min_project(tmp_path)
    before = code_tree_hash(root)["tree_hash"]
    p = root / target
    text = p.read_text(encoding="utf-8")
    p.write_text(text + "\n# stage251 mutation\n", encoding="utf-8")
    after = code_tree_hash(root)["tree_hash"]
    assert before != after


def test_code_tree_hash_stable_regardless_of_mtime(tmp_path):
    root = _make_min_project(tmp_path)
    h1 = code_tree_hash(root)["tree_hash"]
    # 触碰修改时间但不改内容
    for p in (root / "src/rl_platform").glob("*.py"):
        p.touch()
    h2 = code_tree_hash(root)["tree_hash"]
    assert h1 == h2


# ------------------------------------------------------- 数据范围哈希
def _make_data(tmp_path: Path) -> Path:
    f = tmp_path / "BTC_USDT-1h.feather"
    dates = pd.date_range("2026-05-01", periods=24 * 40, freq="1h", tz="UTC")
    n = len(dates)
    df = pd.DataFrame({
        "date": dates,
        "open": np.linspace(100, 110, n), "high": np.linspace(101, 111, n),
        "low": np.linspace(99, 109, n), "close": np.linspace(100.5, 110.5, n),
        "volume": np.ones(n),
    })
    df.to_feather(f)
    return f


def test_data_scope_hash_covers_training_and_prewarm(tmp_path):
    f = _make_data(tmp_path)
    eval_end = pd.Timestamp("2026-06-01", tz="UTC")
    info = data_scope_hash(f, eval_end)
    # 5-01 到 6-01 共 31 天 = 744 行全部参与
    assert info["rows_hashed"] == 31 * 24
    assert info["last_hashed_date"] == str(pd.Timestamp("2026-05-31 23:00:00+00:00"))


def test_data_scope_hash_ignores_rows_after_eval_end(tmp_path):
    f = _make_data(tmp_path)
    eval_end = pd.Timestamp("2026-06-01", tz="UTC")
    before = data_scope_hash(f, eval_end)
    # 追加评估结束之后的新 K 线 -> 哈希不变
    df = pd.read_feather(f)
    extra = df.tail(1).copy()
    extra["date"] = [pd.Timestamp("2026-06-05 00:00:00+00:00")]
    pd.concat([df, extra], ignore_index=True).to_feather(f)
    after = data_scope_hash(f, eval_end)
    assert before["sha256"] == after["sha256"]


def test_data_scope_hash_changes_on_training_row_edit(tmp_path):
    f = _make_data(tmp_path)
    eval_end = pd.Timestamp("2026-06-01", tz="UTC")
    before = data_scope_hash(f, eval_end)
    df = pd.read_feather(f)
    # 修改一行训练数据(date < eval_end)
    df.loc[3, "close"] += 0.5
    df.to_feather(f)
    after = data_scope_hash(f, eval_end)
    assert before["sha256"] != after["sha256"]


# ------------------------------------------------------- 依赖版本实测
def test_dependency_versions_real_imports():
    deps = dependency_versions()
    for key in ("python", "freqtrade", "stable_baselines3", "gymnasium", "torch",
                "numpy", "pandas", "scikit-learn", "ccxt", "os"):
        assert key in deps and deps[key], f"{key} 缺失"
    assert deps["python"].startswith("3.")
    assert deps["freqtrade"] == "2026.7"


# ------------------------------------------------------- manifest 完整性(入口)
def test_run_experiment_manifest_fields(tmp_path, monkeypatch):
    """--skip-backtest 渲染指纹与 manifest,验证字段完整 + 移除硬编码。"""
    spec = importlib.util.spec_from_file_location("run_experiment_manifest", RUN_EXPERIMENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = _make_data(tmp_path)
    monkeypatch.setattr(mod, "DATA_FILE", data)
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path / "runtime")
    rc = 0
    import sys as _sys
    _sys.argv = ["run_experiment.py", "--timerange", "20260520-20260525",
                 "--slippage-bps", "5", "--suffix", "fp", "--skip-backtest"]
    try:
        rc = mod.main()
    except SystemExit as e:
        rc = int(e.code or 0)
    assert rc == 0
    manifests = list((tmp_path / "runtime").glob("manifest_*.json"))
    assert len(manifests) == 1
    m = json.loads(manifests[0].read_text())
    for key in ("identifier", "fingerprint", "freqtrade_commit", "code_tree",
                "config_normalized", "config_hash", "data_scope", "eval_slice",
                "dependencies", "resolved_ppo_params", "expected_windows"):
        assert key in m, f"manifest 缺少 {key}"
    assert m["identifier"].startswith("stage251-rc-")
    assert m["resolved_ppo_params"]["constructor"]["n_steps"] == 128
    assert len(m["expected_windows"]) >= 1
    # identifier 未进入指纹输入(自指避免)
    assert "stage251-rc-" not in json.dumps(m["config_normalized"])
