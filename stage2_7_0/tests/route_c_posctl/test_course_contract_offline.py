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
              bank=None):
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
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(m), encoding="utf-8")
    return mp


def _fake_bank(monkeypatch):
    import rl_posctl.skill_p0.p0banks as pb

    class FakeFeats:
        columns = ["c", "g", "q", "s"]

    monkeypatch.setattr(
        pb, "load_p0_bank",
        lambda p: [(None, FakeFeats(),
                    {"pair_index": 0, "variant": 0})])


def test_entry_pass_and_refuses_overwrite(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp = _manifest(tmp_path)
    out = tmp_path / "rep"
    rc1 = osr.main(["--manifest", str(mp),
                    "--out", str(out)])
    assert rc1 == 0
    first = (out / "offline_skill_report.json").read_text(
        encoding="utf-8")
    rc2 = osr.main(["--manifest", str(mp),
                    "--out", str(out)])
    assert rc2 == osr.RC_INVALID
    assert (out / "offline_skill_report.json").read_text(
        encoding="utf-8") == first


def test_entry_empty_set_invalid(tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    mp = _manifest(tmp_path, grids=[], raws=[])
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r1")])
    assert rc == osr.RC_INVALID


def test_entry_duplicate_tier_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": fsha("grid_ok_boundary.json"),
          "model": "new", "ckpt_sha": "c" * 64}
    mp = _manifest(tmp_path, grids=[g1, dict(g1)])
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r2")])
    assert rc == osr.RC_INVALID


def test_entry_deadbeef_grid_sha_invalid(
        tmp_path, monkeypatch):
    _fake_bank(monkeypatch)
    g1 = {"tier": "ck262144",
          "path": str(FX / "grid_ok_boundary.json"),
          "sha": "deadbeef" + "0" * 56,
          "model": "new", "ckpt_sha": "c" * 64}
    mp = _manifest(tmp_path, grids=[g1])
    rc = osr.main(["--manifest", str(mp),
                   "--out", str(tmp_path / "r3")])
    assert rc == osr.RC_INVALID
    rep = json.loads((tmp_path / "r3" /
                      "offline_skill_report.json").read_text(
        encoding="utf-8"))
    assert rep["status"] == "invalid"
