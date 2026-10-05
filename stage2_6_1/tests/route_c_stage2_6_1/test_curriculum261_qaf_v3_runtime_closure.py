"""RouteC_A2_RuntimeClosure_NewAttempt_v1:RD03–RD06 正反例。

覆盖:
- RD03/RD05:真实 freeze 读取器(write_r17_code_freeze/
  freeze_surface_manifest)在工程隔离目标上的正例(依赖齐全+pin
  HEAD==候选 ⇒ 冻结产物写出)与负例(缺件/错 HEAD/dirty/错源)。
- RD04:runtime_dependency_preflight 契约(缺件/错字节/错 HEAD/
  dirty/非 pin 解析 ⇒ 拒;完整映射 ⇒ ok),并经 preissue_gate
  (operator 与直接 issuer 共同前置)在首一次性写前生效。
- RD06:qaf_v3 注册表身份(26 名/与 v1v2 不相交/迭代/CLI choices
  自动扩展/api 接线)。

全部隔离(tmp 目录);零真实签发/零业务叶调用。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

#: 布局自适应(仓树 stage2_6_1/... 与部署 P 树 .../src 两种形态)
_BASE = Path(__file__).resolve().parents
TREE = next(b for b in _BASE if (b / "src" / "rl_curriculum").is_dir()
            or (b / "stage2_6_1" / "src" / "rl_curriculum").is_dir())
if (TREE / "src" / "rl_curriculum").is_dir():
    SRC_DIR = TREE / "src"
else:
    SRC_DIR = TREE / "stage2_6_1" / "src"
REPO = TREE

sys.path.insert(0, str(SRC_DIR))

from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF3_ALL_NEW, QAF3_ATTEMPT_ID, QAF3_INPUT_SCOPE, QAF_ATTEMPTS,
    QAF_ATTEMPT_IDS, qaf_input_scope_for_attempt,
    qaf_iteration_id_for_attempt,
)
from rl_curriculum.curriculum261_qaf_provenance_guard import (  # noqa: E402
    RUNTIME_ORIGINAL_DIGESTS, preissue_gate,
    runtime_dependency_preflight,
)


PY = sys.executable
GIT = "git"

#: 隔离域构建的固定相对件(与 RUNTIME_* 常量一致的权威面)
_PROJECT_DIRS = ("src/rl_curriculum", "tests/route_c_stage2_6_1",
                 "stage2_6_1_runner")
_GIT_PREFIXED = {
    "src/rl_curriculum": "stage2_6_1/src/rl_curriculum",
    "tests/route_c_stage2_6_1":
        "stage2_6_1/tests/route_c_stage2_6_1",
    "stage2_6_1_runner": "stage2_6_1/runner",
}


def _run(cmd, cwd=None, check=True):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"{cmd} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc


def _build_fixture(tmp_path, *, pin_at="candidate"):
    """构建隔离域:repo(候选提交) + pin worktree + 完整 P3 树。

    返回 (repo, candidate_sha, pin, project)。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _run([GIT, "init", "-q", str(repo)])
    _run([GIT, "config", "user.email", "t@t"], cwd=repo)
    _run([GIT, "config", "user.name", "t"], cwd=repo)
    # 权威树:src/tests/runner + report/repair10/experiments 原件
    proj_base = SRC_DIR.parent
    runner_dir = (proj_base / "stage2_6_1_runner"
                  if (proj_base / "stage2_6_1_runner").is_dir()
                  else proj_base / "runner")
    for d in _PROJECT_DIRS:
        src_root = {"src/rl_curriculum": SRC_DIR / "rl_curriculum",
                    "tests/route_c_stage2_6_1":
                        proj_base / "tests" / "route_c_stage2_6_1",
                    "stage2_6_1_runner": runner_dir}[d]
        dst = repo / _GIT_PREFIXED[d]
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_root, dst,
                        ignore=shutil.ignore_patterns(
                            "__pycache__", ".pytest_cache", "*.pyc"))
    rep = (proj_base / "report"
           if (proj_base / "report").is_dir()
           else proj_base / "stage2_6_1" / "report")
    r10 = (proj_base / "artifacts" / "route_c_stage2_6_1_repair10"
           if (proj_base / "artifacts" / "route_c_stage2_6_1_repair10"
               ).is_dir()
           else proj_base / "stage2_6_1" / "artifacts"
           / "route_c_stage2_6_1_repair10")
    #: repo 路径=真实 git 布局(artifacts/repair10)——与
    #: GIT_BACKED_MAP/真实仓一致;项目根映射在 project 构建后落。
    for repo_rel, origin in (
            ("report/r20_design_calc_v4.py",
             rep / "r20_design_calc_v4.py"),
            ("report/r20_design_calc_v4.json",
             rep / "r20_design_calc_v4.json"),
            ("artifacts/repair10/r10_design_plan.json",
             r10 / "r10_design_plan.json")):
        dst = repo / "stage2_6_1" / repo_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origin, dst)
    _run([GIT, "add", "-A"], cwd=repo)
    _run([GIT, "commit", "-qm", "candidate A"], cwd=repo)
    sha = _run([GIT, "rev-parse", "HEAD"], cwd=repo).stdout.strip()

    pin = tmp_path / "release_pin"
    _run([GIT, "worktree", "add", "--detach", str(pin), sha], cwd=repo)

    project = tmp_path / "project"
    project.mkdir()

    def _copy_projected(src: Path, dst: Path):
        """CR 投影拷贝(部署口径:候选字节 CR 剥离后落盘)。"""
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes().replace(b"\r", b"")
        dst.write_bytes(data)

    # 整 src 树(rl_curriculum+rl_platform 等全部包;api 真实
    # import 链需要);repo 候选树仅含比对权威面。
    for f in SRC_DIR.parent.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        rel = f.relative_to(SRC_DIR.parent)
        if rel.parts[0] in ("__pycache__", ".pytest_cache",
                            "tests", "stage2_6_1_runner"):
            continue
        if any(part in ("__pycache__", ".pytest_cache")
               for part in rel.parts):
            continue
        _copy_projected(f, project / rel)
    for d in _PROJECT_DIRS:
        for f in (repo / _GIT_PREFIXED[d]).rglob("*"):
            if not f.is_file() or f.is_symlink():
                continue
            if any(part in ("__pycache__", ".pytest_cache")
                   for part in f.relative_to(repo / _GIT_PREFIXED[d]).parts):
                continue
            rel = f.relative_to(repo / _GIT_PREFIXED[d])
            _copy_projected(f, project / d / rel)
    for repo_rel, proj_rel in (
            ("report/r20_design_calc_v4.py",
             "report/r20_design_calc_v4.py"),
            ("report/r20_design_calc_v4.json",
             "report/r20_design_calc_v4.json"),
            ("artifacts/repair10/r10_design_plan.json",
             "artifacts/route_c_stage2_6_1_repair10/"
             "r10_design_plan.json")):
        _copy_projected(repo / "stage2_6_1" / repo_rel,
                        project / proj_rel)
    # 已接受原件(旧 P 实测字节):env 三件套+strategy+runtime config
    old_p = Path("/home/cryptorl/projects/crypto_rl")
    for rel in ("user_data/strategies/RouteCStrategy.py",
                "requirements-lock.txt", "environment.yml",
                "activate-freqtrade.sh",
                "experiments/freqai_rl_stage2_5_2a/runtime/"
                "config_stage252a-rc-e9b373b3c9_smoke-reload.json"):
        dst = project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(old_p / rel, dst)
    return repo, sha, pin, project


