# -*- coding: utf-8 -*-
"""R25 后代退出登记与核验工程测试。

RouteC_R25_FinalClosure_TrainingReadiness_v1 增量:
  F01 生产端身份读取故障(PermissionError/FileNotFoundError,root 与
      已创建 descendant)→ 登记显式拒绝(rc=6,登记文件不发布,自有
      实例收尾);握手有效时握手身份为优先来源,/proc 直读故障不
      冒充也不阻断;
  F02 消费端拒无效身份:负数/布尔/浮点/缺值,不因同 PID 存活实例
      变成 pid_reused_old_dead;
  F03 新 producer 合法登记正例 + 同格式副本变异(缺 child/grand/
      root 记录、重复实例、清单矛盾)→ 非 clean,且负例后代真实
      存活、检查前后同一实例、检测后驱动器 finally 清理;
  F04 无后代正例须有可信依据;空/无依据/矛盾材料不 clean;
  F06 僵尸与确定性 PID 错配(模拟,如实标注);
  F07 登记写失败 → 不发布、不继续长任务、只按自有句柄收尾。

保留上轮 C01–C05/C07 既有正反例(v2 格式化夹具)。
注入边界纪律:故障注入仅落在 r25_worker_probe._read_proc_stat
(writer 的 /proc stat 读取口)或握手载荷观测,checker 一律在
独立完整 CLI 进程中读取材料,不注入任何观察替身。
"""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_DEPLOY_ROOT = Path(__file__).resolve().parents[2]
_PROBE = _DEPLOY_ROOT / "stage2_6_1_runner" / "r25_worker_probe.py"
_PY = sys.executable

_spec = importlib.util.spec_from_file_location("r25_worker_probe", _PROBE)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

#: 本模块创建/拥有的全部实例 pid(收尾核验口径;与全局进程无关)
_OWNED: set[int] = set()


def _run_probe(*args, timeout=60):
    return subprocess.run(
        [_PY, str(_PROBE), *args], capture_output=True, text=True,
        timeout=timeout)


def _proc_instance(pid: int):
    """(exists, state, start_ticks);None=不可观测。"""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return (False, "", -1)
    except OSError:
        return None
    try:
        rp = text.rindex(")")
        fields = text[rp + 2:].split()
        return (True, fields[0], int(fields[19]))
    except (ValueError, IndexError):
        return None


def _alive_same_instance(pid: int, start_ticks: int) -> bool:
    inst = _proc_instance(pid)
    return inst is not None and inst[0] and inst[2] == start_ticks \
        and inst[1] != "Z"


def _kill_by_identity(pid: int, start_ticks: int,
                      sig=signal.SIGKILL) -> None:
    """仅对 (pid, start_ticks) 匹配的自有实例发信号;不按裸 PID。"""
    inst = _proc_instance(pid)
    if inst is not None and inst[0] and inst[2] == start_ticks:
        os.kill(pid, sig)


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        inst = _proc_instance(pid)
        if inst is not None and not inst[0]:
            return True
        time.sleep(0.1)
    return False


def _parse_spawned(out_text: str) -> dict:
    """从 writer stdout 中取登记前打印的 spawned 行(含子/孙身份)。"""
    spawned = None
    for line in out_text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("event") == "spawned":
            spawned = obj["spawned"]
    assert spawned is not None, "spawned 行缺失(登记前应已打印)"
    for pid in (spawned["child"]["pid"],
                spawned["grandchild"]["pid"]):
        _OWNED.add(pid)
    return spawned


def _v2_payload(root_pid: int, root_ticks: int, *, roles=("root",),
                created_desc=None, no_ver=None, basis="fixture-basis",
                instances=None):
    """构造 v2 登记夹具;默认为自洽的无后代正例形状。"""
    if created_desc is None:
        created_desc = list(roles) != ["root"]
    if no_ver is None:
        no_ver = (not created_desc)
    if instances is None:
        instances = [{"pid": root_pid, "start_ticks": root_ticks,
                      "role": "root"}]
    return {
        "format": "r25-worker-registry-v2",
        "created_utc": "2026-09-28T00:00:00Z",
        "driver_label": "test-fixture",
        "root_pid": root_pid,
        "created_descendants": created_desc,
        "created_roles": list(roles),
        "no_descendants_verified": no_ver,
        "no_descendants_basis": (None if created_desc else basis),
        "identity_sources": {"root": "fixture"},
        "instances": instances,
    }


