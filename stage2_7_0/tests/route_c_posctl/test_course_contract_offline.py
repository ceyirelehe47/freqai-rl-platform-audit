# -*- coding: utf-8 -*-
"""COURSE_CONTRACT_OFFLINE_V1 纯数据 fixture 测试。

零模型前向/环境 step/训练/bank 生成;fixtures 为固定提交文件。
"""
import importlib.util
import json
import math
import pathlib
import subprocess
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


def test_boundary_pass_exact_thresholds():
    info = validate(load("grid_ok_boundary.json"))
    assert info["conditions"] == 108
    ev = cc.skill_eval(load("grid_ok_boundary.json"))
    for k in ("direction_up", "direction_down",
              "neutral_flat"):
        assert ev[k]["status"] == "pass", (k, ev[k])
        # 恰在阈值(>=)必须过
        assert ev[k]["min"] == pytest.approx(
            ev[k]["threshold"])


def test_one_cell_fail_lists_worst_condition():
    rows = load("grid_one_cell_fail.json")
    ev = cc.skill_eval(rows)
    assert ev["neutral_flat"]["status"] == "fail"
    assert ev["neutral_flat"]["min"] < 0.75
    assert len(ev["neutral_flat"]["worst_condition"]) == 5
    assert ev["direction_up"]["status"] == "pass"
    assert ev["held_position_neutral"] == "not_specified"


def test_missing_cell_rejected():
    with pytest.raises(cc.ContractError,
                       match="condition set mismatch"):
        validate(load("grid_missing_cell.json"))


def test_duplicate_cell_rejected():
    with pytest.raises(cc.ContractError,
                       match="duplicate conditions"):
        validate(load("grid_dup_cell.json"))


def test_mixed_model_rejected():
    with pytest.raises(cc.ContractError,
                       match="mixed or missing model"):
        validate(load("grid_mixed_model.json"))


def test_bad_layout_rejected():
    with pytest.raises(cc.ContractError,
                       match="obs layout not"):
        validate(load("grid_bad_layout.json"))


def test_nan_prob_rejected():
    with pytest.raises(cc.ContractError,
                       match="non-finite"):
        validate(load("grid_nan_prob.json"))


def test_nonflat_obs_rejected():
    with pytest.raises(cc.ContractError,
                       match="non-flat initial exposure"):
        validate(load("grid_nonflat_obs.json"))


def test_unknown_contract_version_rejected():
    with pytest.raises(cc.ContractError,
                       match="unknown contract version"):
        validate(load("grid_ok_boundary.json"),
                 ver="COURSE_CONTRACT_V0")


def test_mirror_counting_uses_base_pairs():
    raw = FX / "raw_mirror.jsonl"
    sha = (FX / "raw_mirror.sha").read_text().strip()
    info, rows = osr.raw_coverage(
        raw, sha, label="fixture")
    assert info["base_pairs"] == [0, 1, 2, 3]
    assert info["episodes_total"] == 8
    assert "非 episodes" in info["mirror_relation"]
    assert "不增加独立样本数" in info[
        "sample_count_note"]


def test_entry_refuses_overwrite(tmp_path, monkeypatch):
    grid = FX / "grid_ok_boundary.json"
    import hashlib
    import rl_posctl.skill_p0.p0banks as pb
    gsha = hashlib.sha256(
        grid.read_bytes()).hexdigest()
    bsha = hashlib.sha256(pathlib.Path(
        __file__).read_bytes()).hexdigest()

    class FakeFeats:
        columns = ["c", "g", "q", "s"]

    monkeypatch.setattr(
        pb, "load_p0_bank",
        lambda p: [(None, FakeFeats(), {"pair_index": 0,
                                        "variant": 0})])
    out = tmp_path / "rep"
    spec = "ck262144|%s|%s|deadbeef" % (grid, gsha)
    rc1 = osr.main(["--bank", __file__, "--bank-sha",
                    bsha, "--grid", spec,
                    "--out", str(out)])
    assert rc1 == 0
    first = (out / "offline_skill_report.json").read_text(
        encoding="utf-8")
    rc2 = osr.main(["--bank", __file__, "--bank-sha",
                    bsha, "--grid", spec,
                    "--out", str(out)])
    assert rc2 == osr.RC_INVALID
    assert (out / "offline_skill_report.json").read_text(
        encoding="utf-8") == first  # 首份未被动
    assert json.loads(first)["status"] == "pass"


def test_invalid_writes_report_and_nonzero(tmp_path):
    grid = FX / "grid_nan_prob.json"
    import hashlib
    gsha = hashlib.sha256(
        grid.read_bytes()).hexdigest()
    out = tmp_path / "rep2"
    rc = osr.main(["--bank", __file__, "--bank-sha", "x"*64,
                   "--grid", "ckX|%s|%s|de" % (grid, gsha),
                   "--out", str(out)])
    assert rc == osr.RC_INVALID
    rep = json.loads(
        (out / "offline_skill_report.json").read_text(
            encoding="utf-8"))
    assert rep["status"] == "invalid"
    assert "SHA drift" in rep["error"]


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
    # c3/c4d0 q 条件化漂移在案(修正"无幅度课程"旧说法)
    assert "q" in c["other_courses"]["c3"]["drift_factor"]
    assert "q" in c["other_courses"]["c4d0"]["drift_factor"]
    for k, v in c["other_courses"].items():
        assert v["gates"] == "not_specified"
