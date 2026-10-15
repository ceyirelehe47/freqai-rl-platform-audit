# -*- coding: utf-8 -*-
"""COURSE_CONTRACT_OFFLINE v2 纯数据 fixture 测试。

零模型前向/环境 step/训练/bank 生成;fixtures 为固定提交文件。
"""
import hashlib
import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rl_posctl.skill_p0 import course_contract as cc  # noqa: E402
from rl_posctl.skill_p0 import (                       # noqa: E402
    offline_skill_report as osr)

FX = (pathlib.Path(__file__).parent
      / "fixtures_course_contract")


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def validate(rows, ver=cc.CONTRACT_VERSION, model="new"):
    return cc.validate_grid_rows(
        rows, contract_version=ver, expect_model=model)


def fsha(name):
    return hashlib.sha256(
        (FX / name).read_bytes()).hexdigest()


# ---- 契约事实 -------------------------------------------------
def test_contract_has_course_facts():
    c = cc.build_contract()
    assert c["c1"]["feature_order"] == ["c", "g", "q", "s"]
    assert c["c1"]["grid_conditions"] == 108
    assert c["c1"]["neutral_conditions"] == 36
    assert c["c1"]["direction_gate"]["threshold"] == 0.80
    assert c["c1"]["direction_gate"]["amplitude_edge"] == 0.25
    assert c["c1"]["neutral_gate"]["threshold"] == 0.75
    assert c["c1"]["neutral_gate"]["band"] == 0.10
    assert c["c1"]["held_position_neutral"] == (
        "not_specified")
    assert c["c1"]["initial_state_gate"].startswith(
        "flat counterfactual")
    assert "q" in c["other_courses"]["c3"]["drift_factor"]
    assert "q" in c["other_courses"]["c4d0"]["drift_factor"]
    for k, v in c["other_courses"].items():
        assert v["gates"] == "not_specified"
    # 来源=本机实核,不冒充 candidate
    sb = c["source_binding"]
    assert not any(k.startswith("candidate")
                   for k in c)
    assert len(sb["modules"]["p0spec"]["sha256"]) == 64
    assert sb["modules"]["p0spec"][
        "imported_path"].endswith("p0spec.py")


# ---- grid 校验(含 v2 反例) -----------------------------------
def test_boundary_pass_exact_thresholds():
    info = validate(load("grid_ok_boundary.json"))
    assert info["conditions"] == 108
    ev = cc.skill_eval(load("grid_ok_boundary.json"))
    for k in ("direction_up", "direction_down",
              "neutral_flat"):
        assert ev[k]["status"] == "pass", (k, ev[k])
        assert ev[k]["min"] == pytest.approx(
            ev[k]["threshold"])


def test_one_cell_fail_lists_worst_condition():
    ev = cc.skill_eval(load("grid_one_cell_fail.json"))
    assert ev["neutral_flat"]["status"] == "fail"
    assert ev["neutral_flat"]["min"] < 0.75
    assert len(ev["neutral_flat"]["worst_condition"]) == 5
    assert ev["held_position_neutral"] == "not_specified"


@pytest.mark.parametrize("name,pat", [
    ("grid_missing_cell.json", "condition set mismatch"),
    ("grid_dup_cell.json", "duplicate conditions"),
    ("grid_mixed_model.json", "mixed or missing model"),
    ("grid_bad_layout.json", "obs slots"),
    ("grid_nan_prob.json", "not finite in"),
    ("grid_nonflat_obs.json", "obs slots"),
    ("grid_p_up_2.json", "not finite in"),
    ("grid_obs4_nan.json", "non-finite slot"),
    ("grid_obs6_999.json", "obs slots"),
    ("grid_remaining_frac.json",
     "remaining not integer-valued")])
def test_grid_rejections(name, pat):
    with pytest.raises(cc.ContractError,
                       match=pat):
        validate(load(name))


def test_unknown_contract_version_rejected():
    with pytest.raises(cc.ContractError,
                       match="unknown contract version"):
        validate(load("grid_ok_boundary.json"),
                 ver="COURSE_CONTRACT_V0")


# ---- raw 完整性(v2) ------------------------------------------
def _map_new():
    return {"new": "ckX"}