def _preflight(repo, sha, pin, project, monkeypatch, tmp_path):
    import rl_curriculum.curriculum261_qaf_provenance_guard as guard
    monkeypatch.setattr(guard, "R17_PIN_EXPECTED_ROOT", str(pin))
    return runtime_dependency_preflight(
        repo=repo, project_dir=project, candidate_sha=sha,
        python=PY)


# ---- RD03/RD05:真实 freeze 读取器正负例 --------------------------

def _freeze_subprocess(project, pin, sha, out, expect_ok):
    """以 P3 为 dev root 真实执行冻结读取器(子进程;真消费面)。"""
    code = (
        "import sys, json\n"
        "from pathlib import Path\n"
        "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
        "dep.R17_RELEASE_PIN_ROOT = Path(sys.argv[2])\n"
        "try:\n"
        "    doc = dep.write_r17_code_freeze(Path(sys.argv[3]),"
        " code_freeze_sha=sys.argv[4])\n"
        "    print('FREEZE_OK', json.dumps({"
        "'sha': doc['code_freeze_sha'],"
        " 'missing': doc['freeze_surface']['missing_required'],"
        " 'head': doc['freeze_surface']['repo_head_commit'],"
        " 'root': doc['freeze_surface']['repo_root']}))\n"
        "except RuntimeError as exc:\n"
        "    print('FREEZE_REFUSED', str(exc))\n")
    proc = subprocess.run(
        [PY, "-c", code, "_", str(pin), str(out), sha],
        capture_output=True, text=True,
        env={"PYTHONPATH": str(project / "src"),
             "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"},
        cwd=project)
    line = (proc.stdout or "").strip().splitlines()[-1] \
        if (proc.stdout or "").strip() else ""
    return proc, line


