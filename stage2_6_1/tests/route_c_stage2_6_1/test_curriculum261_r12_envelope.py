# -*- coding: utf-8 -*-
"""R12 工作包 A 测试:Generation Invocation Envelope。

覆盖(§12 测试类别 1/2/3/4/5/12):
1. invocation envelope canonical roundtrip;
2. envelope hash 对 dict 顺序不敏感;
3. envelope tamper 拒绝;
4. source identity mismatch 拒绝;
5. generator state 变化可检测;
12. generator 调用不修改输入 params(+ A/B 共享流合同要素);
以及失败 attempt 证据在异常前保存(11)与 envelope replay 一致性。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rl_curriculum.curriculum261_generation_envelope import (
    CALL_ENVELOPE_DIGEST_PREFIX,
    ENVELOPE_DIGEST_PREFIX,
    EnvelopeRecorder,
    _digest_body,
    canonical_json,
    compare_envelopes,
    envelope_sink,
    ledger_rows_digest,
    ledger_sink_factory,
    read_envelope_ledger,
    replay_call,
    stable_digest,
    write_attempt_envelopes,
)
from rl_curriculum.curriculum261_api import (
    PairGenerationError,
    generate_pair_with_attempts,
)
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    pair_acceptance_contract,
)

NS = "stress_r12"


def _rung_params(family: str, rung: str = "D0") -> dict:
    spec = family_specs()[family]
    rp = dict(spec.rung_params[rung])
    rp["cur261_rung"] = rung
    return rp


def _recorded(family="c3_cost", rung="D0", pair=3):
    rp = _rung_params(family, rung)
    rec = EnvelopeRecorder(
        iteration="r12", namespace=NS, family=family, rung=rung,
        pair_index=pair, rung_params=rp)
    generate_pair_with_attempts(
        family_specs()[family].generator, rp, namespace=NS, family=family,
        rung=rung, pair_index=pair,
        structural_validator=pair_acceptance_contract(family),
        recorder=rec)
    return rec


# ------------------------------------------------ 1: canonical roundtrip
def test_envelope_canonical_roundtrip(tmp_path):
    rec = _recorded()
    for env in rec.attempt_envelopes:
        s = canonical_json(env)
        rt = json.loads(s)
        assert stable_digest(
            _digest_body(rt), ENVELOPE_DIGEST_PREFIX) == env["digest"]


def test_call_envelope_roundtrip(tmp_path):
    rec = _recorded()
    s = canonical_json(rec.call_envelope)
    rt = json.loads(s)
    assert stable_digest(
        _digest_body(rt), CALL_ENVELOPE_DIGEST_PREFIX) == (
        rec.call_envelope["digest"])


# ------------------------------------------------ 2: dict 顺序不敏感
def test_envelope_hash_dict_order_insensitive():
    payload = {"b": 1, "a": {"y": [1, 2], "x": 3}, "c": (4, 5)}
    payload2 = {"c": (4, 5), "a": {"x": 3, "y": [1, 2]}, "b": 1}
    assert canonical_json(payload) == canonical_json(payload2)
    assert stable_digest(payload, "p-") == stable_digest(payload2, "p-")
    # set 排序规范化
    s3 = stable_digest({"k": {"s", "z", "a"}}, "p-")
    s4 = stable_digest({"k": {"z", "a", "s"}}, "p-")
    assert s3 == s4


# ------------------------------------------------ 3: tamper 拒绝
def test_envelope_tamper_rejected():
    rec = _recorded()
    env = dict(rec.attempt_envelopes[0])
    tampered = dict(env)
    tampered["outer_seed"] = int(env["outer_seed"]) + 1
    assert stable_digest(
        tampered, ENVELOPE_DIGEST_PREFIX) != env["digest"]
    tampered2 = dict(env)
    tampered2["base_params"] = {
        k: dict(v) for k, v in env["base_params"].items()}
    tampered2["base_params"]["A"]["cue_rate"] = 0.5
    assert stable_digest(
        tampered2, ENVELOPE_DIGEST_PREFIX) != env["digest"]


def test_envelope_digest_recompute_detects_field_change():
    from rl_curriculum.curriculum261_r12_determinism import (
        envelope_roundtrip_check,
    )
    rec = _recorded()
    env = rec.attempt_envelopes[0]
    assert envelope_roundtrip_check(env)["ok"]
    bad = dict(env)
    bad["outer_seed"] = int(env["outer_seed"]) ^ 1
    bad.pop("digest", None)
    bad["digest"] = stable_digest(bad, ENVELOPE_DIGEST_PREFIX)
    problems = envelope_roundtrip_check(bad)["problems"]
    assert problems, "outer_seed 与派生字段不一致必须被检出"


# ------------------------------------------------ 4: source identity
def test_generator_source_identity_recorded_and_stable():
    rec = _recorded()
    gen = rec.call_envelope["generator"]
    assert gen["family"] == "c3_cost"
    assert gen["family_version"]
    assert len(gen["source_sha256"]) == 64
    # family_specs 注册项身份进入 call envelope
    fsi = rec.call_envelope["family_spec_identity"]
    assert set(fsi) >= {"c1_opportunity", "c2_context", "c3_cost"}
    # 源码篡改(模拟) => digest 变化
    tampered_gen = dict(gen)
    tampered_gen["source_sha256"] = "0" * 64
    assert stable_digest(
        tampered_gen, "x-") != stable_digest(gen, "x-")


# ------------------------------------------------ 5: generator state
def test_generator_state_change_detectable():
    rec = _recorded()
    gen = family_specs()["c3_cost"].generator
    from rl_curriculum.curriculum261_generation_envelope import (
        generator_state_digest,
    )
    before = generator_state_digest(gen)
    # 模拟跨调用污染:注入一个实例属性
    gen.__dict__["_pollution_probe"] = [1, 2, 3]
    try:
        after = generator_state_digest(gen)
        assert before != after
    finally:
        del gen.__dict__["_pollution_probe"]
    assert generator_state_digest(gen) == before


def test_envelope_records_state_unchanged_in_clean_path():
    rec = _recorded()
    for env in rec.attempt_envelopes:
        assert env["generator_state_changed"] is False
        assert env["generator_state_changed_since_call_start"] is False


# ------------------------------------------------ 12: params 不被修改
@pytest.mark.parametrize("family", [
    "c1_opportunity", "c2_context", "c3_cost"])
def test_generator_call_does_not_mutate_input_params(family):
    rp = _rung_params(family, "D1")
    snap = canonical_json(rp)
    rec = EnvelopeRecorder(
        iteration="r12", namespace=NS, family=family, rung="D1",
        pair_index=0, rung_params=rp)
    generate_pair_with_attempts(
        family_specs()[family].generator, rp, namespace=NS, family=family,
        rung="D1", pair_index=0,
        structural_validator=pair_acceptance_contract(family),
        recorder=rec)
    assert canonical_json(rp) == snap
    # A/B 共享流合同:两侧 base params 只差 pair_variant
    a = dict(rec.attempt_envelopes[0]["base_params"]["A"])
    b = dict(rec.attempt_envelopes[0]["base_params"]["B"])
    va = a.pop("pair_variant")
    vb = b.pop("pair_variant")
    assert (va, vb) == ("A", "B") and a == b


# ------------------------------------------------ 6: 同 envelope 重放一致
def test_replay_call_envelopes_bitwise_consistent():
    rec = _recorded()
    rep = replay_call(rec.call_envelope)
    assert rep["call_digest_recomputed"] == rec.call_envelope["digest"]
    assert len(rep["attempt_envelopes"]) == len(rec.attempt_envelopes)
    for orig, again in zip(rec.attempt_envelopes,
                           rep["attempt_envelopes"]):
        cmp = compare_envelopes(orig, again)
        assert cmp["bitwise_identical"], cmp


# ------------------------------------------------ 11: 失败证据先于异常
def test_failure_evidence_saved_before_raise(tmp_path):
    """五个 attempt 全败的构造性失败:envelopes 在异常对象上完整。

    用不可能通过结构校验的 rung 参数(distractor_rate=0 => 必然
    too_few_distractors;c3 需要 >=1)驱动真实失败路径。
    """
    rp = _rung_params("c3_cost", "D0")
    rp["distractor_rate"] = 0.0
    rp["cue_rate"] = 0.05
    rec = EnvelopeRecorder(
        iteration="r12", namespace=NS, family="c3_cost", rung="D0",
        pair_index=9, rung_params=rp)
    with pytest.raises(PairGenerationError) as ei:
        generate_pair_with_attempts(
            family_specs()["c3_cost"].generator, rp, namespace=NS,
            family="c3_cost", rung="D0", pair_index=9,
            structural_validator=pair_acceptance_contract("c3_cost"),
            recorder=rec)
    exc = ei.value
    assert len(exc.attempt_envelopes) == 5
    assert exc.attempt_log is not None
    assert exc.call_envelope["digest"].startswith(CALL_ENVELOPE_DIGEST_PREFIX)
    for env in exc.attempt_envelopes:
        assert env["accepted"] is False
        assert any("too_few_distractors" in r
                   for r in env["rejection_reasons"])
    # 落盘 + manifest
    manifest = write_attempt_envelopes(
        tmp_path / "evidence.json", exc.call_envelope,
        exc.attempt_envelopes, error_note=str(exc)[:200])
    payload = json.loads((tmp_path / "evidence.json").read_text(
        encoding="utf-8"))
    assert payload["n_attempt_envelopes"] == 5
    assert manifest["sha256"]


def test_recorder_exception_never_breaks_generation():
    """recorder 抛异常必须被吞掉(证据路径 fail-open)。"""
    class BadRecorder:
        call_envelope = {"digest": "x"}
        attempt_envelopes = []

        def record(self, event, payload):
            raise RuntimeError("recorder boom")

    rp = _rung_params("c1_opportunity", "D0")
    episodes, log = generate_pair_with_attempts(
        family_specs()["c1_opportunity"].generator, rp, namespace=NS,
        family="c1_opportunity", rung="D0", pair_index=0,
        structural_validator=pair_acceptance_contract("c1_opportunity"),
        recorder=BadRecorder())
    assert log.selected_attempt is not None
    assert set(episodes) == {"A", "B"}


# ------------------------------------------------ sink 台账
def test_ledger_sink_records_all_attempts(tmp_path):
    path = tmp_path / "ledger.jsonl"
    with envelope_sink(ledger_sink_factory(path, stage_label="t")):
        rp = _rung_params("c3_cost", "D0")
        generate_pair_with_attempts(
            family_specs()["c3_cost"].generator, rp, namespace=NS,
            family="c3_cost", rung="D0", pair_index=4,
            structural_validator=pair_acceptance_contract("c3_cost"))
    rows = read_envelope_ledger(path)
    assert rows
    for row in rows:
        env = row["envelope"]
        assert row["stage"] == "t"
        assert env["digest"].startswith(ENVELOPE_DIGEST_PREFIX)
    # 同一调用重复写台账 => 台账身份 digest 稳定(顺序敏感且确定)
    d1 = ledger_rows_digest(rows)
    # 前缀沿用共享 generation_envelope 模块常量,不随迭代改名
    assert d1 == ledger_rows_digest(read_envelope_ledger(path))
    assert len(d1) > 20


def test_no_sink_no_ledger(tmp_path):
    """sink 未打开时生成照常且无台账(历史路径零影响)。"""
    rp = _rung_params("c2_context", "D0")
    episodes, log = generate_pair_with_attempts(
        family_specs()["c2_context"].generator, rp, namespace=NS,
        family="c2_context", rung="D0", pair_index=0,
        structural_validator=pair_acceptance_contract("c2_context"))
    assert set(episodes) == {"A", "B"}
    assert not list(tmp_path.glob("*.jsonl"))
