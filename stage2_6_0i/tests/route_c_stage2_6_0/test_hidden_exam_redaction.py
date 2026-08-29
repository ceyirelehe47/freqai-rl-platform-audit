"""工作包 K + 阶段 2.6.0a 工作包 H:密封模式输出最小化(严格脱敏)。

阶段 2.6.0a 更新:旧断言只检查"episodes 不出现";新断言要求默认输出
不含 family/split/参数桶/分组统计/分位数/seed/参数(仅硬门布尔与
粗粒度分数带)。旧 CLI(--policy 直评聚合)已删除;公开开发考试的
调试通道是 --dev(标记 formal_conclusion=false)。
阶段 2.6.0b 更新:--no-subprocess 已删除(正式候选一律系统级沙箱执行,
CLI 走真实全链路);承诺 v2 绑定 sandbox profile 与受信 issuer;考试包
Null 家族改为严格三族(sign/volstate/stochvol,block 降级为诊断族)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))


@pytest.fixture()
def sealed_redact_env(tmp_path, formal_checkpoint, sandbox_profile,
                      mock_trusted_issuer):
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
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
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
        name="redact_demo", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 1,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 2,
                        "dev_seed_holdout", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 12,
                        "dev_seed_holdout", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 22,
                        "dev_seed_holdout", timeframe="15m"),
        ] + list(_null_specs()),
        timeframe="15m",
    )
    pack.save(tmp_path / "pack.json")
    write_exam_context(tmp_path / "ctx.json", charter=charter, schema=schema,
                       eval_config=default_eval_config(),
                       sandbox_profile=sandbox_profile,
                       trusted_issuer=mock_trusted_issuer)
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
        evidence_path=str(tmp_path / "builder_evidence.json"),
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(),
        eval_config=default_eval_config(),
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    commitment.save(tmp_path / "commitment.json")
    return {"tmp": tmp_path, "pack": pack, "checkpoint": formal_checkpoint,
            "profile": sandbox_profile}


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
        "--builder-evidence", str(tmp / "builder_evidence.json"),
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])


def test_sealed_output_minimal(sealed_redact_env):
    rc = _run_cli(sealed_redact_env, "agg.json")
    assert rc == 0
    out = json.loads((sealed_redact_env["tmp"] / "agg.json").read_text())
    result = out["result"]
    # 允许的最小字段集(H):attempt id/checkpoint hash/pack hash/状态/
    # 等级/硬门布尔/分数带/完整性/建议
    for key in ("attempt_id", "checkpoint_hash", "pack_hash", "status",
                "grade", "hard_gates", "score_band", "integrity_ok",
                "recommendation"):
        assert key in result
    text = json.dumps(out)
    # 禁止泄漏:generator family/split/参数桶/分组统计/分位数/seed
    for forbidden in ("probe_segmented_drift", "dev_seed_holdout",
                      "param_extrapolation", "by_family", "by_split",
                      "by_param_bucket", "q10", "worst", "best",
                      "actions_sha256", "\"seed\"", "\"params\""):
        assert forbidden not in text, f"密封输出泄漏 {forbidden}"
    # 硬门只是布尔
    assert all(isinstance(v, bool) for v in result["hard_gates"].values())
    assert out["exit_code"] == 0


def test_sealed_status_from_frozen_verdict(sealed_redact_env):
    """状态由冻结判定器产生(PASS/FAIL/SUSPECTED_CHEATING),四态可辨。"""
    _run_cli(sealed_redact_env, "agg.json")
    out = json.loads((sealed_redact_env["tmp"] / "agg.json").read_text())
    assert out["result"]["status"] in (
        "PASS", "FAIL", "SUSPECTED_CHEATING")
    # 测试级未学习 PPO 不可能凭收益中位数直接 PASS:overall median > 0
    # 不再足以 PASS(硬门组合决定)
    assert out["result"]["recommendation"] in ("proceed", "do_not_proceed")


def test_attempt_recorded_idempotent(sealed_redact_env):
    """同 (checkpoint, pack) 重跑:同一 attempt 结果,幂等重试。"""
    _run_cli(sealed_redact_env, "agg1.json")
    rc = _run_cli(sealed_redact_env, "agg2.json")
    assert rc == 0
    o1 = json.loads((sealed_redact_env["tmp"] / "agg1.json").read_text())
    o2 = json.loads((sealed_redact_env["tmp"] / "agg2.json").read_text())
    assert o2["attempt"]["idempotent_retry_of"] == o1["attempt"]["attempt_id"]
    assert o2["result"]["status"] == o1["result"]["status"]


def test_detailed_only_after_retirement(sealed_redact_env):
    """详细结果写出后包退休;再次运行 EXAM_INVALID。"""
    tmp = sealed_redact_env["tmp"]
    rc = _run_cli(sealed_redact_env, "agg.json",
                  "--detailed", str(tmp / "detail.json"))
    assert rc == 0
    detail = json.loads((tmp / "detail.json").read_text())
    # 详细输出才包含聚合与逐 Episode 证据(独立审计方使用)
    assert "report" in detail and "counterfactuals" in detail
    rc2 = _run_cli(sealed_redact_env, "agg2.json")
    assert rc2 == 5


def test_dev_mode_requires_public_pack(sealed_redact_env, tmp_path):
    """--dev 只接受 public pack;mock_hidden 必须走密封。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = sealed_redact_env["tmp"]
    with pytest.raises(SystemExit):
        exam_main([
            "--dev", "--pack", str(tmp / "pack.json"),
            "--policy", "rule_trend", "--out", str(tmp / "dev.json"),
        ])


def test_unknown_policy_rejected(sealed_redact_env, tmp_path):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    with pytest.raises(SystemExit):
        exam_main([
            "--dev", "--pack", str(sealed_redact_env["tmp"] / "pack.json"),
            "--policy", "no_such", "--out", str(tmp_path / "x.json"),
        ])