def test_rd05_freeze_positive_real_consumer(tmp_path):
    """依赖齐全+pin HEAD==候选 ⇒ 真实 write_r17_code_freeze 写出
    工程隔离冻结产物(=audit 步将读到的合同;dev root=P3)。"""
    repo, sha, pin, project = _build_fixture(tmp_path)
    eng = tmp_path / "engineering_freeze_out"
    proc, line = _freeze_subprocess(project, pin, sha, eng, True)
    assert line.startswith("FREEZE_OK"), (line, proc.stderr[-400:])
    payload = json.loads(line[len("FREEZE_OK "):])
    assert payload["sha"] == sha
    assert payload["missing"] == []
    assert payload["head"] == sha
    assert str(pin) in payload["root"]
    assert (eng / "r17_code_freeze.json").is_file()


def test_rd05_freeze_negative_missing_env(tmp_path):
    """缺 environment.yml(上轮真实失败形态)⇒ 真实 freeze 拒绝。"""
    repo, sha, pin, project = _build_fixture(tmp_path)
    (project / "environment.yml").unlink()
    proc, line = _freeze_subprocess(
        project, pin, sha, tmp_path / "eng_neg", False)
    assert line.startswith("FREEZE_REFUSED"), (line, proc.stderr[-300:])
    assert "environment.yml" in line


def test_rd03_freeze_negative_wrong_head(tmp_path):
    """文件齐全但 pin HEAD != 候选 ⇒ 拒(不因齐件放行)。"""
    repo, sha, pin, project = _build_fixture(tmp_path)
    (repo / "stage2_6_1" / "report" / "note.txt").write_text("drift")
    _run([GIT, "add", "-A"], cwd=repo)
    _run([GIT, "commit", "-qm", "advance"], cwd=repo)
    _run([GIT, "worktree", "add", "--detach",
          str(tmp_path / "pin2"), "HEAD"], cwd=repo)
    proc, line = _freeze_subprocess(
        project, tmp_path / "pin2", sha, tmp_path / "eng_wh", False)
    assert "code_freeze_sha 与 repo HEAD" in line, (
        line, proc.stderr[-300:])


# ---- RD04:preflight 契约(两入口共同前置) ------------------------