@pytest.fixture()
def orphan_fixture(tmp_path):
    """启动 orphan 根并等到其退出;yield (reg_path, 实例dict, tmp_path)。

    TTL 60s 有限;finally 只按 (pid, start_ticks) 匹配清理自有实例。
    """
    reg = tmp_path / "orphan_reg.json"
    proc = subprocess.Popen(
        [_PY, str(_PROBE), "--label", "orphanroot", "--mode", "orphan",
         "--seconds", "60", "--registry-out", str(reg)],
        stdout=subprocess.PIPE, text=True)
    _OWNED.add(proc.pid)
    root_line = json.loads(proc.stdout.readline())
    proc.wait(timeout=30)
    assert proc.returncode == 0
    registry = json.loads(reg.read_text(encoding="utf-8"))
    assert root_line["pid"] == registry["root_pid"]
    inst = {i["role"]: i for i in registry["instances"]}
    assert set(inst) == {"root", "child", "grandchild"}
    # v2:登记身份全部有效(实测正整数),无 -1 占位
    for row in inst.values():
        assert type(row["start_ticks"]) is int
        assert row["start_ticks"] >= 1
    assert registry["created_roles"] == ["root", "child", "grandchild"]
    for row in inst.values():
        _OWNED.add(row["pid"])
    try:
        yield reg, inst, tmp_path
    finally:
        # C07:检测与清理分离;checker 只读,驱动器负责收尾
        for role in ("child", "grandchild"):
            _kill_by_identity(inst[role]["pid"],
                              inst[role]["start_ticks"])
        _wait_gone(inst["child"]["pid"])
        _wait_gone(inst["grandchild"]["pid"])


class TestRegistryPositiveC01:
    def test_burn_with_children_clean_exit(self, tmp_path):
        reg = tmp_path / "w_reg.json"
        proc = _run_probe("--label", "c01w", "--mode", "burn",
                          "--seconds", "3", "--spawn-child",
                          "--registry-out", str(reg))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        registry = json.loads(reg.read_text(encoding="utf-8"))
        assert registry["created_roles"] == ["root", "child",
                                             "grandchild"]
        assert all(type(i["start_ticks"]) is int and i["start_ticks"] >= 1
                   for i in registry["instances"])
        check = _run_probe("--check-registry", "--identity", str(reg))
        assert check.returncode == 0, check.stdout + check.stderr
        out = json.loads(check.stdout)
        assert out["verdict"] == "clean"
        assert all(i["status"] == "dead_gone" for i in out["instances"])
        assert len(out["instances"]) == 3  # root+child+grandchild

    def test_sleep_without_children_clean(self, tmp_path):
        reg = tmp_path / "w_reg.json"
        proc = _run_probe("--label", "c01s", "--mode", "sleep",
                          "--seconds", "2", "--registry-out", str(reg))
        assert proc.returncode == 0
        check = _run_probe("--check-registry", "--identity", str(reg))
        assert check.returncode == 0
        out = json.loads(check.stdout)
        assert out["verdict"] == "clean"
        # 无后代声明有显式依据,非空清单默认成功
        registry = json.loads(reg.read_text(encoding="utf-8"))
        assert registry["created_descendants"] is False
        assert registry["no_descendants_verified"] is True
        assert registry["no_descendants_basis"]
        assert registry["created_roles"] == ["root"]