def test_raw_full_new_valid_and_coverage():
    info = osr.validate_raw_file(
        FX / "raw_full_new.jsonl", fsha("raw_full_new.jsonl"),
        _map_new(), "fx")
    pm = info["per_model"]["new"]
    assert pm["rows"] == 512 and pm["episodes"] == 8
    assert pm["base_pairs"] == [0, 1, 2, 3]
    assert pm["mirror_pairs"] == [0, 1, 2, 3]
    assert pm["account_state_rows"]["flat_pre"] == 512


def test_raw_missing_model_rejected():
    """文件只含 new 而映射要求 {new} 之外的 baseline → 拒。"""
    with pytest.raises(cc.ContractError,
                       match="model set"):
        osr.validate_raw_file(
            FX / "raw_full_new.jsonl",
            fsha("raw_full_new.jsonl"),
            {"new": "ckX", "baseline": "ckY"}, "fx")


def test_raw_missing_exposure_rejected(tmp_path):
    rows = [json.loads(l) for l in (
        FX / "raw_full_new.jsonl").read_text(
        encoding="utf-8").splitlines()]
    del rows[10]["exposure_before"]
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(
        json.dumps(r) for r in rows) + "\n",
        encoding="utf-8")
    with pytest.raises(cc.ContractError,
                       match="exposure_before"):
        osr.validate_raw_file(
            p, hashlib.sha256(
                p.read_bytes()).hexdigest(),
            {"new": "ckX"}, "fx")


def test_raw_early_termination_rejected(tmp_path):
    rows = [json.loads(l) for l in (
        FX / "raw_full_new.jsonl").read_text(
        encoding="utf-8").splitlines()]
    rows[5]["terminated"] = True
    p = tmp_path / "r2.jsonl"
    p.write_text("\n".join(
        json.dumps(r) for r in rows) + "\n",
        encoding="utf-8")
    with pytest.raises(cc.ContractError,
                       match="early termination"):
        osr.validate_raw_file(
            p, hashlib.sha256(
                p.read_bytes()).hexdigest(),
            {"new": "ckX"}, "fx")


def test_raw_econ_failure_rejected(tmp_path):
    rows = [json.loads(l) for l in (
        FX / "raw_full_new.jsonl").read_text(
        encoding="utf-8").splitlines()]
    rows[7]["economic_failure"] = True
    p = tmp_path / "r3.jsonl"
    p.write_text("\n".join(
        json.dumps(r) for r in rows) + "\n",
        encoding="utf-8")
    with pytest.raises(cc.ContractError,
                       match="economic_failure"):
        osr.validate_raw_file(
            p, hashlib.sha256(
                p.read_bytes()).hexdigest(),
            {"new": "ckX"}, "fx")


def test_raw_bool_int_rejected(tmp_path):
    rows = [json.loads(l) for l in (
        FX / "raw_full_new.jsonl").read_text(
        encoding="utf-8").splitlines()]
    rows[3]["pair_index"] = True
    p = tmp_path / "r4.jsonl"
    p.write_text("\n".join(
        json.dumps(r) for r in rows) + "\n",
        encoding="utf-8")
    with pytest.raises(cc.ContractError,
                       match="bad pair_index"):
        osr.validate_raw_file(
            p, hashlib.sha256(
                p.read_bytes()).hexdigest(),
            {"new": "ckX"}, "fx")


def test_raw_s_out_of_domain_rejected():
    with pytest.raises(cc.ContractError,
                       match=r"s invalid \(not in"):
        osr.validate_raw_file(
            FX / "raw_s2_first.jsonl",
            fsha("raw_s2_first.jsonl"),
            {"new": "ckX"}, "fx")


def test_raw_reversed_order_passes_same_stats():
    """反序完整 raw 必须通过且统计与正序一致。"""
    fwd = osr.validate_raw_file(
        FX / "raw_full_new.jsonl",
        fsha("raw_full_new.jsonl"), {"new": "ckX"}, "fx")
    rev = osr.validate_raw_file(
        FX / "raw_reversed.jsonl",
        fsha("raw_reversed.jsonl"), {"new": "ckX"}, "fx")
    assert rev["per_model"] == fwd["per_model"]
    assert rev["per_model"]["new"]["rows"] == 512
    assert rev["per_model"]["new"]["episodes"] == 8


def test_raw_pseudo_model_rejected():
    with pytest.raises(cc.ContractError,
                       match="pseudo model"):
        osr.validate_raw_file(
            FX / "raw_pseudo_model.jsonl",
            fsha("raw_pseudo_model.jsonl"), _map_new(),
            "fx")


