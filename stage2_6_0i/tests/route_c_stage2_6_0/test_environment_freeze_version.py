"""冻结版本常量、注入与 fail-closed(阶段 2.6.0 工作包 0)。"""

from __future__ import annotations

import json

import pytest

from rl_platform.versions import (
    CHECKPOINT_REQUIRED_VERSIONS,
    ENV_CORE_VERSION,
    SpecVersionMismatchError,
    assert_versions_compatible,
    spec_versions,
)


def test_frozen_version_values():
    assert ENV_CORE_VERSION == "RouteCEnvCore-v1.0.0"
    v = spec_versions()
    assert v["observation_spec_version"] == "ObservationSpec-v1"
    assert v["action_spec_version"] == "BinaryLongFlatAction-v1"
    assert v["reward_spec_version"] == "NetLogEquityReward-v1"
    assert v["execution_contract_version"] == "MarketOpenCausalExecution-v1"
    assert v["terminal_liquidation_version"] == "TerminalLiquidation-v1"


def test_env_exposes_frozen_versions():
    from rl_platform.env import AlignedLongFlatEnv

    assert AlignedLongFlatEnv.env_core_version == ENV_CORE_VERSION
    assert (
        AlignedLongFlatEnv.observation_spec_version
        == spec_versions()["observation_spec_version"]
    )


def test_versions_into_run_experiment_config_and_manifest():
    # 静态断言注入(避免重入口执行):版本必须进入 config 与 manifest
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / (
        "experiments/freqai_rl_stage2_5_2a/run_experiment.py")
    text = src.read_text(encoding="utf-8")
    assert "rc.update(spec_versions())" in text
    assert '"spec_versions": spec_versions(),' in text


def test_incompatible_checkpoint_versions_rejected():
    good = dict(CHECKPOINT_REQUIRED_VERSIONS)
    assert_versions_compatible(good)  # 不抛
    with pytest.raises(SpecVersionMismatchError):
        assert_versions_compatible(None)  # 无元数据
    with pytest.raises(SpecVersionMismatchError):
        assert_versions_compatible({})  # 缺全部字段
    bad = dict(good)
    bad["env_core_version"] = "RouteCEnvCore-v0.9.0"
    with pytest.raises(SpecVersionMismatchError, match="env_core_version"):
        assert_versions_compatible(bad)
    missing = {k: v for k, v in good.items() if k != "action_spec_version"}
    with pytest.raises(SpecVersionMismatchError, match="缺失"):
        assert_versions_compatible(missing)


def test_versions_are_json_serializable():
    json.dumps(spec_versions())