class TestOrphanNegativesC02C03:
    """根退出留活孤儿(真实反例)→ checker 必拒;检测后由驱动器清理。"""

    def test_c02_root_dead_children_alive_rejected(self, orphan_fixture):
        reg, inst, _ = orphan_fixture
        child, grand = inst["child"], inst["grandchild"]
        # 根已退出;子/孙存活且与登记同实例(检查前握手)
        assert _alive_same_instance(child["pid"], child["start_ticks"])
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])
        check = _run_probe("--check-registry", "--identity", str(reg))
        assert check.returncode == 3
        out = json.loads(check.stdout)
        assert out["verdict"] == "leaked_alive"
        alive = {i["role"] for i in out["instances"]
                 if i["status"] == "alive"}
        assert alive == {"child", "grandchild"}
        root_row = next(i for i in out["instances"]
                        if i["role"] == "root")
        assert root_row["status"] == "dead_gone"
        # 检查后仍存活且同实例(检测未动它们;checker 只读)
        assert _alive_same_instance(child["pid"], child["start_ticks"])
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])

    def test_c03_child_dead_grandchild_alive_rejected(self,
                                                      orphan_fixture):
        reg, inst, _ = orphan_fixture
        child, grand = inst["child"], inst["grandchild"]
        # 中间父退出(SIGKILL,不触发任何清理),孙成为孤儿仍存活
        _kill_by_identity(child["pid"], child["start_ticks"])
        assert _wait_gone(child["pid"])
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])
        check = _run_probe("--check-registry", "--identity", str(reg))
        assert check.returncode == 3
        out = json.loads(check.stdout)
        alive = {i["role"] for i in out["instances"]
                 if i["status"] == "alive"}
        assert alive == {"grandchild"}
        child_row = next(i for i in out["instances"]
                         if i["role"] == "child")
        assert child_row["status"] == "dead_gone"


