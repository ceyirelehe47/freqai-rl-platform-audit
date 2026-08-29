"""阶段 2.6.0g 收尾:产物来源证明 + evidence 第三次重放(工作包 E)。

- verify_builder_provenance 按 mode 分派:mock 走主进程重组装,
  builder_execution 走全新隔离 Runner;
- 无 evidence -> 拒绝;evidence 篡改 -> bre- 对账拒绝;
- precommit 双跑 + 第三次重放的三组 hash 对账;
- 私有 None 入口/错误产物在隔离 Runner 内被拒。
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    PRIVATE_BUILDER_NONE_FILES,
    private_provider_from_root,
    write_private_builder,
)


def test_verify_mock_provenance_with_evidence(sealed_exam_env,
                                              mock_provider,
                                              duration_contract,
                                              mock_pack, tmp_path):
    from rl_curriculum.builder_evidence import (
        write_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        verify_builder_provenance,
    )

    commitment = sealed_exam_env["commitment"]
    ev_path = tmp_path / "evidence.json"
    write_builder_run_evidence(ev_path, sealed_exam_env["evidence"])
    report = verify_builder_provenance(
        mock_provider, commitment, pack=mock_pack,
        duration_contract=duration_contract,
        builder_evidence=sealed_exam_env["evidence"])
    assert report["status"] == "ok"
    assert report["mode"] == "mock_payload_assembly"
    assert report["replay_pack_hash"] == commitment.pack_hash
    assert report["evidence_hash"].startswith("bre-")
    assert report["replay_isolated_process"] is False
    assert ev_path.exists()


def test_verify_without_evidence_rejected(sealed_exam_env, mock_provider,
                                          duration_contract, mock_pack):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        verify_builder_provenance,
    )

    with pytest.raises(BuilderProvenanceError, match="Run Evidence"):
        verify_builder_provenance(
            mock_provider, sealed_exam_env["commitment"], pack=mock_pack,
            duration_contract=duration_contract, builder_evidence=None)


def test_tampered_evidence_rejected(sealed_exam_env, mock_provider,
                                    duration_contract, mock_pack):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        verify_builder_provenance,
    )

    ev = copy.deepcopy(sealed_exam_env["evidence"])
    ev["detail"]["attempt_log"]["selected_attempt"] = 99
    with pytest.raises(BuilderProvenanceError,
                       match="不合法|不一致|哈希不一致"):
        verify_builder_provenance(
            mock_provider, sealed_exam_env["commitment"], pack=mock_pack,
            duration_contract=duration_contract, builder_evidence=ev)


def test_evidence_wrong_request_rejected(sealed_exam_env, mock_provider,
                                         duration_contract, mock_pack):
    """evidence 绑定的 nbr- 与请求不符 -> 拒绝。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        verify_builder_provenance,
    )

    ev = copy.deepcopy(sealed_exam_env["evidence"])
    ev["frozen_request_hash"] = "nbr-" + "9" * 64
    # 重新自签 evidence_hash 模拟攻击者
    from rl_curriculum.builder_evidence import (
        builder_run_evidence_hash,
    )

    ev["evidence_hash"] = builder_run_evidence_hash(ev)
    with pytest.raises(BuilderProvenanceError,
                       match="frozen_request|哈希不一致"):
        verify_builder_provenance(
            mock_provider, sealed_exam_env["commitment"], pack=mock_pack,
            duration_contract=duration_contract, builder_evidence=ev)


def test_private_provenance_via_isolated_runner(private_builder_a,
                                                 sealed_exam_env,
                                                 duration_contract,
                                                 mock_pack):
    """私有 builder_execution 模式:第三次重放在全新隔离 Runner 内执行。

    builder A 的产物 pack_hash 与 mock 承诺不同 -> pack_hash 对账
    拒绝;但重放本身真实发生了隔离进程(isolated_process=True)。
    """
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        verify_builder_provenance,
    )

    provider = private_builder_a
    req = provider.frozen_build_request(mock_pack, duration_contract)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    assert evidence["mode"] == "builder_execution"
    assert evidence["deterministic"] is True
    assert runs[0]["runner_isolation"] == "isolated_process"
    # 私有请求不得携带 mock 载荷
    assert "mock_pack_payload" not in req
    # 对 mock 承诺做 verify:请求 nbr 不同 -> 拒绝
    with pytest.raises(BuilderProvenanceError, match="nbr|请求"):
        verify_builder_provenance(
            provider, sealed_exam_env["commitment"], pack=mock_pack,
            duration_contract=duration_contract, builder_evidence=evidence,
            builder_root=provider.root)


def test_private_none_entrypoint_rejected_in_runner(private_builder_none,
                                                    sealed_exam_env,
                                                    duration_contract,
                                                    mock_pack):
    """P2 攻击闭环:None 入口在隔离 Runner 内执行失败(fail closed)。"""
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    provider = private_builder_none
    req = provider.frozen_build_request(mock_pack, duration_contract)
    with pytest.raises(BuilderProvenanceError,
                       match="Runner|返回 None|失败"):
        precommit_builder_runs(
            provider, req, builder_root=provider.root)


def test_private_wrong_pack_builder_rejected(private_builder_wrong_pack,
                                             sealed_exam_env,
                                             duration_contract,
                                             mock_pack):
    """产物来源攻击:builder 无视冻结 timeframe 构造 5m pack -> 与
    承诺(15m)的 pack_hash 对不上,precommit 阶段即暴露。"""
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )

    provider = private_builder_wrong_pack
    req = provider.frozen_build_request(mock_pack, duration_contract)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    assert runs[0]["pack"].timeframe == "5m"
    assert runs[0]["pack_hash"] != sealed_exam_env["commitment"].pack_hash


def test_evidence_write_load_roundtrip(sealed_exam_env, tmp_path):
    from rl_curriculum.builder_evidence import (
        load_builder_run_evidence,
        write_builder_run_evidence,
    )

    p = tmp_path / "ev.json"
    write_builder_run_evidence(p, sealed_exam_env["evidence"])
    loaded = load_builder_run_evidence(p)
    assert loaded["evidence_hash"] == \
        sealed_exam_env["evidence"]["evidence_hash"]


def test_load_missing_evidence_rejected(tmp_path):
    from rl_curriculum.builder_evidence import (
        BuilderProvenanceError,
        load_builder_run_evidence,
    )

    with pytest.raises(BuilderProvenanceError, match="不存在"):
        load_builder_run_evidence(tmp_path / "nope.json")