def test_raw_pair99_onerow_rejected():
    with pytest.raises(cc.ContractError):
        osr.validate_raw_file(
            FX / "raw_pair99_onerow.jsonl",
            fsha("raw_pair99_onerow.jsonl"), _map_new(),
            "fx")


# ---- manifest 驱动入口 ----------------------------------------
def _manifest(tmp_path, *, grids=None, raws=None,
              bank=None, schema=None, course_id="c1",
              extra_expected=None):
    """schema=None→legacy(仅 golden 允许,测试经注入表放行)。"""
    if bank is None:
        bank = (__file__, hashlib.sha256(
            pathlib.Path(__file__).read_bytes()
        ).hexdigest())
    g = grids if grids is not None else [{
        "tier": "ck262144",
        "path": str(FX / "grid_ok_boundary.json"),
        "sha": fsha("grid_ok_boundary.json"),
        "model": "new", "ckpt_sha": "c" * 64}]
    r = raws if raws is not None else [{
        "label": "fx", "path": str(
            FX / "raw_full_new.jsonl"),
        "sha": fsha("raw_full_new.jsonl"),
        "models": {"new": "ck262144"}}]
    m = {"contract_version": cc.CONTRACT_VERSION,
         "bank": {"path": bank[0], "sha": bank[1]},
         "grids": g, "raws": r}
    if schema == "C1":
        m["manifest_schema"] = "MANIFEST_C1_V1"
        m["course_id"] = course_id
        if extra_expected is None:
            m["expected_tiers"] = ["ck262144"]
            m["expected_ckpt"] = {"ck262144": "c" * 64}
            m["expected_raw_labels"] = ["fx"]
            m["expected_raw_models"] = {
                "fx": {"new": "ck262144"}}
    elif schema is not None:
        m["manifest_schema"] = schema
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(m), encoding="utf-8")
    return mp, hashlib.sha256(
        mp.read_bytes()).hexdigest()


def _trust(msha, course_id="c1"):
    return [{"sha256": msha, "kind": "test_injected",
             "course_id": course_id}]


def _fake_bank(monkeypatch):
    import rl_posctl.skill_p0.p0banks as pb

    class FakeFeats:
        columns = ["c", "g", "q", "s"]

    monkeypatch.setattr(
        pb, "load_p0_bank",
        lambda p: [(None, FakeFeats(),
                    {"pair_index": 0, "variant": 0})])


def test_entry_c1_schema_pass_and_refuses_overwrite(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    out = tmp_path / "rep"
    rc1 = osr.main(["--manifest", str(mp),
                    "--out", str(out)],
                   trusted_entries=_trust(msha))
    assert rc1 == 0
    first = (out / "offline_skill_report.json").read_text(
        encoding="utf-8")
    rc2 = osr.main(["--manifest", str(mp),
                    "--out", str(out)],
                   trusted_entries=_trust(msha))
    assert rc2 == osr.RC_INVALID
    assert (out / "offline_skill_report.json").read_text(
        encoding="utf-8") == first


def test_entry_candidate_rejected_in_production(
        tmp_path, monkeypatch):
    """注入可接入;生产 CLI(默认信任表)拒同候选。"""
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    out1 = tmp_path / "inj"
    assert osr.main(["--manifest", str(mp),
                     "--out", str(out1)],
                    trusted_entries=_trust(msha)) == 0
    # 生产默认信任表(golden)下同 manifest -> not trusted
    out2 = tmp_path / "prod"
    assert osr.main(["--manifest", str(mp),
                     "--out", str(out2)]) == (
        osr.RC_INVALID)
    rep = json.loads((out2 / "offline_skill_report.json")
                     .read_text(encoding="utf-8"))
    assert "not in trusted table" in rep["error"]


def test_entry_empty_set_invalid(tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, grids=[], raws=[],
                         schema="C1")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r1")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_missing_declared_tier_invalid(
        tmp_path, monkeypatch):
    """声明 expected 含 ck999999 但 grids 缺该档→拒(缺档)。"""
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "c" * 64}
    r1 = {"label": "fx",
          "path": str(FX / "raw_full_new.jsonl"),
          "sha": fsha("raw_full_new.jsonl"),
          "models": {"new": "ck262144"}}
    mp, msha = _manifest(
        tmp_path, grids=[g1], raws=[r1], schema="C1",
        extra_expected={
            "expected_tiers": ["ck262144", "ck999999"],
            "expected_ckpt": {"ck262144": "c" * 64,
                              "ck999999": "d" * 64},
            "expected_raw_labels": ["fx"],
            "expected_raw_models": {
                "fx": {"new": "ck262144"}}})
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "rs")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_duplicate_raw_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    r1 = {"label": "fx",
          "path": str(FX / "raw_full_new.jsonl"),
          "sha": fsha("raw_full_new.jsonl"),
          "models": {"new": "ck262144"}}
    mp, msha = _manifest(tmp_path, raws=[r1, dict(r1)],
                         schema="C1")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "rd")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_deadbeef_ckpt_rejected_by_structure(
        tmp_path, monkeypatch):
    """deadbeef ckpt 与声明 expected_ckpt 冲突→拒。"""
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "deadbeef"}
    mp, msha = _manifest(tmp_path, grids=[g1],
                         schema="C1")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "rf")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_unknown_schema_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="MANIFEST_X9")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "ru")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_manifest_trust_key_rejected(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["trust_source"] = "self"
    mp.write_text(json.dumps(m), encoding="utf-8")
    msha2 = hashlib.sha256(
        mp.read_bytes()).hexdigest()
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "rt")],
                  trusted_entries=_trust(msha2))
    assert rc == osr.RC_INVALID


