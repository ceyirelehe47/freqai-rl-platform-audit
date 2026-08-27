"""工作包 K + 阶段 2.6.0a 工作包 H:考试包退休机制(密封模式)。

阶段 2.6.0a 更新:旧 CLI(--policy 规则策略直评)已不存在;退休演示
改走密封模式(--sealed-manifest + --checkpoint + --context)。
阶段 2.6.0b 更新:--no-subprocess 已删除(候选一律系统级沙箱执行);
承诺 v2 绑定 sandbox profile 与受信 issuer;checkpoint 需受信
attestation;考试包 Null 家族改为严格三族(含 stochvol 不含 block)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))


@pytest.fixture()
def sealed_env(tmp_path, formal_checkpoint, sandbox_profile,
               mock_trusted_issuer):
    """小型密封环境:pack + context + commitment + attested checkpoint。"""
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        default_eval_config,
        write_exam_context,
    )
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.probe_charter import (
        audit_probe_charter,
        probe_observation_schema,
    )
    from rl_platform.versions import spec_versions

    charter = audit_probe_charter()
    schema = probe_observation_schema()
    import sys as _sys0
    from pathlib import Path as _P0

    _t0 = _P0(__file__).resolve().parents[1]
    if str(_t0) not in _sys0.path:
        _sys0.path.insert(0, str(_t0))
    from null_qual_cache import null_episode_specs as _null_specs
    pack = ExamPack(
        name="retire_demo", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 1,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 2,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 3,
                        "dev_seed_holdout", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 23,
                        "dev_seed_holdout", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 43,
                        "dev_seed_holdout", timeframe="15m"),
        ] + list(_null_specs()),
        timeframe="15m",
    )
    pack.save(tmp_path / "pack.json")
    write_exam_context(
        tmp_path / "ctx.json", charter=charter, schema=schema,
        eval_config=default_eval_config(),
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer)
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    # 阶段 2.6.0d:完整资格链(v3 + 功效 + pack validity)+ null 扩容
    import sys as _sys
    from pathlib import Path as _P

    _tests = _P(__file__).resolve().parents[1]
    if str(_tests) not in _sys.path:
        _sys.path.insert(0, str(_tests))
    from null_qual_cache import (
        build_commitment_null_materials,
        null_episode_specs,
    )

    materials = build_commitment_null_materials(
        pack, schema, default_eval_config())
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(),
        eval_config=default_eval_config(),
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=materials['bindings'],
        power_analysis_report=materials['power_analysis_report'],
        pack_validity_report=materials['pack_validity_report'],
    )
    commitment.save(tmp_path / "commitment.json")
    return {"tmp": tmp_path, "pack": pack, "charter": charter,
            "schema": schema, "checkpoint": formal_checkpoint}


def _run_cli(env_dir, out_name, *extra):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = env_dir["tmp"]
    return exam_main([
        "--sealed-manifest", str(tmp / "commitment.json"),
        "--pack", str(tmp / "pack.json"),
        "--checkpoint", str(env_dir["checkpoint"]),
        "--context", str(tmp / "ctx.json"),
        "--out", str(tmp / out_name),
        "--builder-provider", "mock",
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])


def test_detailed_disclosure_retires_pack(sealed_env):
    from rl_curriculum.exam_pack import RetirementRegistry

    tmp = sealed_env["tmp"]
    rc = _run_cli(sealed_env, "agg.json", "--detailed", str(tmp / "detail.json"))
    assert rc == 0
    assert (tmp / "detail.json").is_file()
    reg = RetirementRegistry(tmp / "ret.json")
    assert reg.is_retired(sealed_env["pack"].pack_hash())
    entry = reg.entries()[sealed_env["pack"].pack_hash()]
    assert "详细结果已公开" in entry["reason"]


def test_retired_pack_rejected_on_reuse(sealed_env):
    from rl_curriculum.exam_pack import (
        ExamPack,
        RetirementRegistry,
        materialize_pack,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    tmp = sealed_env["tmp"]
    _run_cli(sealed_env, "agg1.json", "--detailed", str(tmp / "detail.json"))
    # 已退休:再评估必须被拒绝(EXAM_INVALID)
    rc = _run_cli(sealed_env, "agg2.json")
    assert rc == 5
    out = json.loads((tmp / "agg2.json").read_text())
    assert out["status"] == "EXAM_INVALID"
    # 错误输出已脱敏:不出现内部异常原文,但保留状态
    assert "error" not in out or not out.get("error")
    with pytest.raises(Exception, match="退休"):
        materialize_pack(
            ExamPack.load(tmp / "pack.json"),
            DEFAULT_GENERATOR_REGISTRY,
            retire_registry=RetirementRegistry(tmp / "ret.json"),
        )


def test_aggregate_only_does_not_retire(sealed_env):
    from rl_curriculum.exam_pack import RetirementRegistry

    tmp = sealed_env["tmp"]
    _run_cli(sealed_env, "agg.json")
    assert not RetirementRegistry(tmp / "ret.json").is_retired(
        sealed_env["pack"].pack_hash())
