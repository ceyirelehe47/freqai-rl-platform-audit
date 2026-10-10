# -*- coding: utf-8 -*-
"""RouteC_A2_RuntimeClosure FiniteRepair R2:FR2-01/02 binding 层验收。

上游 R2 终验(REVIEW.md §3)判:r11/r12/r13 binding 的历史原件层
未入首签发前必要检查(删除 r13_iteration_aborted.json 或
cue_event_trace.jsonl 后前置仍 ok)。R2 修复=提取三个真实 binder 的
只读 checks(_r11_abort_checks/_r12_abort_checks/_r13_failure_checks
与 cmd_audit 的 binder 同源同判据),接入探针 → preissue_gate →
三条签发路径(operator execute / 直接 qprod_formal_authority
issue-permit / r17_admission_issue)。

场景(隔离域=--shared 克隆真实 PIN;单条件突变;恢复正例):
- r11:trace 缺失 / abort marker 字节改变 / 应缺席的 final 出现;
- r13:abort 缺失 / result blob 改变 / exposure 缺失 / plan digest 改变;
- r12:marker blob 改变 / 应缺席的 exposure 出现;
- 直接 permit 入口:历史突变拒(rc=96,historical_bindings,零写);
  合法配置穿过全部前置在批准原件边界截停。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_curriculum261_qaf_v3_finite_repair_r1 import (  # noqa: E402
    BRANCH, GIT, PY, _deploy_scaffold, _entry_env, _preflight, _run,
    fr_domain,
)

R11 = "stage2_6_1/artifacts/repair11"
R12 = "stage2_6_1/artifacts/repair12"
R13 = "stage2_6_1/artifacts/repair13"

pytestmark = pytest.mark.skipif(
    not Path("/home/cryptorl/release_pin_qaf_v3/.git").exists(),
    reason="真实 PIN 不可达(隔离域需真实对象 --shared 克隆)")


def _assert_binding_refusal(rd, iteration: str):
    assert not rd["ok"], rd.get("problems")
    states = rd.get("bind_states") or {}
    assert states.get(iteration) is False, (states, rd.get("problems"))
    assert any("historical_bindings" in p for p in rd["problems"]), \
        rd["problems"]
    # 单条件突变:其余检查面不触发(vendor/digests/分支均保持)
    for marker in ("vendor_static", "historical_digests",
                   "branch_lineage"):
        assert not any(marker in p for p in rd["problems"]), \
            (marker, rd["problems"])


def _mutate(pin: Path, rel: str, *, delete=False, append=None,
            write=None):
    f = pin / rel
    data = f.read_bytes()
    if delete:
        f.unlink()
    elif append is not None:
        f.write_bytes(data + append)
    elif write is not None:
        f.write_bytes(write)
    return data


def _restore(pin: Path, rel: str, data: bytes):
    (pin / rel).write_bytes(data)


# ---- FR2-01:r11 binding 层 ---------------------------------------

def test_fr201_r11_trace_missing(fr_domain, monkeypatch):
    f = fr_domain["pin"] / R11 / "cue_event_trace.jsonl"
    data = _mutate(fr_domain["pin"], f"{R11}/cue_event_trace.jsonl",
                   delete=True)
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r11")
    finally:
        _restore(fr_domain["pin"], f"{R11}/cue_event_trace.jsonl", data)


def test_fr201_r11_marker_bytes_changed(fr_domain, monkeypatch):
    f = f"{R11}/r11_iteration_aborted.json"
    data = _mutate(fr_domain["pin"], f, append=b"\n")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r11")
    finally:
        _restore(fr_domain["pin"], f, data)


def test_fr201_r11_final_result_appears(fr_domain, monkeypatch):
    """历史声明 final 从未执行;该文件出现即拒(必要缺席条件)。"""
    f = fr_domain["pin"] / R11 / "qualification_result.json"
    f.write_text('{"verdict": "PASS"}\n', encoding="utf-8")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r11")
    finally:
        f.unlink()


def test_fr201_r11_audit_result_changed(fr_domain, monkeypatch):
    f = f"{R11}/cue_contract_audit.json"
    data = _mutate(fr_domain["pin"], f, append=b" ")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r11")
    finally:
        _restore(fr_domain["pin"], f, data)


# ---- FR2-01:r13 binding 层 ---------------------------------------

def test_fr201_r13_abort_missing(fr_domain, monkeypatch):
    f = f"{R13}/r13_iteration_aborted.json"
    data = _mutate(fr_domain["pin"], f, delete=True)
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r13")
    finally:
        _restore(fr_domain["pin"], f, data)


def test_fr201_r13_result_blob_changed(fr_domain, monkeypatch):
    """verdict 等语义字段不变,仅字节改变(blob!=基线)即拒。"""
    p = fr_domain["pin"] / f"{R13}/qualification_result.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    data = p.read_bytes()
    obj["fr2_probe_tamper"] = True
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r13")
    finally:
        p.write_bytes(data)


def test_fr201_r13_exposure_missing(fr_domain, monkeypatch):
    f = f"{R13}/qualification_exposure_r13.json"
    data = _mutate(fr_domain["pin"], f, delete=True)
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r13")
    finally:
        _restore(fr_domain["pin"], f, data)


def test_fr201_r13_plan_digest_changed(fr_domain, monkeypatch):
    f = f"{R13}/qualification_plan_digest_r13.txt"
    data = _mutate(fr_domain["pin"], f, write=b"qp12-tampered\n")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r13")
    finally:
        _restore(fr_domain["pin"], f, data)


# ---- FR2-01:r12 binding 层 ---------------------------------------

def test_fr201_r12_marker_blob_changed(fr_domain, monkeypatch):
    """r12 marker 字节改变:heb 层(r12_abort_marker_content_matches_
    baseline)与 binder 层同源双检出——单突变双标记属设计,不互斥。"""
    f = f"{R12}/r12_iteration_aborted.json"
    data = _mutate(fr_domain["pin"], f, append=b"\n")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        assert not rd["ok"], rd.get("problems")
        states = rd.get("bind_states") or {}
        assert states.get("r12") is False, states
        hit = {m for m in ("historical_bindings", "branch_lineage",
                           "vendor_static", "historical_digests")
               if any(m in pr for pr in rd["problems"])}
        assert hit == {"historical_bindings", "branch_lineage"}, hit
    finally:
        _restore(fr_domain["pin"], f, data)


def test_fr201_r12_exposure_appears(fr_domain, monkeypatch):
    f = fr_domain["pin"] / R12 / "qualification_exposure_r12.json"
    f.write_text('{"status": "exposed"}\n', encoding="utf-8")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_binding_refusal(rd, "r12")
    finally:
        f.unlink()


# ---- 恢复正例:全部突变恢复后基线重新全绿 ------------------------

def test_fr201_restore_returns_ok(fr_domain, monkeypatch):
    f = fr_domain["pin"] / f"{R13}/r13_iteration_aborted.json"
    data = _mutate(fr_domain["pin"], f"{R13}/r13_iteration_aborted.json",
                   delete=True)
    _preflight(fr_domain, monkeypatch)  # 破坏态被拒(不检查具体标记)
    _restore(fr_domain["pin"], f"{R13}/r13_iteration_aborted.json", data)
    rd = _preflight(fr_domain, monkeypatch)
    assert rd["ok"], rd.get("problems")
    assert all((rd.get("bind_states") or {}).values())


# ---- FR2-02:直接 qprod_formal_authority issue-permit 实跑 --------

def _authority_dir(fr_domain, tmp_path):
    entry = fr_domain["project"] / "stage2_6_1_runner" / \
        "qprod_formal_authority.py"
    adir = tmp_path / "authority"
    proc = _run([PY, str(entry), "init", "--dir", str(adir)],
                cwd=fr_domain["project"], check=False)
    assert proc.returncode == 0, proc.stderr[-400:]
    return adir, entry


def test_fr202_direct_permit_refuses_before_first_write(
        fr_domain, tmp_path):
    """直接 issue-permit 首写前 gate 拒绝(rc=96,零许可写)。

    入口子进程内 PIN 解析=guard 常量(上游禁 env/手写重定向),历史
    原件突变不可注入入口子进程——入口级接线证明用 vendor 突变
    (读 fixture project;与 FR1 admission 先例同构);binding 层
    拒绝在同一 preissue_gate/探针代码路径,由 preflight 级
    FR2-01 九场景覆盖。"""
    deploy = _deploy_scaffold(fr_domain, tmp_path)
    adir, entry = _authority_dir(fr_domain, tmp_path)
    tree = _run([GIT, "rev-parse", fr_domain["head"] + "^{tree}"],
                cwd=fr_domain["pin"]).stdout.strip()
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    saved = fr_domain["base"] / "vendor_saved_fr2"
    vend.rename(saved)
    try:
        proc = subprocess.run(
            [PY, str(entry), "issue-permit",
             "--dir", str(adir),
             "--deploy-root", str(deploy),
             "--task-level", "level_a",
             "--attempt", "qaf_v3",
             "--repo", str(fr_domain["pin"]),
             "--project-dir", str(fr_domain["project"]),
             "--regression-evidence", "unused-fr2",
             "--code-freeze-sha", fr_domain["head"],
             "--plan-digest", tree],
            capture_output=True, text=True, env=_entry_env(fr_domain),
            cwd=str(fr_domain["project"]), timeout=600)
        assert proc.returncode == 96, (proc.returncode, proc.stdout,
                                       proc.stderr[-600:])
        assert "vendor_static" in proc.stdout, proc.stdout[-600:]
        assert '"one_shot_writes": 0' in proc.stdout
        assert not list(adir.rglob("permit_*")), \
            "gate 拒绝路径不得写任何许可"
    finally:
        saved.rename(vend)


def test_fr202_direct_permit_legal_passes_gate_to_approval(
        fr_domain, tmp_path):
    """合法完整域:直接 issue-permit 穿过全部前置(含 binding 层),
    在批准原件边界截停(非历史/环境拒因)。"""
    deploy = _deploy_scaffold(fr_domain, tmp_path)
    adir, entry = _authority_dir(fr_domain, tmp_path)
    tree = _run([GIT, "rev-parse", fr_domain["head"] + "^{tree}"],
                cwd=fr_domain["pin"]).stdout.strip()
    proc = subprocess.run(
        [PY, str(entry), "issue-permit",
         "--dir", str(adir),
         "--deploy-root", str(deploy),
         "--task-level", "level_a",
         "--attempt", "qaf_v3",
         "--repo", str(fr_domain["pin"]),
         "--project-dir", str(fr_domain["project"]),
         "--regression-evidence", "unused-fr2",
         "--code-freeze-sha", fr_domain["head"],
         "--plan-digest", tree],
        capture_output=True, text=True, env=_entry_env(fr_domain),
        cwd=str(fr_domain["project"]), timeout=600)
    out = proc.stdout
    for marker in ("historical_bindings", "vendor_static",
                   "branch_lineage", "historical_digests"):
        assert marker not in out, out[-600:]
    assert proc.returncode != 0
    assert "批准" in out or "approval" in out.lower(), out[-600:]
    assert not list(adir.rglob("permit_*"))