def test_entry_non_c1_cannot_pass(tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1",
                         course_id="c2")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "rc2")],
                  trusted_entries=_trust(
                      msha, course_id="c2"))
    assert rc != 0  # 非 C1 不能整体 pass
    rep = json.loads((tmp_path / "rc2" /
                      "offline_skill_report.json").read_text(
        encoding="utf-8"))
    assert rep["status"] != "pass"


def test_entry_unverified_ckpt_rejected(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1",
                         extra_expected=None)
    # 改 ckpt 为 UNVERIFIED 并同步 expected
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["grids"][0]["ckpt_sha"] = "UNVERIFIED"
    m["expected_ckpt"]["ck262144"] = "UNVERIFIED"
    mp.write_text(json.dumps(m), encoding="utf-8")
    rc = osr.main(
        ["--manifest", str(mp),
         "--out", str(tmp_path / "uv")],
        trusted_entries=_trust(hashlib.sha256(
            mp.read_bytes()).hexdigest()))
    assert rc == osr.RC_INVALID


def test_entry_raw_to_nonexistent_tier_rejected(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["raws"][0]["models"] = {"new": "ckNOPE"}
    mp.write_text(json.dumps(m), encoding="utf-8")
    rc = osr.main(
        ["--manifest", str(mp),
         "--out", str(tmp_path / "np")],
        trusted_entries=_trust(hashlib.sha256(
            mp.read_bytes()).hexdigest()))
    assert rc == osr.RC_INVALID


def test_entry_partial_coverage_rejected(
        tmp_path, monkeypatch):
    """两档 grid 但 raw 只覆盖一档→拒(并集恰覆盖)。"""
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "c" * 64}
    g2 = {"tier": "ck999999",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "d" * 64}
    r1 = {"label": "fx",
          "path": str(FX / "raw_full_new.jsonl"),
          "sha": fsha("raw_full_new.jsonl"),
          "models": {"new": "ck262144"}}
    mp, msha = _manifest(
        tmp_path, grids=[g1, g2], raws=[r1], schema="C1",
        extra_expected={
            "expected_tiers": ["ck262144", "ck999999"],
            "expected_ckpt": {"ck262144": "c" * 64,
                              "ck999999": "d" * 64},
            "expected_raw_labels": ["fx"],
            "expected_raw_models": {
                "fx": {"new": "ck262144"}}})
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "pc")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_untrusted_marker_rejected(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["untrusted_candidate"] = True
    mp.write_text(json.dumps(m), encoding="utf-8")
    rc = osr.main(
        ["--manifest", str(mp),
         "--out", str(tmp_path / "ut")],
        trusted_entries=_trust(hashlib.sha256(
            mp.read_bytes()).hexdigest()))
    assert rc == osr.RC_INVALID


def test_entry_single_tier_c1_with_full_cover_pass(
        tmp_path, monkeypatch):
    """合法单档 C1(grid/raw 映射恰覆盖)必须通过。"""
    _fake_bank(monkeypatch)
    mp, msha = _manifest(tmp_path, schema="C1")
    out = tmp_path / "ok1"
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(out)],
                  trusted_entries=_trust(msha))
    assert rc == 0