class TestRegistrationRefusalF01:
    """F01:真实 writer/main 控制流内身份读取故障 → 显式拒绝。

    注入边界 = probe._read_proc_stat(writer 的 /proc stat 读取口)
    或握手载荷(已拥有实例的自报身份);PermissionError 与
    FileNotFoundError 均覆盖 root 与已创建 descendant。
    """

    def _run_main_refused(self, monkeypatch, tmp_path, fault, target):
        reg = tmp_path / "refused_reg.json"
        real_read = probe._read_proc_stat

        def faulting_read(pid):
            if (target == "root") == (pid == os.getpid()):
                if fault == "permission":
                    raise PermissionError(
                        "injected ONLY at writer identity read")
                raise FileNotFoundError(
                    "injected ONLY at writer identity read")
            return real_read(pid)

        monkeypatch.setattr(probe, "_read_proc_stat", faulting_read)
        if target != "root":
            # 观测边界内的握手载荷损坏:子自报身份丢失(真实 spawn
            # 照常发生,仅握手观测值被破坏为占位 -1)。
            real_spawn = probe._spawn_child

            def corrupted_handshake_spawn(seconds):
                proc, hs = real_spawn(seconds)
                assert hs is not None
                bad = dict(hs)
                bad["start_ticks"] = -1
                return proc, bad

            monkeypatch.setattr(probe, "_spawn_child",
                                corrupted_handshake_spawn)

        t0 = time.monotonic()
        rc = probe.main(["--label", "f01", "--mode", "sleep",
                         "--seconds", "30", "--spawn-child",
                         "--registry-out", str(reg)])
        dt = time.monotonic() - t0
        return reg, rc, dt

    def _check_refusal(self, reg, rc, dt, capsys, role_hint):
        assert rc == 6
        assert dt < 15, "登记失败不得继续长任务"
        captured = capsys.readouterr()
        spawned = _parse_spawned(captured.out)
        assert not reg.exists(), "拒绝路径绝不能发布登记文件"
        failed = Path(str(reg) + ".failed.json")
        assert failed.exists()
        record = json.loads(failed.read_text(encoding="utf-8"))
        assert record["event"] == "registration_failed"
        assert role_hint in record["reason"]
        assert "registration_failed" in captured.err
        # 自有实例已收尾(合作子/孙全部退出回收)
        assert _wait_gone(spawned["child"]["pid"])
        assert _wait_gone(spawned["grandchild"]["pid"])

    def test_f01_root_permission_error_refused(self, monkeypatch,
                                               tmp_path, capsys):
        reg, rc, dt = self._run_main_refused(monkeypatch, tmp_path,
                                             "permission", "root")
        self._check_refusal(reg, rc, dt, capsys, "root")

    def test_f01_root_not_found_refused(self, monkeypatch, tmp_path,
                                        capsys):
        reg, rc, dt = self._run_main_refused(monkeypatch, tmp_path,
                                             "not_found", "root")
        self._check_refusal(reg, rc, dt, capsys, "root")

    def test_f01_child_permission_and_handshake_lost_refused(
            self, monkeypatch, tmp_path, capsys):
        reg, rc, dt = self._run_main_refused(monkeypatch, tmp_path,
                                             "permission", "child")
        self._check_refusal(reg, rc, dt, capsys, "child")

    def test_f01_child_not_found_and_handshake_lost_refused(
            self, monkeypatch, tmp_path, capsys):
        reg, rc, dt = self._run_main_refused(monkeypatch, tmp_path,
                                             "not_found", "child")
        self._check_refusal(reg, rc, dt, capsys, "child")

    def test_f01_handshake_identity_survives_proc_read_fault(
            self, monkeypatch, tmp_path, capsys):
        """握手优先来源:/proc 直读故障但握手自报有效 → 发布的登记
        身份真实有效(非 -1),且登记照常成功。"""
        reg = tmp_path / "hs_reg.json"
        real_read = probe._read_proc_stat

        def faulting_read(pid):
            if pid != os.getpid():
                raise PermissionError("injected at writer direct read")
            return real_read(pid)

        monkeypatch.setattr(probe, "_read_proc_stat", faulting_read)
        rc = probe.main(["--label", "f01h", "--mode", "sleep",
                         "--seconds", "1", "--spawn-child",
                         "--registry-out", str(reg)])
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        spawned = _parse_spawned(captured.out)
        registry = json.loads(reg.read_text(encoding="utf-8"))
        inst = {i["role"]: i for i in registry["instances"]}
        assert set(inst) == {"root", "child", "grandchild"}
        assert inst["child"]["start_ticks"] \
            == spawned["child"]["start_ticks"] >= 1
        assert inst["grandchild"]["start_ticks"] \
            == spawned["grandchild"]["start_ticks"] >= 1
        assert registry["identity_sources"]["child"] \
            == "handshake_self_report"
        # 结束后:子/孙退出回收(dead_gone),root=本 pytest 进程仍活
        # → checker 按有效身份如实报 leaked_alive/rc=3(不是 clean,
        # 也不是身份类 rc=4——证明登记身份真实可比较)
        check = _run_probe("--check-registry", "--identity", str(reg))
        assert check.returncode == 3, check.stdout + check.stderr
        out = json.loads(check.stdout)
        assert out["verdict"] == "leaked_alive"
        status = {i["role"]: i["status"] for i in out["instances"]}
        assert status["root"] == "alive"
        assert status["child"] == "dead_gone"
        assert status["grandchild"] == "dead_gone"

