"""工作包 G 测试:缓存 manifest 生成/自检失败必须让整轮实验失败。

回测成功 -> 生成缓存内容 manifest -> 立即自检;只有 self_check == COMPLETE
整轮实验才成功。任何失败:写入原始错误、backtesting_predictions 整体
quarantine(不删模型)、本轮 manifest 标记 invalid、退出码 4;
Freqtrade 的退出码 0 不得覆盖后处理失败。
"""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ / "src"))


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_experiment_252a_g",
        PROJ / "experiments" / "freqai_rl_stage2_5_2a" / "run_experiment.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()

from rl_platform.cache_guard import derive_expected_windows  # noqa: E402

PAIR = "SYN/USDT"
TIMEFRAME_SECS = 3600
TIMERANGE = "20260715-20260729"
TRAIN_DAYS = 15
BT_DAYS = 7
FINGERPRINT = {"code_tree": "abc123", "config": "cfg456", "seed": 42}
CACHE_PIPELINE_EXIT_CODE = RUNNER.CACHE_PIPELINE_EXIT_CODE


@pytest.fixture()
def pipeline_env(tmp_path, monkeypatch):
    """构造两个窗口的合法缓存 + pipeline 所需全部路径。"""
    monkeypatch.setattr(RUNNER, "PAIR", PAIR)
    windows = derive_expected_windows(TIMERANGE, TRAIN_DAYS, BT_DAYS)
    models_dir = tmp_path / "models" / "stage252a-g-test"
    pred_dir = models_dir / "backtesting_predictions"
    pred_dir.mkdir(parents=True)
    coin = PAIR.split("/")[0].lower()
    rng = np.random.default_rng(42)
    for w in windows:
        n = (w["bt_stopts"] - w["bt_startts"]) // TIMEFRAME_SECS
        dates = pd.date_range(
            pd.Timestamp(w["bt_startts"], unit="s", tz="UTC"),
            periods=n, freq="1h",
        )
        pd.DataFrame({
            "date": dates,
            "&-target_position": (rng.random(n) > 0.5).astype(int),
            "do_predict": np.ones(n, dtype=int),
        }).reset_index(drop=True).to_feather(
            pred_dir / f"cb_{coin}_{w['timestamp_model_id']}_prediction.feather")
    manifest = {"identifier": "stage252a-g-test", "post_run": {}}
    manifest_path = tmp_path / "manifest.json"
    content_manifest_path = models_dir / "cache_content_manifest.json"
    return {
        "windows": windows,
        "pred_dir": pred_dir,
        "models_dir": models_dir,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "content_manifest_path": content_manifest_path,
        "fingerprint": FINGERPRINT,
    }


def run_pipeline(env, **overrides):
    kwargs = dict(
        identifier="stage252a-g-test",
        fingerprint=env["fingerprint"],
        windows=env["windows"],
        pred_dir=env["pred_dir"],
        content_manifest_path=env["content_manifest_path"],
        manifest=env["manifest"],
        manifest_path=env["manifest_path"],
    )
    kwargs.update(overrides)
    return RUNNER.post_backtest_cache_pipeline(**kwargs)


def test_build_manifest_exception_is_fatal(pipeline_env, monkeypatch):
    """1) build_cache_content_manifest 抛异常 -> 退出码 4 + quarantine + invalid。"""
    env = pipeline_env

    def boom(*a, **k):
        raise RuntimeError("磁盘 I/O 异常(测试注入)")

    monkeypatch.setattr(RUNNER, "build_cache_content_manifest", boom)
    rc = run_pipeline(env)
    assert rc == CACHE_PIPELINE_EXIT_CODE == 4
    m = json.loads(env["manifest_path"].read_text())
    assert m["cache_content_manifest"]["invalid"] is True
    assert "磁盘 I/O" in m["cache_content_manifest"]["error"]
    # 预测缓存被整体隔离,不再可复用
    assert not env["pred_dir"].exists()
    qdirs = list(env["models_dir"].glob("*quarantine*"))
    assert qdirs, "必须存在 quarantine 目录"
    assert any(f.suffix == ".feather" for q in qdirs for f in q.rglob("*.feather"))
    # 模型目录不被删除
    assert env["models_dir"].is_dir()