def test_rd04_preflight_positive(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert rd["ok"], rd.get("problems")
    assert rd["repo_head_commit"] == sha
    assert str(pin) in rd["repo_root"]
    assert rd["n_dev_files"] > 300


def test_rd04_preflight_missing_env_negative(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    (project / "environment.yml").unlink()
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert not rd["ok"]
    assert any("environment.yml" in p or "缺失" in p
               for p in rd["problems"])


def test_rd04_preflight_wrong_bytes_negative(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    (project / "requirements-lock.txt").write_text("tampered")
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert not rd["ok"]
    assert any("requirements-lock.txt" in p for p in rd["problems"])


def test_rd04_preflight_src_drift_negative(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    target = next((project / "src/rl_curriculum").glob(
        "curriculum261_r10_*"))
    target.write_text("# drift")
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert not rd["ok"]
    assert any("tree_mismatched" in p for p in rd["problems"])


def test_rd04_preflight_wrong_head_negative(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    (repo / "note.txt").write_text("x")
    _run([GIT, "add", "-A"], cwd=repo)
    _run([GIT, "commit", "-qm", "advance"], cwd=repo)
    _run([GIT, "-C", str(pin), "checkout", "-q", "HEAD~1"], check=False)
    _run([GIT, "worktree", "add", "--detach",
          str(tmp_path / "pin2"), "HEAD"], cwd=repo)
    import rl_curriculum.curriculum261_qaf_provenance_guard as guard
    monkeypatch.setattr(guard, "R17_PIN_EXPECTED_ROOT",
                        str(tmp_path / "pin2"))
    rd = runtime_dependency_preflight(
        repo=repo, project_dir=project, candidate_sha=sha, python=PY)
    assert not rd["ok"]
    assert any("HEAD" in p for p in rd["problems"])


def test_rd04_preflight_dirty_pin_negative(tmp_path, monkeypatch):
    repo, sha, pin, project = _build_fixture(tmp_path)
    _d = (pin / "stage2_6_1" / "runner").rglob("*.py")
    next(_d).write_text("# dirty")
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert not rd["ok"]
    assert any("dirty" in p for p in rd["problems"])


def test_rd04_preflight_non_pin_resolution_negative(
        tmp_path, monkeypatch):
    """pin 不在场 ⇒ 解析回退到 /mnt/f(非 pin)⇒ 错源拒。"""
    repo, sha, pin, project = _build_fixture(tmp_path)
    _run([GIT, "worktree", "remove", "--force", str(pin)], cwd=repo)
    rd = _preflight(repo, sha, pin, project, monkeypatch, tmp_path)
    assert not rd["ok"]
    assert any("非 pinned 源" in p for p in rd["problems"])


def test_rd04_gate_enforced_before_first_write(tmp_path, monkeypatch):
    """preissue_gate(qaf_v3;两入口共同前置)在缺件时拒,
    零一次性写。"""
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    repo, sha, pin, project = _build_fixture(tmp_path)
    import rl_curriculum.curriculum261_qaf_provenance_guard as guard
    monkeypatch.setattr(guard, "R17_PIN_EXPECTED_ROOT", str(pin))
    # 候选仓内补充钉死 provenance 两件(真实来源字节)并重订 pin
    from test_curriculum261_qaf_v2_preissue_guard import _guard_repo
    grepo = _guard_repo()
    pin_commit = guard.PROVENANCE_SOURCE_COMMIT_DEFAULT
    for rel in ("gate_topology_reconciliation.json",
                "gate_topology_reconciliation_digest.txt"):
        base = ("stage2_6_1/artifacts/repair17/development/"
                "formal_freeze_binding_v1/provenance/")
        blob = _run([GIT, "-C", str(grepo), "cat-file", "blob",
                     f"{pin_commit}:{base}{rel}"],
                    check=False).stdout
        dst = repo / base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(blob, encoding="utf-8", newline="\n")
    _run([GIT, "add", "-A"], cwd=repo)
    _run([GIT, "commit", "-qm", "candidate A + pinned provenance"],
         cwd=repo)
    sha = _run([GIT, "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    _run([GIT, "worktree", "remove", "--force", str(pin)], cwd=repo)
    pin = tmp_path / "release_pin"
    _run([GIT, "worktree", "add", "--detach", str(pin), sha], cwd=repo)
    _orig_rps = guard.read_pinned_source
    monkeypatch.setattr(
        guard, "read_pinned_source",
        lambda r, **kw: _orig_rps(r, commit=sha, **kw))
    deploy = tmp_path / "deploy"
    art = deploy / "artifacts" / "formal_a_qaf_v3"
    art.mkdir(parents=True)
    from test_curriculum261_qaf_v2_preissue_guard import (
        _guard_repo,
    )
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
    (project / "environment.yml").unlink()
    gate = preissue_gate(
        repo=repo, deploy_root=deploy, project_dir=project,
        attempt="qaf_v3", candidate_sha=sha, python=PY)
    assert not gate.get("ok")
    assert "runtime_dependencies" in gate.get("refusal", "")
    assert gate["one_shot_writes"] == 0
    assert not (deploy / "authority").exists()


# ---- RD06:qaf_v3 身份 -------------------------------------------

def test_rd06_qaf_v3_registry_identity():
    assert QAF3_ATTEMPT_ID == "qaf_v3"
    assert QAF3_ATTEMPT_ID in QAF_ATTEMPTS
    assert QAF3_ATTEMPT_ID in QAF_ATTEMPT_IDS  # CLI choices 单一来源
    assert len(QAF3_ALL_NEW) == 26
    assert len(set(QAF3_ALL_NEW)) == 26
    v1 = set(QAF_ATTEMPTS["qaf_v1"].input_scope)
    v2 = set(QAF_ATTEMPTS["qaf_v2"].input_scope)
    assert not (set(QAF3_ALL_NEW) & v1)
    assert not (set(QAF3_ALL_NEW) & v2)
    assert qaf_iteration_id_for_attempt("qaf_v3") == "qprod_a_formal_v3"
    assert qaf_input_scope_for_attempt("qaf_v3") == QAF3_INPUT_SCOPE


def test_rd06_qaf_v3_design_names_explicit():
    fam = QAF_ATTEMPTS["qaf_v3"]
    assert fam.design_matched_main == "design_qaf_v3_matched_main"
    assert fam.design_matched_validation == (
        "design_qaf_v3_matched_validation")
    assert fam.design_independent == (
        "design_qaf_v3_independent_marginal")


def test_rd06_qaf_v3_api_wiring(tmp_path):
    """部署树 api 接线:v3 常量导入与 recorder 迭代匹配表首项
    (注册表精确成员优先于子串序)。"""
    repo, sha, pin, project = _build_fixture(tmp_path)
    api_src = (project / "src/rl_curriculum/curriculum261_api.py"
               ).read_text(encoding="utf-8")
    assert "QAF3_ALL_NEW as _QAF_V3_ATTEMPT_NAMESPACES" in api_src
    assert '(_QAF_V3_ATTEMPT_NAMESPACES, "qaf_v3")' in api_src
    # 部署树内导入面实测(真实 import 链)
    code = subprocess.run(
        [PY, "-c",
         "import rl_curriculum.curriculum261_api as api; "
         "ns = api._QAF_V3_ATTEMPT_NAMESPACES; "
         "assert len(ns) == 26; "
         "assert 'design_qaf_v3_independent_marginal' in ns; "
         "print('API_WIRING_OK')"],
        capture_output=True, text=True,
        env={"PYTHONPATH": str(project / "src"),
             "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"},
        cwd=project)
    assert "API_WIRING_OK" in code.stdout, code.stderr[-500:]
