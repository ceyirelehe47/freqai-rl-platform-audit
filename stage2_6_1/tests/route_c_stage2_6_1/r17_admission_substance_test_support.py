# -*- coding: utf-8 -*-
"""准入实质绑定(v3)测试支撑:沙箱 git 仓库 / 真实执行器运行 /
回归证据 record 负例改造器 / preregistration 构造器。

2026-09-25 v3 升级(RouteC_FullCollection_ResearchDesign_NextGoal_v1):
沙箱仓携带真实测试源树(canonical 模块 = plain + parametrize×3 +
参数化 fixture×2 + pytest_generate_tests×2,全部真实 pytest 展开;
conftest + 7 个历史 skip 桩模块[skip 标记真实生效];src/rl_curriculum
__init__)。合法完整证据不再由 helper 合成,而是由真实执行器
runner/r21_full_collection_regression.py 在沙箱部署面上采集:
collection/execution stdout、junit、env、record 全部为真实原件。
负例 = 复制运行目录后定向改造(record 字段/原件字节),经被测包
真实函数核验;不再提供"调用方自写 collection 列表"的构造路径。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from rl_curriculum.curriculum261_r17_admission_substance import (
    HISTORICAL_SKIP_IDS,
    candidate_hook_bindings,
    REGRESSION_EVIDENCE_FORMAT,
    candidate_test_map,
    junit_nodeid,
    parse_junit,
    verify_preregistration_substance,
)

_SANDBOX_MODULE = "test_sandbox"

#: canonical 沙箱模块:覆盖本项目参数化语义的全部形态。
_CANONICAL_SOURCE = '''# sandbox canonical test module (generated)
import pytest


def test_plain_ok():
    assert True


@pytest.mark.parametrize("x", [0, 1, 2])
def test_parameter(x):
    assert x in (0, 1, 2)


@pytest.fixture(params=["fa", "fb"])
def fixture_param(request):
    return request.param


def test_fixture_param(fixture_param):
    assert fixture_param in ("fa", "fb")


def test_generated(gen_param):
    assert gen_param in ("g1", "g2")
'''

#: 沙箱 conftest:pytest_generate_tests 是被允许的动态收集形态
#: (A03 验收项),不是过滤 hook(_verify_conftest_hooks 只拒绝
#: pytest_collection_modifyitems / pytest_ignore_collect)。
_SANDBOX_CONFTEST = '''# sandbox conftest (generated)


def pytest_generate_tests(metafunc):
    if "gen_param" in metafunc.fixturenames:
        metafunc.parametrize("gen_param", ["g1", "g2"])
'''


#: A01 反例树:三参数实例之一有意失败(审查 probe 形状)。
_PROBE_SOURCE = '''# sandbox probe module (one param instance intentionally fails)
import pytest


def test_probe_plain_ok():
    assert True


@pytest.mark.parametrize("x", [0, 1, 2])
def test_parameter(x):
    assert x != 1
'''

#: R22/A01 反例树(审查 probe_worktree 形状):conftest 以 import
#: 形式引入 pytest_pycollect_makeitem(绕过 v3 只查顶层 def 的
#: _CONFT_HOOKS),LOCAL_QUICK_TESTS 门控在收集早期移除失败参数
#: 实例——收集/执行一致缩减(10→9)仍可全绿。
_HOOK_SUPPORT_SOURCE = '''# sandbox selection_support (imported collection hook; review probe)
import os
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makeitem(collector, name, obj):
    outcome = yield
    if os.environ.get("LOCAL_QUICK_TESTS") == "1":
        items = outcome.get_result()
        if isinstance(items, list):
            outcome.force_result([item for item in items
                                   if item.name != "test_parameter[1]"])
'''
_HOOK_CONFTEST = ("# sandbox conftest (imported hook counterexample)\n"
                  "from .selection_support import pytest_pycollect_makeitem\n")

#: R23/A01 反例树(审查 probe_cases/scoped_specname 形状):conftest
#: 在 pytest_sessionstart 注册临时插件,hookimpl 用 specname 别名
#: 绑定 pytest_pycollect_makeitem 过滤失败参数实例,并在
#: pytest_collection_finish 的 tryfirst 回调注销自身(早于审计器
#: 结束快照)。注册包 try/except(审查 A02"异常被捕获"窄变体):
#: 审计器在注册通知处已记录事实,捕获不影响判定。静态扫描无受控
#: 钩子名字面绑定(方法名与 specname 均非受控名)。
_SCOPED_CONFTEST = '''# sandbox conftest (scoped specname temporary plugin; review probe)
import json
from pathlib import Path

import pytest


def _event(name, **values):
    with Path("scoped_plugin_events.jsonl").open("a") as handle:
        handle.write(json.dumps({"event": name, **values}) + "\\n")


class ScopedCollectionPlugin:
    @pytest.hookimpl(specname="pytest_pycollect_makeitem",
                     hookwrapper=True)
    def pytest_scoped_parameter(self, collector, name, obj):
        outcome = yield
        if name == "test_parameter":
            items = outcome.get_result()
            if isinstance(items, list):
                kept = [item for item in items
                        if getattr(item, "callspec", None) is None
                        or item.callspec.params.get("x") != 1]
                _event("filtered",
                       generated=[item.name for item in items],
                       kept=[item.name for item in kept])
                outcome.force_result(kept)

    @pytest.hookimpl(specname="pytest_collection_finish", tryfirst=True)
    def pytest_release_scope(self, session):
        session.config.pluginmanager.unregister(self)
        _event("unregistered")


def pytest_sessionstart(session):
    try:
        session.config.pluginmanager.register(
            ScopedCollectionPlugin(), "scoped_collection")
    except Exception:  # noqa: BLE001 —— 审查 A02:注册异常被捕获
        pass
    _event("registered")
'''

_TESTS_DIR = Path(__file__).resolve().parent
_EXECUTOR_CANDIDATES = (
    _TESTS_DIR.parents[1] / "runner" / "r21_full_collection_regression.py",
    _TESTS_DIR.parents[1] / "stage2_6_1" / "runner" / (
        "r21_full_collection_regression.py"),
    _TESTS_DIR.parents[1] / "stage2_6_1_runner" / (
        "r21_full_collection_regression.py"),
)

def runner_repo_path(leaf: str) -> Path:
    """发布仓 runner 面文件(执行器/审计器/签发器字节来源)。"""
    return executor_path().parent / leaf


_SUBSTANCE_SRC_CANDIDATES = (
    _TESTS_DIR.parents[1] / "src",
    _TESTS_DIR.parents[2] / "src",
)


def executor_path() -> Path:
    for path in _EXECUTOR_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "runner/r21_full_collection_regression.py 不可达: "
        + str(tuple(str(p) for p in _EXECUTOR_CANDIDATES)))


def substance_src() -> Path:
    for cand in _SUBSTANCE_SRC_CANDIDATES:
        if (cand / "rl_curriculum" / (
                "curriculum261_r17_admission_substance.py")).is_file():
            return cand
    raise FileNotFoundError("发布仓 src 包不可达")


def _skip_module_sources() -> dict[str, str]:
    """由 HISTORICAL_SKIP_IDS 权威表生成 7 个历史 skip 桩模块源
    (模块/类/方法名与表内 classname 逐字一致;真实运行中以
    pytest.mark.skip 呈现 skipped,不手抄防漂移)。"""
    modules: dict[str, dict[str | None, list[str]]] = {}
    for cid in HISTORICAL_SKIP_IDS:
        classname, name = cid.rsplit("::", 1)
        parts = classname.split(".")
        module, cls = parts[2], (parts[3] if len(parts) > 3 else None)
        modules.setdefault(module, {}).setdefault(cls, []).append(name)
    sources = {}
    for module, classes in sorted(modules.items()):
        lines = ["# sandbox historical-skip stub (generated)",
                 "import pytest", ""]
        for cls, methods in classes.items():
            if cls is None:
                for m in methods:
                    lines += [
                        "@pytest.mark.skip("
                        "reason='sandbox historical allowlist stub')",
                        f"def {m}():",
                        "    raise AssertionError('unreachable')", ""]
            else:
                lines.append(f"class {cls}:")
                for m in methods:
                    lines += [
                        "    @pytest.mark.skip("
                        "reason='sandbox historical allowlist stub')",
                        f"    def {m}(self):",
                        "        raise AssertionError('unreachable')"]
                    lines.append("")
        sources[f"{module}.py"] = "\n".join(lines) + "\n"
    return sources


def write_sandbox_test_tree(repo: Path, *, probe: bool = False,
                            imported_hook: bool = False,
                            scoped: bool = False) -> None:
    """把沙箱测试源树 + src/rl_curriculum 写入仓工作区
    (调用方负责 git add/commit)。

    src 面含真实 substance 模块字节副本:签发器要求发布仓内存在
    该模块,v3 import_surface 又要求候选 src 成员与部署 src 字节
    一致——副本而非符号链接,避免 git mode 120000 进入映射。
    imported_hook=True 写入 R22/A01 反例树(import 式收集钩子);
    scoped=True 写入 R23/A01 反例树(sessionstart 注册 specname
    别名临时插件,collection_finish 注销;静态扫描干净)。"""
    test_dir = repo / "stage2_6_1" / "tests" / "route_c_stage2_6_1"
    test_dir.mkdir(parents=True, exist_ok=True)
    if imported_hook:
        (test_dir / f"{_SANDBOX_MODULE}.py").write_text(
            _PROBE_SOURCE, encoding="utf-8")
        (test_dir / "__init__.py").write_text("", encoding="utf-8")
        (test_dir / "conftest.py").write_text(
            _HOOK_CONFTEST, encoding="utf-8")
        (test_dir / "selection_support.py").write_text(
            _HOOK_SUPPORT_SOURCE, encoding="utf-8")
    elif scoped:
        (test_dir / f"{_SANDBOX_MODULE}.py").write_text(
            _PROBE_SOURCE, encoding="utf-8")
        (test_dir / "__init__.py").write_text("", encoding="utf-8")
        (test_dir / "conftest.py").write_text(
            _SCOPED_CONFTEST, encoding="utf-8")
    else:
        (test_dir / f"{_SANDBOX_MODULE}.py").write_text(
            _PROBE_SOURCE if probe else _CANONICAL_SOURCE,
            encoding="utf-8")
        (test_dir / "conftest.py").write_text(
            "# sandbox conftest\n" if probe else _SANDBOX_CONFTEST,
            encoding="utf-8")
    for leaf, source in _skip_module_sources().items():
        (test_dir / leaf).write_text(source, encoding="utf-8")
    src_dir = repo / "stage2_6_1" / "src" / "rl_curriculum"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "__init__.py").write_text(
        "# sandbox src root\n", encoding="utf-8")
    shutil.copyfile(
        substance_src() / "rl_curriculum" / (
            "curriculum261_r17_admission_substance.py"),
        src_dir / "curriculum261_r17_admission_substance.py")
    runner_dir = repo / "stage2_6_1" / "runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    for leaf in ("r21_full_collection_regression.py",
                 "r21_collection_auditor.py",
                 "r17_admission_issue.py"):
        shutil.copyfile(runner_repo_path(leaf), runner_dir / leaf)


def git_repo_with_candidate(tmp: Path, *, probe: bool = False,
                            imported_hook: bool = False,
                            scoped: bool = False
                            ) -> tuple[Path, str, str]:
    """两提交沙箱仓(Commit A 需有 parent,满足签发器校验)。

    base 提交携带完整测试源树 + src 根 + runner 面,cand 提交为
    候选。canonical 树真实展开 = 8 通过 + 7 历史 skip;probe 树 =
    2 通过 + 1 失败 + 7 历史 skip;imported_hook 树 = R22 审查
    反例(import 式收集钩子);scoped 树 = R23 审查反例
    (sessionstart 注册 specname 别名临时插件,11 项含 1 失败,
    门控后 10 项全绿)。"""
    repo = tmp / "relrepo"
    repo.mkdir(parents=True)
    for args in (
        ("git", "init", "-q", "."),
        ("git", "config", "user.email", "sandbox@test.invalid"),
        ("git", "config", "user.name", "sandbox"),
    ):
        subprocess.run(args, cwd=str(repo), check=True)
    (repo / "base.txt").write_text("base\n")
    write_sandbox_test_tree(repo, probe=probe,
                            imported_hook=imported_hook,
                            scoped=scoped)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=str(repo),
                   check=True)
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True).stdout.strip()
    (repo / "cand.txt").write_text("cand\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "cand"], cwd=str(repo),
                   check=True)
    commit_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True).stdout.strip()
    return repo, commit_a, parent


def sync_deploy_surface(repo: Path, commit_a: str, deploy_root: Path) -> Path:
    """把候选树测试面 + src 面按映射同步到沙箱部署根
    (字节 = CR 规范化 blob)。只写沙箱,永不触真实部署面。"""
    mapping = candidate_test_map(repo, commit_a)
    target = Path(deploy_root) / "tests" / "route_c_stage2_6_1"
    target.mkdir(parents=True, exist_ok=True)
    for row in mapping.values():
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit_a}:{row['source_path']}"],
            capture_output=True, check=True).stdout
        (target / Path(row["deploy_path"]).name).write_bytes(
            blob.replace(b"\r", b""))
    src_tree = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit_a,
         "--", "stage2_6_1/src/rl_curriculum/"],
        capture_output=True, check=True, text=True).stdout
    src_dir = Path(deploy_root) / "src" / "rl_curriculum"
    src_dir.mkdir(parents=True, exist_ok=True)
    for rel in [ln for ln in src_tree.splitlines() if ln.endswith(".py")]:
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit_a}:{rel}"],
            capture_output=True, check=True).stdout
        (src_dir / rel.rsplit("/", 1)[-1]).write_bytes(
            blob.replace(b"\r", b""))
    # v4 执行面:runner 目录(executor/auditor/issuer)按候选 blob
    # CR 规范化字节同步(record executor_face 绑定部署字节)。
    runner_dir = Path(deploy_root) / "stage2_6_1_runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    for rel in ("stage2_6_1/runner/r21_full_collection_regression.py",
                "stage2_6_1/runner/r21_collection_auditor.py",
                "stage2_6_1/runner/r17_admission_issue.py"):
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit_a}:{rel}"],
            capture_output=True, check=True).stdout
        (runner_dir / rel.rsplit("/", 1)[-1]).write_bytes(
            blob.replace(b"\r", b""))
    return target


def run_executor(out_dir: Path, repo: Path, commit_a: str,
                 deploy_root: Path, *, protocol: str = "full",
                 differential: Path | None = None, shards: list[str] | None = None,
                 expect_rc: tuple = (0, 3)) -> tuple[Path, dict, int]:
    """在沙箱部署面真实执行 r21_full_collection_regression.py。

    返回 (run_dir, summary, rc)。合法运行 expect_rc=(0,);
    负例树/拒绝场景放宽。substance 模块取真实发布仓 src。"""
    command = [
        sys.executable, str(executor_path()),
        "--repo", str(repo), "--commit-a", commit_a,
        "--deploy-root", str(deploy_root), "--out-dir", str(out_dir),
        "--substance-src", str(substance_src()),
    ]
    # v4:合法生成 hook 批准 = 候选树静态绑定集合(canonical 沙箱
    # conftest 的 pytest_generate_tests;真实树为空)。
    bindings = candidate_hook_bindings(
        repo, commit_a, candidate_test_map(repo, commit_a))
    for deploy_path, rows in sorted(bindings.items()):
        if any(row["hook"] == "pytest_generate_tests" for row in rows):
            command += ["--approved-generate-tests", deploy_path]
    if protocol != "full":
        command += ["--protocol", protocol]
    if differential is not None:
        command += ["--differential", str(differential)]
    for shard in (shards or []):
        command += ["--shard", shard]
    proc_env = {k: v for k, v in os.environ.items()
                if not k.startswith("PYTEST_")}
    proc = subprocess.run(command, capture_output=True, text=True,
                          timeout=900, env=proc_env)
    assert proc.returncode in expect_rc, (
        f"executor rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    summary = json.loads((Path(out_dir) / "summary.json").read_text(
        encoding="utf-8")) if (Path(out_dir) / "summary.json").is_file() \
        else {"raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return Path(out_dir), summary, proc.returncode


def record_path(run_dir: Path) -> Path:
    return Path(run_dir) / "regression_evidence_v3_record.json"


def read_record(run_dir: Path) -> dict:
    return json.loads(record_path(run_dir).read_text(encoding="utf-8"))


def copy_run(run_dir: Path, dest: Path) -> Path:
    """复制完整运行目录(record 原件相对路径保持自洽)。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copytree(run_dir, dest, dirs_exist_ok=True)
    return dest


