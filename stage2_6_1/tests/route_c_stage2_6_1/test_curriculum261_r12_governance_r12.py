# -*- coding: utf-8 -*-
"""R12 测试:GenerationEvidenceCompleteness-v1 与 HistoricalEvidenceBinding-v1
及 freeze 治理(§5/§6/§15/§26)。

覆盖:
- missing envelope 拒绝;duplicate envelope 拒绝;orphan 拒绝;
- 同坐标多重合法调用(eval + c13 corpus)按 call_digest 分组;
- accepted 唯一性与 attempt 连续性;
- block attempt log 完整性;
- historical binding:git ancestry 语义、merge-base、A′ 链、blob
  identity、R11 证据保留;
- baseline 常量与分支;
- release rehearsal 的重复写入拒绝(轻量单元级;完整 rehearsal 走
  CLI pre-freeze 阶段)。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r12_generation_evidence import (
    BlockAttemptSummary,
    ExpectedCall,
    verify_generation_evidence_completeness,
)
from rl_curriculum.curriculum261_r12_historical import (
    R11_COMMIT_A,
    R11_COMMIT_A_PRIME,
    R12_EXPECTED_BASELINE,
    historical_evidence_binding,
)


def _env(namespace="stress_r12", family="c3_cost", rung="D0", pair=0,
         attempt=0, accepted=True, digest=None, call_digest="cd-1"):
    return {
        "stage": "s", "iteration": "r12", "call_digest": call_digest,
        "envelope": {
            "iteration": "r12", "namespace": namespace,
            "family": family, "rung": rung, "pair_index": pair,
            "attempt_index": attempt, "outer_seed": 12345,
            "accepted": accepted,
            "digest": digest or "x" * 64,
        },
    }


EXPECTED = [ExpectedCall("stress_r12", "c3_cost", "D0", 0)]


def test_complete_pass():
    rows = [
        _env(attempt=0, accepted=False),
        _env(attempt=1, accepted=True),
    ]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert r["pass"], r["problems_sample"]
    assert r["observed_call_invocations"] == 1
    assert r["n_calls_with_accepted"] == 1


def test_missing_call_rejected():
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=[])
    assert not r["pass"]
    assert r["missing_calls"] >= 1


def test_orphan_call_rejected():
    rows = [_env(attempt=0, accepted=True),
            _env(pair=7, attempt=0, accepted=True, call_digest="cd-2")]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]
    assert r["orphan_excess_calls"] >= 1


def test_duplicate_attempt_rejected():
    rows = [_env(attempt=0, accepted=True),
            _env(attempt=0, accepted=True, call_digest="cd-1")]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


def test_no_accepted_rejected():
    rows = [_env(attempt=0, accepted=False)]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


def test_two_accepted_rejected():
    rows = [_env(attempt=0, accepted=True),
            _env(attempt=1, accepted=True)]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


def test_same_coordinate_two_legal_calls():
    """eval records 与 c13 corpus 同坐标两次调用(call_digest 区分)。"""
    rows = [_env(attempt=0, accepted=True, call_digest="cd-a"),
            _env(attempt=0, accepted=True, call_digest="cd-b")]
    expected = [ExpectedCall("stress_r12", "c3_cost", "D0", 0),
                ExpectedCall("stress_r12", "c3_cost", "D0", 0)]
    r = verify_generation_evidence_completeness(
        None, expected, stage_label="s", ledger_rows_override=rows)
    assert r["pass"], r["problems_sample"]
    assert r["observed_call_invocations"] == 2


def test_stage_mismatch_rejected():
    rows = [_env(attempt=0, accepted=True)]
    rows[0]["stage"] = "other"
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


def test_iteration_mismatch_rejected():
    rows = [_env(attempt=0, accepted=True)]
    rows[0]["envelope"]["iteration"] = "r11"
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]
    assert r["iteration_mismatch_rows"] == 1


def test_bad_envelope_digest_rejected():
    rows = [_env(attempt=0, accepted=True, digest="short")]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


def test_block_summary_ok_and_rejected():
    blocks_ok = [BlockAttemptSummary(
        "design_r12_matched_main", 0, 1,
        [{"attempt": 0, "accepted": False, "reason": "x"},
         {"attempt": 1, "accepted": True, "reason": None}])]
    r = verify_generation_evidence_completeness(
        None, [], stage_label="s", blocks=blocks_ok)
    assert r["pass"]
    blocks_bad = [BlockAttemptSummary(
        "design_r12_matched_main", 0, 0,
        [{"attempt": 0, "accepted": True, "reason": None}])]
    # selected=0 合法;构造 selected 后仍有接受的非法例
    blocks_bad2 = [BlockAttemptSummary(
        "design_r12_matched_main", 0, 0,
        [{"attempt": 0, "accepted": True, "reason": None},
         {"attempt": 1, "accepted": True, "reason": None}])]
    r2 = verify_generation_evidence_completeness(
        None, [], stage_label="s", blocks=blocks_bad2)
    assert not r2["pass"]
    blocks_bad3 = [BlockAttemptSummary(
        "design_r12_matched_main", 0, 5,
        [{"attempt": 0, "accepted": True, "reason": None}])]
    r3 = verify_generation_evidence_completeness(
        None, [], stage_label="s", blocks=blocks_bad3)
    assert not r3["pass"]


def _release_repo() -> Path | None:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if (cand / ".git").exists():
            return cand
    return None


def _on_r12_branch() -> bool:
    """R12 binding 的分支检查只在 repair12 分支上下文中有意义。

    R13 起 HEAD 位于后续 repair 分支,R12 模块的 r12_branch_name_ok
    按设计为 False(binding 语义属于 R12 iteration 上下文);R13 的
    等价断言由 test_curriculum261_r13_governance 承担。checkout 到
    repair12 分支时本测试恢复完整执行。
    """
    repo = _release_repo()
    if repo is None:
        return False
    out = subprocess.run(
        ["git", "branch", "--show-current"], cwd=str(repo),
        capture_output=True, text=True)
    return out.stdout.strip() == "route-c-stage2-6-1-repair12"


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达")
class TestHistoricalEvidenceBinding:
    @pytest.mark.skipif(not _on_r12_branch(),
                        reason="非 repair12 分支:R12 binding 的分支检查"
                               "仅在 R12 iteration 上下文有效(R13 起"
                               "由 r13 governance 测试承担)")
    def test_ancestry_semantics_pass(self):
        repo = _release_repo()
        b = historical_evidence_binding(repo)
        assert b["expected_baseline"] == R12_EXPECTED_BASELINE
        # 当前分支从 baseline 创建 ⇒ ancestor/merge-base 全过
        assert b["checks"]["baseline_is_ancestor_of_head"] is True
        assert b["checks"]["merge_base_equals_baseline"] is True
        assert b["ok"] is True, b["failed_checks"]

    def test_r11_chain_anchors(self):
        assert R11_COMMIT_A != R11_COMMIT_A_PRIME
        assert R12_EXPECTED_BASELINE != R11_COMMIT_A
        repo = _release_repo()
        b = historical_evidence_binding(repo)
        c = b["checks"]
        assert c["r11_a_ancestor_of_a_prime"] is True
        assert c["r11_a_prime_ancestor_of_b"] is True
        assert c["r11_clean_chain_invalidated_by_a_prime"] is True
        assert c["r11_final_qualification_not_executed"] is True
        assert c["r11_qualification_exposure_absent"] is True
        assert c["preserved_files_blob_identity_ok"] is True

    def test_baseline_constant_value(self):
        assert R12_EXPECTED_BASELINE == \
            "96446f2f91cd13df0411dc70909dd43ab8864046"

    def test_head_drift_detected(self):
        """人为篡改 head 字段 ⇒ verify 路径的比对基础(单元级:
        binding 对象包含 head,digest 覆盖 head)。"""
        repo = _release_repo()
        b = historical_evidence_binding(repo)
        assert "head" in b
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True).stdout.strip()
        assert b["head"] == head


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达")
class TestFreezeGovernance:
    def test_freeze_writer_then_verify_roundtrip(self, tmp_path):
        from rl_curriculum.curriculum261_r12_dependencies import (
            verify_r12_code_freeze,
            write_r12_code_freeze,
        )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_release_repo()),
            capture_output=True, text=True).stdout.strip()
        doc = write_r12_code_freeze(tmp_path, code_freeze_sha=head)
        assert doc["code_freeze_sha"] == head
        chk = verify_r12_code_freeze(tmp_path)
        assert chk["pass"] is True, chk
        # 重复写入必须被拒绝(不存在 A′ 恢复路径)
        with pytest.raises(RuntimeError):
            write_r12_code_freeze(tmp_path, code_freeze_sha=head)

    def test_freeze_rejects_source_drift(self, tmp_path,
                                         monkeypatch):
        """freeze 记录与当前源码树不一致 ⇒ 拒绝(篡改一个源文件)。
        用 monkeypatch 临时修改模块内存,不改磁盘(冻结前工程验证)。"""
        from rl_curriculum.curriculum261_r12_dependencies import (
            source_tree_digest_r12,
            verify_r12_code_freeze,
            write_r12_code_freeze,
        )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_release_repo()),
            capture_output=True, text=True).stdout.strip()
        write_r12_code_freeze(tmp_path, code_freeze_sha=head)
        real = source_tree_digest_r12

        def fake_drift():
            return {"modules": {}, "source_tree_digest": "0" * 64,
                    "all_present": False}

        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r12_dependencies."
            "source_tree_digest_r12", fake_drift)
        chk = verify_r12_code_freeze(tmp_path)
        assert chk["pass"] is False
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r12_dependencies."
            "source_tree_digest_r12", real)

    def test_no_a_prime_recovery_path(self):
        """CLI 无任何 A′/unfreeze/refreeze 入口(源码扫描)。"""
        import rl_curriculum.curriculum261_r12_cli as cli
        import inspect

        src = inspect.getsource(cli)
        for banned in ("unfreeze", "refreeze", "replace_freeze",
                       "hotfix_after_freeze"):
            assert banned not in src