class TestIdentityInvalidF02:
    """F02:当前格式 consumer 收无效身份 → 完整 CLI 非零非 clean,
    原因对应身份字段;同 PID 存活实例不得变 pid_reused_old_dead。
    """

    def test_f02_invalid_start_ticks_with_live_instance(self, tmp_path):
        holder = subprocess.Popen([_PY, "-c",
                                   "import time; time.sleep(30)"])
        _OWNED.add(holder.pid)
        try:
            inst = _proc_instance(holder.pid)
            assert inst and inst[0]
            cases = [
                ("neg1", -1),
                ("bool_true", True),
                ("bool_false", False),
                ("float", 1.5),
                ("zero", 0),
            ]
            for name, bad_ticks in cases:
                payload = _v2_payload(
                    holder.pid, inst[2],
                    instances=[{"pid": holder.pid,
                                "start_ticks": bad_ticks,
                                "role": "root"}])
                p = tmp_path / f"{name}.json"
                p.write_text(json.dumps(payload, ensure_ascii=False),
                             encoding="utf-8")
                check = _run_probe("--check-registry", "--identity",
                                   str(p))
                assert check.returncode == 4, \
                    f"{name}: {check.stdout}"
                out = json.loads(check.stdout)
                assert out["verdict"] == "registry_incomplete"
                assert "身份不合法" in out["reason"]
                assert "start_ticks" in out["reason"]
                # 关键:不因该 PID 当前存活且 ticks 不匹配而变
                # pid_reused_old_dead/clean——无效身份没有比较资格
                assert "pid_reused" not in check.stdout
                assert _alive_same_instance(holder.pid, inst[2])
        finally:
            holder.terminate()
            holder.wait(timeout=10)

    def test_f02_invalid_pid_values(self, tmp_path):
        cases = [
            ("bool_pid", {"start_ticks": 7, "role": "root"}),
            ("zero_pid", {"pid": 0, "start_ticks": 7, "role": "root"}),
            ("neg_pid", {"pid": -5, "start_ticks": 7, "role": "root"}),
            ("str_pid", {"pid": "1", "start_ticks": 7, "role": "root"}),
        ]
        for name, entry in cases:
            payload = _v2_payload(1, 7, instances=[entry])
            p = tmp_path / f"{name}.json"
            p.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
            check = _run_probe("--check-registry", "--identity", str(p))
            assert check.returncode == 4, f"{name}: {check.stdout}"
            out = json.loads(check.stdout)
            assert out["verdict"] == "registry_incomplete"
            assert "身份不合法" in out["reason"]