def edit_record(run_dir: Path, mutate) -> Path:
    """加载 record → mutate(record) → 原位写回(sha 由调用方自理)。"""
    path = record_path(run_dir)
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path


def rehash_artifact(run_dir: Path, name: str) -> str:
    """原件被定向改造后,把 record 内对应 sha 换成新字节摘要。"""
    data = (Path(run_dir) / name).read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    def _fix(doc: dict) -> None:
        for block in (doc.get("collection_run", {}).get("runs", [])
                      + doc.get("execution", {}).get("runs", [])):
            for key in ("stdout", "stderr"):
                art = block.get(key) or {}
                if art.get("path") == name:
                    art["sha256"] = digest
        for entry in doc.get("junit", []):
            if entry.get("path") == name:
                entry["sha256"] = digest
        for block in (doc.get("collection_run", {}).get("runs", [])
                      + doc.get("execution", {}).get("runs", [])):
            art = block.get("audit") or {}
            if art.get("path") == name:
                art["sha256"] = digest
        for block in (doc.get("collection_run", {}).get("runs", [])
                      + doc.get("execution", {}).get("runs", [])):
            art = block.get("audit_lifecycle") or {}
            if art.get("path") == name:
                art["sha256"] = digest
        if doc.get("audit_manifest", {}).get("path") == name:
            doc["audit_manifest"]["sha256"] = digest
    edit_record(run_dir, _fix)
    return digest


