"""GOAL §4 C3 finite-reserve contract tests (no skip/mock of downstream math).

Evidence validation uses the exact envelope shape of the deterministic
rt3 c3_cost/D0/pair52 structural exhaustion (five attempts, vocabulary
rejections only), as dumped by the R17 §11 failure-evidence path.
"""
from __future__ import annotations

import pytest

from rl_curriculum import curriculum261_r17_c3_finite_reserve as fr
from rl_curriculum.curriculum261_api import PairGenerationError
from rl_curriculum.curriculum261_c3 import C3_REJECT_VOCAB


def _envelope(index: int, *, accepted=False, reasons=None, exception=None):
    reasons = ['A:too_few_distractors', 'B:too_few_distractors',
               'pair:too_few_distractors'] if reasons is None else reasons
    return {
        "attempt_index": index, "accepted": accepted,
        "exception": exception, "rejection_reasons": list(reasons),
        "family": "c3_cost", "rung": "D0", "pair_index": 52,
        "namespace": "rt3_calibration_main_r17",
    }


def _exc(envelopes, max_attempts=5):
    return PairGenerationError(
        "structural", attempt_envelopes=envelopes,
        call_envelope={"max_attempts": max_attempts})


def test_reserve_indices_are_disjoint_deterministic_and_bounded():
    assert fr.reserve_index(0, 0) == fr.RESERVE_INDEX_BASE
    assert fr.reserve_index(52, 0) == 1104
    assert fr.reserve_index(52, 1) == 1105
    used = {fr.reserve_index(i, s)
            for i in range(60) for s in range(fr.RESERVE_SLOTS_PER_COORDINATE)}
    assert len(used) == 120 and not (used & set(range(60)))
    with pytest.raises(ValueError):
        fr.reserve_index(fr.RESERVE_INDEX_BASE, 0)
    with pytest.raises(ValueError):
        fr.reserve_index(0, fr.RESERVE_SLOTS_PER_COORDINATE)


def test_declaration_covers_full_grid_and_frozen_vocabulary():
    d = fr.reserve_declaration("ns_x", 60)
    assert d["contract"] == fr.RESERVE_CONTRACT
    assert d["main_indices"] == list(range(60))
    assert set(d["allowed_rejection_vocabulary"]) == set(C3_REJECT_VOCAB)
    assert len(d["reserve_indices"]) == 4 * 60
    assert all(len(v) == fr.RESERVE_SLOTS_PER_COORDINATE
               for v in d["reserve_indices"].values())


def test_real_p52_shaped_evidence_is_structural_exhaustion():
    evidence = fr.structural_exhaustion_evidence(
        _exc([_envelope(i) for i in range(5)]))
    assert evidence is not None
    assert evidence["n_attempts"] == 5
    assert evidence["coordinate"] == {
        "family": "c3_cost", "rung": "D0", "pair_index": 52,
        "namespace": "rt3_calibration_main_r17"}
    assert len(evidence["evidence_digest"]) == 64


@pytest.mark.parametrize("mutation", [
    "empty", "short", "accepted", "exception", "foreign_reason",
    "duplicate_index", "no_call_max", "bare_reason_ok",
])
def test_evidence_completeness_rules(mutation):
    envelopes = [_envelope(i) for i in range(5)]
    max_attempts = 5
    if mutation == "empty":
        envelopes = []
    elif mutation == "short":
        envelopes = envelopes[:4]
    elif mutation == "accepted":
        envelopes[2] = _envelope(2, accepted=True)
    elif mutation == "exception":
        envelopes[2] = _envelope(2, exception="GeneratorError: boom")
    elif mutation == "foreign_reason":
        envelopes[2] = _envelope(2, reasons=["A:pnl_too_low"])
    elif mutation == "duplicate_index":
        envelopes[2] = _envelope(1)
    elif mutation == "no_call_max":
        max_attempts = None
    elif mutation == "bare_reason_ok":
        envelopes[2] = _envelope(2, reasons=["too_few_distractors"])
    evidence = fr.structural_exhaustion_evidence(
        _exc(envelopes, max_attempts=max_attempts)
        if max_attempts is not None else
        PairGenerationError("x", attempt_envelopes=envelopes))
    if mutation == "bare_reason_ok":
        assert evidence is not None
    else:
        assert evidence is None


class _Rec:
    def __init__(self, idx):
        self.pair_index = idx


def test_substitution_only_on_evidenced_exhaustion(monkeypatch):
    import rl_curriculum.curriculum261_pairs as pairs
    calls = []

    def fake_generate(family, rung, idx, *, namespace, rung_params_override=None):
        calls.append((family, rung, idx))
        if idx == 52:
            raise _exc([_envelope(i) for i in range(5)])
        return _Rec(idx)

    monkeypatch.setattr(pairs, "generate_pair", fake_generate)
    log = []
    rec = fr.generate_c3_pair_with_finite_reserve(
        "D0", 52, namespace="ns", override={}, reserve_log=log)
    assert rec.pair_index == fr.reserve_index(52, 0)
    assert [e["event"] for e in log] == [
        "main_structural_exhaustion", "reserve_substituted"]
    assert log[1]["main_index"] == 52 and log[1]["reserve_index"] == 1104


def test_budget_exhaustion_reraises_and_unknown_never_retried(monkeypatch):
    import rl_curriculum.curriculum261_pairs as pairs

    def always_fails(family, rung, idx, *, namespace, rung_params_override=None):
        raise _exc([_envelope(i) for i in range(5)])

    monkeypatch.setattr(pairs, "generate_pair", always_fails)
    log = []
    with pytest.raises(PairGenerationError):
        fr.generate_c3_pair_with_finite_reserve(
            "D0", 7, namespace="ns", override={}, reserve_log=log)
    assert len(log) == 1 + fr.RESERVE_SLOTS_PER_COORDINATE

    def unknown(family, rung, idx, *, namespace, rung_params_override=None):
        raise PairGenerationError("unknown", attempt_envelopes=[])

    monkeypatch.setattr(pairs, "generate_pair", unknown)
    with pytest.raises(PairGenerationError):
        fr.generate_c3_pair_with_finite_reserve(
            "D0", 7, namespace="ns", override={}, reserve_log=[])


def test_completeness_verifier_exempts_evidenced_exhaustion():
    from rl_curriculum.curriculum261_r17_generation_evidence import (
        ExpectedCall, verify_generation_evidence_completeness)

    def env(idx, *, accepted, pair_index):
        return {"iteration": "r17", "namespace": "ns", "family": "c3_cost",
                "rung": "D0", "pair_index": pair_index,
                "attempt_index": idx, "outer_seed": 1,
                "digest": "d" * 32, "accepted": accepted, "exception": None}

    rows = [{"stage": "s", "envelope": env(i, accepted=False, pair_index=52)}
            for i in range(5)]
    rows.append({"stage": "s",
                 "envelope": env(0, accepted=True, pair_index=1104)})
    expected = [ExpectedCall("ns", "c3_cost", "D0", 52),
                ExpectedCall("ns", "c3_cost", "D0", 1104)]
    exempt = {("ns", "c3_cost", "D0", 52): {
        "source": "main", "evidence_digest": "x" * 64}}
    result = verify_generation_evidence_completeness(
        None, expected, stage_label="s", ledger_rows_override=rows,
        evidenced_exhausted=exempt)
    assert result["pass"] is True
    assert result["exempted_exhausted_calls"] == 1
    baseline = verify_generation_evidence_completeness(
        None, expected, stage_label="s", ledger_rows_override=rows)
    assert baseline["pass"] is False
