# -*- coding: utf-8 -*-
"""R25 后代退出登记与核验工程测试(RouteC_R25_BindingAndDescendantClosure_v1
C 出口:C01-C05/C07)。

真实 Linux 进程正反例:checker 只读、逐实例核验登记(pid+starttime
ticks);根退出/重托管后仍能发现存活孤儿;登记缺失不默认成功;实例
错配不误杀;检测与清理分离(驱动器 finally 只按身份匹配清理自有进程)。
无研究生成模块参与。
"""

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


def _run_probe(*args, timeout=60):
    return subprocess.run(
        [_PY, str(_PROBE), *args], capture_output=True, text=True,
        timeout=timeout)


def _proc_instance(pid: int):
    """(exists, state, start_ticks);None=不可观测。"""
    try:
        text = open(f"/proc/{pid}/stat", encoding="utf-8").read()
    except FileNotFoundError:
        return (False, "", -1)
    except OSError:
        return None
    rp = text.rindex(")")
    fields = text[rp + 2:].split()
    return (True, fields[0], int(fields[19]))


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


class TestRegistryPositiveC01:
    def test_burn_with_children_clean_exit(self, tmp_path):
        reg = tmp_path / "w_reg.json"
        proc = _run_probe("--label", "c01w", "--mode", "burn",
                          "--seconds", "3", "--spawn-child",
                          "--registry-out", str(reg))
        assert proc.returncode == 0, proc.stdout + proc.stderr
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


class TestOrphanNegativesC02C03C07:
    """根退出留活孤儿(真实反例)→ checker 必拒;检测后由驱动器清理。"""

    @pytest.fixture()
    def orphan_fixture(self, tmp_path):
        """启动 orphan 根并等到其退出;yield (reg_path, 实例dict)。

        TTL 60s 有限;finally 只按 (pid, start_ticks) 匹配清理自有实例。
        """
        reg = tmp_path / "orphan_reg.json"
        proc = subprocess.Popen(
            [_PY, str(_PROBE), "--label", "c02root", "--mode", "orphan",
             "--seconds", "60", "--registry-out", str(reg)],
            stdout=subprocess.PIPE, text=True)
        root_line = json.loads(proc.stdout.readline())
        proc.wait(timeout=30)
        assert proc.returncode == 0
        registry = json.loads(reg.read_text(encoding="utf-8"))
        assert root_line["pid"] == registry["root_pid"]
        inst = {i["role"]: i for i in registry["instances"]}
        assert set(inst) == {"root", "child", "grandchild"}
        try:
            yield reg, inst
        finally:
            # C07:检测与清理分离;checker 只读,驱动器负责收尾
            for role in ("child", "grandchild"):
                _kill_by_identity(inst[role]["pid"],
                                  inst[role]["start_ticks"])
            _wait_gone(inst["child"]["pid"])
            _wait_gone(inst["grandchild"]["pid"])

    def test_c02_root_dead_children_alive_rejected(self, orphan_fixture):
        reg, inst = orphan_fixture
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
        reg, inst = orphan_fixture
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


class TestRegistryInvalidC04C05:
    def _write(self, tmp_path: Path, name: str, payload) -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(payload, ensure_ascii=False),
                     encoding="utf-8")
        return p

    _BASE = {"format": "r25-worker-registry-v1",
             "created_utc": "x", "root_pid": 1,
             "created_descendants": True,
             "no_descendants_verified": False}

    def test_c04_missing_file_is_not_clean(self, tmp_path):
        check = _run_probe("--check-registry", "--identity",
                           str(tmp_path / "nope.json"))
        assert check.returncode == 4

    def test_c04_bad_json_not_clean(self, tmp_path):
        p = tmp_path / "reg.json"
        p.write_text("{broken", encoding="utf-8")
        assert _run_probe("--check-registry", "--identity",
                          str(p)).returncode == 4

    def test_c04_empty_or_incomplete_registry_not_clean(self, tmp_path):
        empty = self._write(tmp_path, "a.json", {**self._BASE,
                                                 "instances": []})
        assert _run_probe("--check-registry", "--identity",
                          str(empty)).returncode == 4
        no_ticks = self._write(tmp_path, "b.json", {
            **self._BASE, "instances": [{"pid": 1, "role": "root"}]})
        assert _run_probe("--check-registry", "--identity",
                          str(no_ticks)).returncode == 4
        no_proof = self._write(tmp_path, "c.json", {
            **self._BASE, "created_descendants": False,
            "no_descendants_verified": False,
            "instances": [{"pid": 1, "start_ticks": 1,
                           "role": "root"}]})
        assert _run_probe("--check-registry", "--identity",
                          str(no_proof)).returncode == 4

    def test_c05_instance_mismatch_is_reuse_not_ours(self, tmp_path):
        """同 PID 不同 starttime:不当作旧实例存活,也不向其发信号。

        确定性观察夹具(非内核级真实 PID 复用):对活进程登记错误
        starttime,checker 应判 pid_reused_old_dead 且 clean,并保持
        该进程不受影响。
        """
        holder = subprocess.Popen([_PY, "-c",
                                   "import time; time.sleep(30)"])
        try:
            inst = _proc_instance(holder.pid)
            assert inst and inst[0]
            wrong_ticks = inst[2] + 7
            reg = self._write(tmp_path, "m.json", {
                "format": "r25-worker-registry-v1",
                "created_utc": "x", "root_pid": holder.pid,
                "created_descendants": False,
                "no_descendants_verified": True,
                "instances": [{"pid": holder.pid,
                               "start_ticks": wrong_ticks,
                               "role": "root"}]})
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


class TestFinalCleanupC07:
    def test_no_owned_children_left_after_suite(self):
        """负例收尾后:本测试进程没有未回收的直接子进程。

        /proc 直读(不 spawn 子进程,避免 ps 自身成为观察伪影)。
        """
        me = os.getpid()
        own = []
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == me:
                continue
            try:
                with open(f"/proc/{name}/stat", encoding="utf-8") as fh:
                    text = fh.read()
                rp = text.rindex(")")
                fields = text[rp + 2:].split()
                if int(fields[1]) == me:
                    own.append(f"{name}({text[text.index('(') + 1:rp]},"
                               f"{fields[0]})")
            except (OSError, ValueError, IndexError):
                continue
        assert not own, f"仍有子进程未回收: {own}"
