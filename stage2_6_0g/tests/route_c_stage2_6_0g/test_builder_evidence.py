"""阶段 2.6.0g 收尾:工作包 E 攻击矩阵——evidence 与确定性。"""

from __future__ import annotations

import copy
import json

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    private_provider_from_root,
    write_private_builder,
)


def _private_evidence(tmp_path, pack, dc):
    from rl_curriculum.builder_evidence import precommit_builder_runs

    root = write_private_builder(tmp_path / "ev_builder")
    provider = private_provider_from_root(root)
    req = provider.frozen_build_request(pack, dc)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    return provider, req, evidence, runs


def test_precommit_double_run_hashes(private_builder_a, sealed_exam_env,
                                     duration_contract, mock_pack):
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )

    provider = private_builder_a
    req = provider.frozen_build_request(mock_pack, duration_contract)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    r1, r2 = evidence["runs"]
    assert r1["pack_hash"] == r2["pack_hash"]
    assert r1["attempt_log_hash"] == r2["attempt_log_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]
    assert evidence["evidence_hash"].startswith("bre-")
    assert evidence["runner_code_hash"].startswith("rtb-")
    assert evidence["sandbox_profile_hash"].startswith("brp-")
    assert evidence["runtime_lock_hash"].startswith("nrl-")
    assert evidence["attempt_log_hash"].startswith("nal-")
    assert evidence["frozen_request_hash"].startswith("nbr-")
    assert evidence["attempt_policy_hash"].startswith("nap-")
    assert evidence["staged_tree_hash"]
    assert runs[0]["isolated_process"] is True


def test_evidence_core_hash_excludes_detail(sealed_exam_env):
    evidence = sealed_exam_env["evidence"]
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_core,
        builder_run_evidence_hash,
    )

    core = builder_run_evidence_core(evidence)
    assert "detail" not in core
    assert builder_run_evidence_hash(evidence) == \
        evidence["evidence_hash"]
    # detail 不进 bre-:篡改 detail 才会破坏自洽(哈希覆盖核心字段)
    tampered = copy.deepcopy(evidence)
    tampered["mode"] = "builder_execution"
    assert builder_run_evidence_hash(tampered) != evidence["evidence_hash"]


def test_evidence_verify_against_commitment(private_builder_a,
                                            sealed_exam_env,
                                            duration_contract, mock_pack):
    from rl_curriculum.builder_evidence import (
        verify_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    provider = private_builder_a
    req = provider.frozen_build_request(mock_pack, duration_contract)
    identity = provider.builder_identity()
    # 用私有 builder 自己的 evidence + 自己的请求构造自洽校验
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )

    evidence, _ = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash,
    )

    class _C:
        pack_hash = evidence["output_pack_hash"]
        builder_run_evidence = {
            k: v for k, v in evidence.items() if k != "detail"}

    verify_builder_run_evidence(
        evidence, commitment=_C(), identity=identity,
        request_hash=frozen_build_request_hash(req))
    # 篡改 output_pack_hash -> 与承诺不一致
    bad = copy.deepcopy(evidence)
    bad["output_pack_hash"] = "p-" + "0" * 64
    with pytest.raises(BuilderProvenanceError):
        verify_builder_run_evidence(
            bad, commitment=_C(), identity=identity,
            request_hash=frozen_build_request_hash(req))


def test_runs_mismatch_rejected(sealed_exam_env, mock_provider,
                                duration_contract, mock_pack):
    """precommit 双跑记录不一致(evidence 层伪造) -> 拒绝。"""
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
        verify_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        frozen_build_request_hash,
    )

    req = mock_provider.frozen_build_request(mock_pack, duration_contract)
    evidence = copy.deepcopy(sealed_exam_env["evidence"])
    evidence["runs"] = [
        {"run": 1, "pack_hash": "p-a", "attempt_log_hash": "nal-a",
         "runtime_lock_hash": "nrl-a"},
        {"run": 2, "pack_hash": "p-b", "attempt_log_hash": "nal-b",
         "runtime_lock_hash": "nrl-b"}]
    evidence["evidence_hash"] = builder_run_evidence_hash(evidence)
    commitment = sealed_exam_env["commitment"]
    with pytest.raises(BuilderProvenanceError,
                       match="不完整或不一致|不一致"):
        verify_builder_run_evidence(
            evidence, commitment=commitment,
            identity=sealed_exam_env["provider"].builder_identity(),
            request_hash=frozen_build_request_hash(req))


def test_deterministic_false_rejected(sealed_exam_env, mock_provider,
                                      duration_contract, mock_pack):
    from rl_curriculum.builder_evidence import (
        verify_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        frozen_build_request_hash,
    )

    evidence = copy.deepcopy(sealed_exam_env["evidence"])
    evidence["deterministic"] = False
    commitment = sealed_exam_env["commitment"]
    # evidence_hash 不再匹配承诺摘要 -> 先在哈希层拒绝
    with pytest.raises(BuilderProvenanceError):
        verify_builder_run_evidence(
            evidence, commitment=commitment,
            identity=sealed_exam_env["provider"].builder_identity(),
            request_hash=frozen_build_request_hash(
                mock_provider.frozen_build_request(mock_pack,
                                                   duration_contract)))


def test_evidence_file_roundtrip_private(tmp_path, sealed_exam_env,
                                         duration_contract, mock_pack):
    provider, req, evidence, _ = _private_evidence(
        tmp_path, mock_pack, duration_contract)
    from rl_curriculum.builder_evidence import (
        load_builder_run_evidence,
        write_builder_run_evidence,
    )

    p = tmp_path / "private_ev.json"
    write_builder_run_evidence(p, evidence)
    loaded = load_builder_run_evidence(p)
    assert loaded["evidence_hash"] == evidence["evidence_hash"]
    assert "runtime_lock" in loaded["detail"]
    assert "attempt_log" in loaded["detail"]