def test_manifest_write_failure_is_fatal(pipeline_env, monkeypatch):
    """2) manifest 写文件失败(父目录不存在 -> OSError) -> 退出码 4。"""
    env = pipeline_env
    blocked = env["models_dir"] / "no_such_parent" / "cache_content_manifest.json"
    rc = run_pipeline(env, content_manifest_path=blocked)
    assert rc == CACHE_PIPELINE_EXIT_CODE
    m = json.loads(env["manifest_path"].read_text())
    assert m["cache_content_manifest"]["invalid"] is True
    assert env["pred_dir"].exists() is False


def test_self_check_inconsistent_is_fatal(pipeline_env, monkeypatch):
    """3) self-check 返回 INCONSISTENT -> 退出码 4 + quarantine + invalid。"""
    env = pipeline_env

    def fake_verify(*a, **k):
        return "INCONSISTENT", ["cb_syn_x_prediction.feather: 文件 sha256 与 manifest 不符"]

    monkeypatch.setattr(RUNNER, "verify_cache_content", fake_verify)
    rc = run_pipeline(env)
    assert rc == CACHE_PIPELINE_EXIT_CODE
    m = json.loads(env["manifest_path"].read_text())
    assert m["cache_content_manifest"]["invalid"] is True
    assert m["cache_content_manifest"]["self_check"] == "INCONSISTENT"
    assert not env["pred_dir"].exists()


def test_manifest_modified_after_write_detected(pipeline_env, monkeypatch):
    """4) manifest 写出后缓存被立即修改:自检(真实函数)必须捕获 -> 退出码 4。"""
    env = pipeline_env
    # 先真实生成一份与磁盘一致的 manifest 内容
    real_content = RUNNER.build_cache_content_manifest(
        env["pred_dir"], env["windows"], PAIR, TIMEFRAME_SECS,
        fingerprint=FINGERPRINT, identifier="stage252a-g-test",
    )
    # 篡改缓存文件(模拟生成后磁盘内容被改动)
    f = sorted(env["pred_dir"].glob("*.feather"))[0]
    df = pd.read_feather(f)
    df.loc[df.index[0], "&-target_position"] = 1 - int(
        df["&-target_position"].iloc[0])
    df.to_feather(f)
    # build 返回"生成时刻"的旧内容(真实场景:生成后立刻被改)
    monkeypatch.setattr(
        RUNNER, "build_cache_content_manifest",
        lambda *a, **k: real_content,
    )
    rc = run_pipeline(env)  # verify 为真实函数,必须发现 sha 不符
    assert rc == CACHE_PIPELINE_EXIT_CODE
    m = json.loads(env["manifest_path"].read_text())
    assert m["cache_content_manifest"]["invalid"] is True


def test_normal_success_path(pipeline_env):
    """5) 正常成功路径:退出码 0,self_check=COMPLETE,invalid=False。"""
    env = pipeline_env
    rc = run_pipeline(env)
    assert rc == 0
    m = json.loads(env["manifest_path"].read_text())
    assert m["cache_content_manifest"]["self_check"] == "COMPLETE"
    assert m["cache_content_manifest"]["invalid"] is False
    assert env["pred_dir"].is_dir()  # 未隔离
    assert env["content_manifest_path"].is_file()
    # 二次运行(缓存未动)仍 COMPLETE(幂等)
    rc2 = run_pipeline(env)
    assert rc2 == 0


def test_quarantined_cache_not_reused_next_run(pipeline_env, monkeypatch):
    """后续运行不得复用被隔离缓存:quarantine 后预测目录不存在,
    名称/行数层应判 NONE(全窗重推理),而不是 COMPLETE。"""
    from rl_platform.cache_guard import classify_cache_state

    env = pipeline_env

    def boom(*a, **k):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(RUNNER, "build_cache_content_manifest", boom)
    rc = run_pipeline(env)
    assert rc == CACHE_PIPELINE_EXIT_CODE
    state = classify_cache_state(env["pred_dir"], env["windows"], PAIR,
                                 TIMEFRAME_SECS)
    assert state.state == "NONE"