class TestMutatedCopyF03:
    """F03:新 producer 正例的副本变异(同 v2 格式)→ 非 clean。

    真根退出、真子/孙存活,检查前后同一实例证据,检测后由夹具
    finally 清理;checker 只读。
    """

    def _mutated(self, tmp_path, registry, name, mutate):
        data = json.loads(json.dumps(registry))  # 深拷贝
        mutate(data)
        p = tmp_path / f"mut_{name}.json"
        p.write_text(json.dumps(data, ensure_ascii=False),
                     encoding="utf-8")
        return p

    def test_f03_omit_child_record_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        child, grand = inst["child"], inst["grandchild"]
        assert _alive_same_instance(child["pid"], child["start_ticks"])
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            d["instances"] = [i for i in d["instances"]
                              if i["role"] != "child"]

        p = self._mutated(tmp_path, registry, "omit_child", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4, check.stdout
        out = json.loads(check.stdout)
        assert out["verdict"] == "registry_incomplete"
        assert "矛盾" in out["reason"]
        # 检查前后同一存活实例(child 仍活;checker 未动它)
        assert _alive_same_instance(child["pid"], child["start_ticks"])
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])

    def test_f03_omit_grandchild_record_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        grand = inst["grandchild"]
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            d["instances"] = [i for i in d["instances"]
                              if i["role"] != "grandchild"]

        p = self._mutated(tmp_path, registry, "omit_grand", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        assert _alive_same_instance(grand["pid"], grand["start_ticks"])

    def test_f03_omit_root_record_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            d["instances"] = [i for i in d["instances"]
                              if i["role"] != "root"]

        p = self._mutated(tmp_path, registry, "omit_root", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert "root" in out["reason"]

    def test_f03_duplicate_instance_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            child = next(i for i in d["instances"]
                         if i["role"] == "child")
            d["instances"].append(dict(child))

        p = self._mutated(tmp_path, registry, "dup_child", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert "重复" in out["reason"] or "矛盾" in out["reason"]

    def test_f03_roles_instance_mismatch_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            d["created_roles"] = ["root", "child"]  # 声明缺 grandchild

        p = self._mutated(tmp_path, registry, "roles_mismatch", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert "矛盾" in out["reason"]

    def test_f03_root_association_missing_not_clean(self, orphan_fixture):
        reg, inst, tmp_path = orphan_fixture
        registry = json.loads(reg.read_text(encoding="utf-8"))

        def mutate(d):
            d["root_pid"] = d["root_pid"] + 1  # 指向不存在的关联

        p = self._mutated(tmp_path, registry, "root_assoc", mutate)
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert "root 关联" in out["reason"]


class TestNoDescendantsBasisF04:
    """F04:无后代材料必须有可信依据;空/无依据/矛盾不 clean。"""

    def test_f04_empty_or_missing_basis_rejected(self, tmp_path):
        for name, basis in (("empty_basis", ""), ("none_basis", None),
                            ("blank_basis", "   ")):
            payload = _v2_payload(1, 7, basis=basis)
            payload["no_descendants_basis"] = basis
            p = tmp_path / f"{name}.json"
            p.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")
            check = _run_probe("--check-registry", "--identity",
                               str(p))
            assert check.returncode == 4, f"{name}: {check.stdout}"
            out = json.loads(check.stdout)
            assert "无后代" in out["reason"]

    def test_f04_contradictory_roles_rejected(self, tmp_path):
        # 声明无后代却带 child 记录 / created_roles 与声明矛盾
        payload = _v2_payload(
            1, 7, roles=("root", "child"), created_desc=False,
            no_ver=True, basis="x",
            instances=[{"pid": 1, "start_ticks": 7, "role": "root"},
                       {"pid": 2, "start_ticks": 8, "role": "child"}])
        p = tmp_path / "contra.json"
        p.write_text(json.dumps(payload, ensure_ascii=False),
                     encoding="utf-8")
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4

    def test_f04_missing_created_roles_rejected(self, tmp_path):
        payload = _v2_payload(1, 7)
        del payload["created_roles"]
        p = tmp_path / "no_roles.json"
        p.write_text(json.dumps(payload, ensure_ascii=False),
                     encoding="utf-8")
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert "created_roles" in out["reason"]


class TestRegistryInvalidC04C05:
    def _write(self, tmp_path: Path, name: str, payload) -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(payload, ensure_ascii=False),
                     encoding="utf-8")
        return p

    def test_c04_missing_file_is_not_clean(self, tmp_path):
        check = _run_probe("--check-registry", "--identity",
                           str(tmp_path / "nope.json"))
        assert check.returncode == 4

    def test_c04_bad_json_not_clean(self, tmp_path):
        p = tmp_path / "reg.json"
        p.write_text("{broken", encoding="utf-8")
        assert _run_probe("--check-registry", "--identity",
                          str(p)).returncode == 4

    def test_c04_old_v1_format_rejected(self, tmp_path):
        """v1 为历史缺陷格式(可含 -1/缺记录),一律拒绝。"""
        p = self._write(tmp_path, "v1.json", {
            "format": "r25-worker-registry-v1",
            "created_utc": "x", "root_pid": 1,
            "created_descendants": True,
            "no_descendants_verified": False,
            "instances": [{"pid": 1, "start_ticks": -1,
                           "role": "root"}]})
        check = _run_probe("--check-registry", "--identity", str(p))
        assert check.returncode == 4
        out = json.loads(check.stdout)
        assert out["verdict"] == "registry_invalid"

    def test_c04_empty_or_incomplete_registry_not_clean(self, tmp_path):
        empty = self._write(tmp_path, "a.json",
                            _v2_payload(1, 7, instances=[]))
        assert _run_probe("--check-registry", "--identity",
                          str(empty)).returncode == 4
        no_ticks = self._write(tmp_path, "b.json", _v2_payload(
            1, 7, instances=[{"pid": 1, "role": "root"}]))
        assert _run_probe("--check-registry", "--identity",
                          str(no_ticks)).returncode == 4
        no_proof = self._write(tmp_path, "c.json", _v2_payload(
            1, 7, no_ver=False, basis=None))
        assert _run_probe("--check-registry", "--identity",
                          str(no_proof)).returncode == 4

    def test_c05_instance_mismatch_is_reuse_not_ours(self, tmp_path):
        """同 PID 不同 starttime:不当作旧实例存活,也不向其发信号。

        确定性观察夹具(非内核级真实 PID 复用,如实标注为模拟):
        对活进程登记错误 starttime,登记身份本身有效(正整数),
        checker 应判 pid_reused_old_dead 且 clean,并保持该进程
        不受影响。
        """
        holder = subprocess.Popen([_PY, "-c",
                                   "import time; time.sleep(30)"])
        _OWNED.add(holder.pid)
        try:
            inst = _proc_instance(holder.pid)
            assert inst and inst[0]
            wrong_ticks = inst[2] + 7
            reg = self._write(tmp_path, "m.json", _v2_payload(
                holder.pid, wrong_ticks))
            check = _run_probe("--check-registry", "--identity",
                               str(reg))
            assert check.returncode == 0
            out = json.loads(check.stdout)
            assert out["verdict"] == "clean"
            assert out["instances"][0]["status"] == "pid_reused_old_dead"
            # checker 只读:该活进程不受影响
            after = _proc_instance(holder.pid)
            assert after and after[0] and after[2] == inst[2]
        finally:
            holder.terminate()
            holder.wait(timeout=10)


class TestZombieF06:
    def test_f06_zombie_reported_not_clean_then_reaped(self, tmp_path):
        """僵尸(zombie_unreaped)与 clean 区分;checker 不回收;
        由本测试 waitpid 回收自有实例。"""
        victim = subprocess.Popen([_PY, "-c",
                                   "import time; time.sleep(30)"])
        _OWNED.add(victim.pid)
        inst = _proc_instance(victim.pid)
        assert inst and inst[0]
        os.kill(victim.pid, signal.SIGKILL)
        time.sleep(0.3)
        z = _proc_instance(victim.pid)
        assert z and z[0] and z[1] == "Z", "夹具应产生僵尸"
        reg = tmp_path / "zombie_reg.json"
        reg.write_text(json.dumps(
            _v2_payload(victim.pid, inst[2], basis="fixture-zombie"),
            ensure_ascii=False), encoding="utf-8")
        try:
            check = _run_probe("--check-registry", "--identity",
                               str(reg))
            assert check.returncode == 2
            out = json.loads(check.stdout)
            assert out["verdict"] == "zombie_unreaped"
            assert out["instances"][0]["status"] == "zombie_unreaped"
            # checker 只读:僵尸仍在(未代为回收)
            after = _proc_instance(victim.pid)
            assert after and after[0] and after[1] == "Z"
        finally:
            got, _status = os.waitpid(victim.pid, 0)
            assert got == victim.pid
        assert _wait_gone(victim.pid), "回收后 /proc 应消失"


class TestWriteFailureF07:
    def test_f07_registry_write_failure_refuses_and_terminates(
            self, tmp_path, capsys):
        """登记写不出(父路径被文件占据)→ 不发布、不进长任务、
        只按自有句柄收尾;失败事实不落盘(不可写)时必须进 stderr。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        reg = blocker / "reg.json"
        t0 = time.monotonic()
        rc = probe.main(["--label", "f07", "--mode", "sleep",
                         "--seconds", "30", "--spawn-child",
                         "--registry-out", str(reg)])
        dt = time.monotonic() - t0
        assert rc == 6
        assert dt < 15, "写失败不得继续长任务"
        captured = capsys.readouterr()
        spawned = _parse_spawned(captured.out)
        assert not reg.exists()
        assert "登记写入失败" in captured.err
        assert "registration_failed" in captured.err
        assert "failed_facts_write_error" in captured.err
        # 自有实例收尾(不凭不可信登记,直接句柄收尾)
        assert _wait_gone(spawned["child"]["pid"])
        assert _wait_gone(spawned["grandchild"]["pid"])


class TestFinalCleanupC07:
    def test_no_owned_instances_left_after_suite(self):
        """C07:本模块登记的全部自有实例均已退出(模块口径,不假设
        共享套件里其他模块没有自己的子进程;/proc 直读,不 spawn)。
        """
        leftover = []
        for pid in sorted(_OWNED):
            inst = _proc_instance(pid)
            if inst is None:
                leftover.append(f"{pid}(unobservable)")
            elif inst[0]:
                leftover.append(f"{pid}({inst[1]},start={inst[2]})")
        assert not leftover, f"仍有本模块自有实例存活: {leftover}"