def test_trusted_table_missing_corrupt(monkeypatch, tmp_path):
    bad = tmp_path / "trusted_manifests.json"
    rc = osr.main(
        ["--manifest", str(tmp_path / "any.json"),
         "--out", str(tmp_path / "x1")])
    assert rc == osr.RC_INVALID  # 生产默认表缺失→fail closed
    bad.write_text("{corrupt", encoding="utf-8")
    # 外部替换尝试:入口按 __file__ 定位,不受 cwd/环境表影响;
    # 模拟包内表损坏经内部路径验证
    with pytest.raises(cc.ContractError,
                       match="fail-closed"):
        osr._load_trusted_entries(
            trusted_path=bad)


def _tt(entries):
    p = pathlib.Path(
        osr.__file__).parent / "trusted_manifests.json"
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    f = d / "t.json"
    f.write_text(json.dumps(
        {"schema": "TRUSTED_MANIFESTS_V1",
         "entries": entries}), encoding="utf-8")
    return f


def test_trusted_entry_missing_approved_by():
    f = _tt([{"sha256": "a" * 64, "kind": "k",
              "course_id": "c1"}])
    with pytest.raises(cc.ContractError,
                       match="approved_by"):
        osr._load_trusted_entries(trusted_path=f)


def test_trusted_entry_dup_sha_conflict():
    e = {"sha256": "a" * 64, "kind": "k",
         "course_id": "c1",
         "approved_by": {"channel": "C1", "ts": "1"}}
    f = _tt([e, dict(e, course_id="c2")])
    with pytest.raises(cc.ContractError,
                       match="duplicate sha"):
        osr._load_trusted_entries(trusted_path=f)


def test_trusted_entry_bad_approved_by_text():
    """非空文字≠真实性:approved_by 必须是结构化引用。"""
    f = _tt([{"sha256": "a" * 64, "kind": "k",
              "course_id": "c1",
              "approved_by": "approved"}])
    with pytest.raises(cc.ContractError,
                       match="approved_by"):
        osr._load_trusted_entries(trusted_path=f)


def test_emit_candidate_proposal_only(
        tmp_path, monkeypatch):
    out = tmp_path / "cand.json"
    rc = osr.main([
        "--emit-candidate", "--out", str(out),
        "--grid", "ckX|%s|new" % (
            FX / "grid_ok_boundary.json"),
        "--raw", "fx|%s|new" % (
            FX / "raw_full_new.jsonl")])
    assert rc == 0
    cand = json.loads(out.read_text(encoding="utf-8"))
    assert cand["untrusted_candidate"] is True
    assert "PROPOSAL ONLY" in cand["watermark"]
    assert cand["grids"][0][
        "ckpt_sha"] == "UNVERIFIED(review fills)"
    # 不改信任表
    tpath = (pathlib.Path(
        osr.__file__).parent / "trusted_manifests.json")
    assert json.loads(tpath.read_text(
        encoding="utf-8"))["entries"][0][
        "sha256"] == osr.GOLDEN_SHA
    # 拒绝覆盖既有输出
    rc2 = osr.main([
        "--emit-candidate", "--out", str(out),
        "--grid", "ckX|%s|new" % (
            FX / "grid_ok_boundary.json"),
        "--raw", "fx|%s|new" % (
            FX / "raw_full_new.jsonl")])
    assert rc2 == 3


def test_entry_duplicate_tier_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "c" * 64}
    mp, msha = _manifest(tmp_path, grids=[g1, dict(g1)],
                         schema="C1")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r2")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID


def test_entry_deadbeef_grid_sha_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": "deadbeef" + "0" * 56,
          "model": "new", "ckpt_sha": "c" * 64}
    mp, msha = _manifest(tmp_path, grids=[g1],
                         schema="C1")
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r3")],
                  trusted_entries=_trust(msha))
    assert rc == osr.RC_INVALID
    rep = json.loads((tmp_path / "r3" /
                      "offline_skill_report.json").read_text(
        encoding="utf-8"))
    assert rep["status"] == "invalid"
