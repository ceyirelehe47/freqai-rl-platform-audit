# -*- coding: utf-8 -*-
"""RouteC_A2_RuntimeClosure FiniteRepair R1:FR01–FR03 正反例成对验收。

上游独立终验(0f494d27)FAIL 的两项遗漏进入运行前置后:
- FR01 vendor 静态合同(cmd_audit 的 vendor_dir_default/_vendor_state/
  VENDOR_PIN 同源读取):缺目录/dirty/错 HEAD 在首签发前拒;
- FR02 PIN 历史原件(_historical_binding 同源):digest 缺失/改字节/
  基线 blob 改变在首签发前拒;
- FR03 PIN 分支/血统(historical_evidence_binding 同源):same-commit
  detached/错分支在首签发前拒;既有拒例(缺 env/错字节/错 HEAD/
  dirty 源码/非 pin 解析)不退回。

隔离域用真实对象的 --shared 克隆构成完整合法基线(r13/r15/r16
历史、digest 原件、vendor@VENDOR_PIN 均为真对象);每场景仅改
一个条件。两入口(operator execute / admission issue)以子进程
实跑,拒绝先于任何一次性写。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parents
TREE = next(b for b in _BASE if (b / "src" / "rl_curriculum").is_dir()
            or (b / "stage2_6_1" / "src" / "rl_curriculum").is_dir())
if (TREE / "src" / "rl_curriculum").is_dir():
    SRC_DIR = TREE / "src"
else:
    SRC_DIR = TREE / "stage2_6_1" / "src"
sys.path.insert(0, str(SRC_DIR))

from rl_curriculum.curriculum261_qaf_provenance_guard import (  # noqa: E402
    runtime_dependency_preflight,
)

PY = sys.executable
GIT = "git"
REAL_PIN = Path("/home/cryptorl/release_pin_qaf_v3")
REAL_P3 = Path("/home/cryptorl/projects/crypto_rl_qaf_v3")
REAL_VENDOR = REAL_P3 / "vendor" / "freqtrade"
OLD_P = Path("/home/cryptorl/projects/crypto_rl")
BRANCH = "route-c-stage2-6-1-repair17"

pytestmark = pytest.mark.skipif(
    not (REAL_PIN / ".git").exists() or not REAL_P3.is_dir(),
    reason="真实 PIN/P3 不可达(隔离域需真实对象 --shared 克隆)")


def _run(cmd, cwd=None, check=True):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(str(c) for c in cmd)} rc={proc.returncode}\n"
            f"{proc.stdout}\n{proc.stderr}")
    return proc


def _pin_head() -> str:
    return _run([GIT, "rev-parse", "HEAD"], cwd=REAL_PIN).stdout.strip()


#: _historical_binding 工作树读取面(digest 原件+r11/r12 blob 件)
_HIST_FILES = [
    "stage2_6_1/artifacts/repair2/qualification_plan_digest.txt",
    "stage2_6_2/artifacts/repair2/diagnostic_plan_digest.txt",
    "stage2_6_1/artifacts/repair4/r4_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair6/r6_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair7/r7_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair8/r8_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair9/r9_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair9/r9_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair10/r10_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair10/r10_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair11/cue_audit_plan_digest.txt",
    "stage2_6_1/artifacts/repair11/r11_code_freeze.json",
    "stage2_6_1/artifacts/repair12/cue_contract_audit.json",
    "stage2_6_1/artifacts/repair12/r12_code_freeze.json",
    "stage2_6_1/artifacts/repair12/robustness_gate.json",
    "stage2_6_1/artifacts/repair12/lock_plan_failure_traceback.json",
    "stage2_6_1/artifacts/repair13/r13_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair13/r13_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair13/qualification_plan_digest_r13.txt",
    "stage2_6_1/artifacts/repair12/r12_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair12/r12_parameter_pack_digest.txt",
]

#: freeze manifest 单文件(仓库根)
_ROOT_FILES = ["environment.yml", "requirements-lock.txt",
               "activate-freqtrade.sh",
               "user_data/strategies/RouteCStrategy.py"]

#: 项目侧已接受原件(旧 P 实测字节)
_ORIGINALS = [
    "user_data/strategies/RouteCStrategy.py",
    "requirements-lock.txt",
    "environment.yml",
    "activate-freqtrade.sh",
    "experiments/freqai_rl_stage2_5_2a/runtime/"
    "config_stage252a-rc-e9b373b3c9_smoke-reload.json",
]


def _sparse_patterns():
    pats = ["/stage2_6_1/src/**", "/stage2_6_1/tests/**",
            "/stage2_6_1/runner/**", "/stage2_6_1/report/**",
            "/stage2_6_1/artifacts/repair10/r10_design_plan.json",
            "/stage2_6_1/artifacts/repair11/**",
            "/stage2_6_1/artifacts/repair12/**",
            "/stage2_6_1/artifacts/repair13/**"]
    pats += [f"/{rel}" for rel in _HIST_FILES]
    pats += [f"/{rel}" for rel in _ROOT_FILES]
    return pats


@pytest.fixture(scope="module")
def fr_domain(tmp_path_factory):
    """隔离完整合法域:--shared 真 history pin + 候选字节 project +
    vendor@VENDOR_PIN shared 克隆。返回 dict(pin, project, head)。"""
    base = tmp_path_factory.mktemp("fr1")
    pin = base / "release_pin"
    _run([GIT, "clone", "-q", "--shared", "--no-checkout",
          str(REAL_PIN), str(pin)])
    head = _pin_head()
    _run([GIT, "sparse-checkout", "init", "--no-cone"], cwd=pin)
    _run([GIT, "sparse-checkout", "set", *_sparse_patterns()], cwd=pin)
    _run([GIT, "checkout", "-qB", BRANCH, head], cwd=pin)

    project = base / "project"
    project.mkdir()

    def _proj_copy(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes().replace(b"\r", b""))
    def _copy_tree(src_dir: Path, dst_dir: Path):
        for f in src_dir.rglob("*"):
            if not f.is_file() or f.is_symlink():
                continue
            if any(part in ("__pycache__", ".pytest_cache")
                   for part in f.relative_to(src_dir).parts):
                continue
            _proj_copy(f, dst_dir / f.relative_to(src_dir))

    _copy_tree(pin / "stage2_6_1" / "src", project / "src")
    _copy_tree(pin / "stage2_6_1" / "runner",
               project / "stage2_6_1_runner")
    _copy_tree(pin / "stage2_6_1" / "tests" / "route_c_stage2_6_1",
               project / "tests" / "route_c_stage2_6_1")
    for repo_rel, proj_rel in (
            ("stage2_6_1/report/r20_design_calc_v4.py",
             "report/r20_design_calc_v4.py"),
            ("stage2_6_1/report/r20_design_calc_v4.json",
             "report/r20_design_calc_v4.json"),
            ("stage2_6_1/artifacts/repair10/r10_design_plan.json",
             "artifacts/route_c_stage2_6_1_repair10/"
             "r10_design_plan.json")):
        _proj_copy(pin / repo_rel, project / proj_rel)
    for rel in _ORIGINALS:
        dst = project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(OLD_P / rel, dst)
    # 已接受原件(git 未跟踪但部署必需;字节=旧 P 实测):从真实
    # P3 逐字节补齐(raw 字节与钉死 sha 一致,不做 CR 投影)。
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        RUNTIME_TREE_ALLOWED_EXTRAS,
    )
    for rel in RUNTIME_TREE_ALLOWED_EXTRAS:
        origin = REAL_P3 / rel
        if origin.is_file():
            dst = project / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(origin, dst)
    # rl_platform 等 src 顶层包(git 未跟踪、比对面外;部署必需)
    # 从真实 P3 逐字节补齐。
    for top in REAL_P3.joinpath("src").iterdir():
        if top.name == "rl_curriculum" or top.name.startswith("."):
            continue
        if top.is_dir():
            _copy_tree(top, project / "src" / top.name)
        elif top.is_file():
            _proj_copy(top, project / "src" / top.name)

    # vendor:真对象 shared 克隆 @VENDOR_PIN(与 cmd_audit 同判据)
    from rl_curriculum.curriculum261_r17_cli import VENDOR_PIN
    vend = project / "vendor" / "freqtrade"
    _run([GIT, "clone", "-q", "--shared", "--no-checkout",
          str(REAL_VENDOR), str(vend)])
    _run([GIT, "checkout", "-q", VENDOR_PIN], cwd=vend)
    return {"pin": pin, "project": project, "head": head,
            "base": base, "vendor_pin": VENDOR_PIN}


def _preflight(domain, monkeypatch):
    import rl_curriculum.curriculum261_qaf_provenance_guard as guard
    monkeypatch.setattr(guard, "R17_PIN_EXPECTED_ROOT",
                        str(domain["pin"]))
    return runtime_dependency_preflight(
        repo=domain["pin"], project_dir=domain["project"],
        candidate_sha=domain["head"], python=PY)


_MARKERS = ("vendor_static", "historical_digests", "branch_lineage")


def _assert_single_marker(rd, marker):
    """拒绝且仅含目标 FR 标记(单一条件变化)。"""
    assert not rd["ok"], rd.get("problems")
    hit = [m for m in _MARKERS
           if any(m in p for p in rd["problems"])]
    assert hit == [marker], (marker, rd["problems"])


# ---- 基线正例:完整合法配置(ok 且三类新检查全绿) ----------------

def test_fr_baseline_positive(fr_domain, monkeypatch):
    rd = _preflight(fr_domain, monkeypatch)
    assert rd["ok"], rd.get("problems")
    assert rd["vendor_ok"] is True
    assert rd["hist_digests_match"] is True
    assert rd["heb_ok"] is True
    assert rd["heb_branch"] == BRANCH


# ---- FR01:vendor 静态合同 ---------------------------------------

def test_fr01_vendor_missing(fr_domain, monkeypatch):
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    saved = fr_domain["base"] / "vendor_saved"
    vend.rename(saved)
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "vendor_static")
    finally:
        saved.rename(vend)


def test_fr01_vendor_dirty(fr_domain, monkeypatch):
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    touched = vend / "README.md"
    data = touched.read_bytes()
    try:
        touched.write_bytes(data + b"\n# fr dirty\n")
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "vendor_static")
    finally:
        touched.write_bytes(data)


def test_fr01_vendor_wrong_head(fr_domain, monkeypatch):
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    (vend / ".fr_wrong_head").write_text("x")
    _run([GIT, "add", "-A"], cwd=vend)
    _run([GIT, "-c", "user.email=t@t", "-c", "user.name=t",
          "commit", "-qm", "fr wrong head"], cwd=vend)
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "vendor_static")
    finally:
        _run([GIT, "checkout", "-q", fr_domain["vendor_pin"]], cwd=vend)


# ---- FR02:PIN 历史原件 -------------------------------------------

def test_fr02_digest_deleted(fr_domain, monkeypatch):
    f = fr_domain["pin"] / _HIST_FILES[0]
    data = f.read_bytes()
    f.unlink()
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "historical_digests")
    finally:
        f.write_bytes(data)


def test_fr02_digest_bytes_changed(fr_domain, monkeypatch):
    f = fr_domain["pin"] / (
        "stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt")
    data = f.read_bytes()
    f.write_bytes(b"tampered-fr02\n")
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "historical_digests")
    finally:
        f.write_bytes(data)


def test_fr02_baseline_blob_changed(fr_domain, monkeypatch):
    """r11 基线 blob 件工作树字节改变(HEAD 不变也拒)。"""
    f = fr_domain["pin"] / (
        "stage2_6_1/artifacts/repair11/r11_code_freeze.json")
    data = f.read_bytes()
    f.write_bytes(b'{"tampered": "fr02"}\n')
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "historical_digests")
    finally:
        f.write_bytes(data)


def test_fr02_restore_returns_ok(fr_domain, monkeypatch):
    """负例恢复后基线重新全绿(恢复真实性)。"""
    f = fr_domain["pin"] / _HIST_FILES[0]
    data = f.read_bytes()
    f.unlink()
    _preflight(fr_domain, monkeypatch)
    f.write_bytes(data)
    rd = _preflight(fr_domain, monkeypatch)
    assert rd["ok"], rd.get("problems")


# ---- FR03:PIN 分支/血统 -----------------------------------------

def test_fr03_detached_same_commit(fr_domain, monkeypatch):
    _run([GIT, "checkout", "-q", "--detach", fr_domain["head"]],
         cwd=fr_domain["pin"])
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "branch_lineage")
        assert "detached" not in (rd.get("heb_branch") or "")
    finally:
        _run([GIT, "checkout", "-q", BRANCH], cwd=fr_domain["pin"])


def test_fr03_wrong_branch_name(fr_domain, monkeypatch):
    _run([GIT, "checkout", "-qB", "route-c-stage2-6-1-repair18",
          fr_domain["head"]], cwd=fr_domain["pin"])
    try:
        rd = _preflight(fr_domain, monkeypatch)
        _assert_single_marker(rd, "branch_lineage")
        assert rd["heb_branch"] != BRANCH
    finally:
        _run([GIT, "checkout", "-qB", BRANCH, fr_domain["head"]],
             cwd=fr_domain["pin"])


# ---- 既有拒例不退回(回归口径;与 rd04 系列互补) -----------------

def test_fr03_existing_refusals_hold(fr_domain, monkeypatch):
    """缺 env 仍拒(不因新检查改变既有拒绝)。"""
    f = fr_domain["project"] / "environment.yml"
    data = f.read_bytes()
    f.unlink()
    try:
        rd = _preflight(fr_domain, monkeypatch)
        assert not rd["ok"]
        assert any("缺失" in p or "environment.yml" in p
                   for p in rd["problems"]), rd["problems"]
    finally:
        f.write_bytes(data)


# ---- 两入口实际接线(operator execute / admission issue) --------

def _deploy_scaffold(domain, tmp_path):
    """gate 前置件:provenance 目标安装+部署配置(隔离 deploy 根)。"""
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    from test_curriculum261_qaf_v2_preissue_guard import _guard_repo
    deploy = tmp_path / "deploy"
    art = deploy / "artifacts" / "formal_a_qaf_v3"
    art.mkdir(parents=True)
    src = read_pinned_source(_guard_repo())
    install_to_target(art, src)
    (deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "formal_ready",
        "formal_roots": {"qprod_a_formal_v3": {
            "artifact_root": str(art),
            "state_root": str(deploy / "state"),
            "authority_dir": str(deploy / "authority")}}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return deploy


def _entry_env(domain):
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "/home/cryptorl",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(domain["project"] / "src")}


def test_fr_entry_operator_vendor_refusal(fr_domain, tmp_path):
    """operator execute 实跑:vendor 破坏 ⇒ rc=96 拒绝且零一次性写。"""
    deploy = _deploy_scaffold(fr_domain, tmp_path)
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    saved = fr_domain["base"] / "vendor_saved_e1"
    vend.rename(saved)
    entry = (fr_domain["project"] / "stage2_6_1_runner"
             / "qaf_v2_operator_entry.py")
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")
    try:
        proc = subprocess.run(
            [PY, str(entry), "execute",
             "--repo", str(fr_domain["pin"]),
             "--deploy-root", str(deploy),
             "--project-dir", str(fr_domain["project"]),
             "--approval-json", str(approval),
             "--regression-evidence", "unused",
             "--admission-id", "qaf-v3-fr-entry-test",
             "--authorization", "test",
             "--plan-digest", _run(
             [GIT, "rev-parse", fr_domain["head"] + "^{tree}"],
             cwd=fr_domain["pin"]).stdout.strip(),
             "--code-freeze-sha", fr_domain["head"],
             "--attempt", "qaf_v3",
         "--model-update"],
            capture_output=True, text=True, env=_entry_env(fr_domain),
            cwd=str(fr_domain["project"]), timeout=600)
        assert proc.returncode == 96, (proc.returncode, proc.stdout,
                                       proc.stderr[-600:])
        assert "vendor_static" in proc.stdout, proc.stdout[-600:]
        assert '"one_shot_writes": 0' in proc.stdout
        assert not (deploy / "authority").exists()
    finally:
        saved.rename(vend)


def test_fr_entry_admission_vendor_refusal(fr_domain, tmp_path):
    """admission issue 实跑:vendor 缺失 ⇒ rc=96 拒绝且零一次性写
    (入口子进程内 pin 覆盖目标为真实 PIN,故入口级 FR 标记用
    vendor——读取 fixture project 消费面;分支/历史反例在
    preflight 级 FR02/FR03 成对覆盖)。"""
    deploy = _deploy_scaffold(fr_domain, tmp_path)
    vend = fr_domain["project"] / "vendor" / "freqtrade"
    saved = fr_domain["base"] / "vendor_saved_e2"
    vend.rename(saved)
    entry = (fr_domain["project"] / "stage2_6_1_runner"
             / "r17_admission_issue.py")
    prereg = tmp_path / "prereg.json"
    tree = _run([GIT, "rev-parse", fr_domain["head"] + "^{tree}"],
                cwd=fr_domain["pin"]).stdout.strip()
    prereg.write_text(json.dumps({
        "iteration": "qprod_a_formal_v3",
        "formal_attempt": "qaf_v3",
        "plan_digest": tree,
        "plan_digest_method": "git_tree_digest",
        "regression_evidence": "unused-fr-test",
        "admission_id": "qaf-v3-fr-entry-test",
        "authorization": "test"}, ensure_ascii=False),
        encoding="utf-8")
    try:
        proc = subprocess.run(
            [PY, str(entry),
             "--repo", str(fr_domain["pin"]),
             "--deploy-root", str(deploy),
             "--state-root", str(deploy / "artifacts" / "route_c_stage2_6_1_repair17" / "state"),
             "--commit-a", fr_domain["head"],
             "--preregistration", str(prereg),
             "--project-dir", str(fr_domain["project"])],
            capture_output=True, text=True, env=_entry_env(fr_domain),
            cwd=str(fr_domain["project"]), timeout=600)
        assert proc.returncode == 96, (proc.returncode, proc.stdout,
                                       proc.stderr[-600:])
        assert "vendor_static" in proc.stdout, proc.stdout[-600:]
        assert '"one_shot_writes": 0' in proc.stdout
        assert not (deploy / "authority").exists()
    finally:
        saved.rename(vend)


def test_fr_entry_operator_passes_gate_to_next_boundary(
        fr_domain, tmp_path):
    """完整合法域:operator 通过守卫后抵达下一真实边界(批准原件
    绑定)——截停点不是前置检查,证明前置放行到达签发边界。"""
    deploy = _deploy_scaffold(fr_domain, tmp_path)
    entry = (fr_domain["project"] / "stage2_6_1_runner"
             / "qaf_v2_operator_entry.py")
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        [PY, str(entry), "execute",
         "--repo", str(fr_domain["pin"]),
         "--deploy-root", str(deploy),
         "--project-dir", str(fr_domain["project"]),
         "--approval-json", str(approval),
         "--regression-evidence", "unused",
         "--admission-id", "qaf-v3-fr-entry-test",
         "--authorization", "test",
         "--plan-digest", _run(
             [GIT, "rev-parse", fr_domain["head"] + "^{tree}"],
             cwd=fr_domain["pin"]).stdout.strip(),
         "--code-freeze-sha", fr_domain["head"],
         "--attempt", "qaf_v3",
         "--model-update"],
        capture_output=True, text=True, env=_entry_env(fr_domain),
        cwd=str(fr_domain["project"]), timeout=600)
    out = proc.stdout
    assert proc.returncode not in (0,), (proc.returncode, out,
                                        proc.stderr[-600:])
    # 守卫通过:拒绝来自守卫之后的批准绑定/参数绑定边界
    assert "vendor_static" not in out and "branch_lineage" not in out \
        and "historical_digests" not in out, out[-600:]
    assert "one_shot_writes" in out
    assert not (deploy / "authority").exists()