def rewrite_collection_stdout(run_dir: Path, ids: list[str]) -> None:
    """把收集原件改写为给定 ID 全集(计数行同步)——负例构造器,
    模拟"伪造的收集输出";sha 由调用方 rehash 或保留以测替换检测。"""
    text = "\n".join(ids) + f"\n\n{len(ids)} tests collected in 0.00s\n"
    (Path(run_dir) / "collection.stdout.txt").write_text(
        text, encoding="utf-8")


def write_junit(path: Path, passed: int,
                skipped_ids=HISTORICAL_SKIP_IDS) -> Path:
    """生成与 parse_junit 兼容的最小 junit 原件(计数自洽)。

    仅服务于 parse_junit 元素级核验单元测试;v3 完整证据路径一律
    使用真实执行器产物。通过用例 = tests.route_c_stage2_6_1.
    test_sandbox 模块 test_case_0..N-1。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = []
    for i in range(passed):
        cases.append(
            f'<testcase classname="tests.route_c_stage2_6_1.test_sandbox"'
            f' name="test_case_{i}"/>')
    for cid in sorted(skipped_ids):
        classname, _, name = cid.rpartition("::")
        cases.append(
            f'<testcase classname="{classname}" name="{name}">'
            f"<skipped/></testcase>")
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuite name="sandbox" tests="{len(cases)}" failures="0" '
        f'errors="0" skipped="{len(cases) - passed}">'
        + "".join(cases) + "</testsuite>\n", encoding="utf-8")
    return path


def write_preregistration(path: Path, repo: Path, commit_a: str,
                          evidence_path: Path, *,
                          plan_digest: str | None = None,
                          admission_id: str = "sandbox-aid-0001",
                          iteration: str = "r18",
                          drop_keys: tuple = ()) -> Path:
    """构造带实质绑定字段的 preregistration(plan_digest 默认实算)。"""
    if plan_digest is None:
        plan_digest = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", commit_a + "^{tree}"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    prereg = {
        "admission_id": admission_id,
        "iteration": iteration,
        "plan_digest": plan_digest,
        "plan_digest_method": (
            "git tree digest of Commit A "
            "(git rev-parse <sha>^{tree})"),
        "regression_evidence": str(evidence_path),
        "authorization": (
            "test-harness:沙箱实质绑定验证,不触碰正式部署面"),
        "commit_a_sha": commit_a,
    }
    for key in drop_keys:
        prereg.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prereg, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def substance_fields(repo: Path, commit_a: str,
                     prereg_path: Path) -> dict:
    """经真实签发端验证路径生成 admission 的 substance 两字段。"""
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    substance = verify_preregistration_substance(
        repo, commit_a, prereg)
    from rl_curriculum.curriculum261_r17_admission_substance import (
        substance_digest)
    return {"substance": substance,
            "substance_digest": substance_digest(substance)}
