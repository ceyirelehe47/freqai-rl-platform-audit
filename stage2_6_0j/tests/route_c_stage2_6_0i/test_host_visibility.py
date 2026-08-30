"""工作包 B:宿主状态可见性(B3/B4 + E7;真实生产路径)。

- E7:Builder 读取 /etc/beacon、宿主 conda env 路径、HOME 下文件、
  /usr、/proc/self/status、宿主 /tmp beacon -> ENOENT(不可命名,
  不只是事后记录);pack 无法依赖这些输入;
- B3:Worker 自身无 /proc(动态内核状态不可观察;外部实测进入
  EDIC);
- B4:UTS hostname 固定 builder-worker;环境身份(白名单 env)进入
  EDIC 并跨运行一致;cwd=/scratch。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.stage2_6_0i

HOST_PATHS = (
    "/etc/beacon-host-file",
    "/usr/share/beacon",
    "/proc/self/status",
    "/proc/self/maps",
    "/home/cryptorl/.bashrc",
    "/home/cryptorl/.ssh/id_rsa",
    "/etc/hostname",
)


def test_host_paths_unnameable(run_attack):
    """E7(2.6.0j 升级):宿主路径 ENOENT 由 EDIC 的 Worker 实测探针
    (report 阶段,可信代码)证明;Builder 在 Compute 内的 os.stat 探测
    被零 import 合同 + final filter 双拒(更强语义)。"""
    run = run_attack("    pass\n", label="host-unnameable",
                     max_attempts=1)
    assert isinstance(run, dict), run
    probes = run["deterministic_input_report"]["probes"]
    assert probes["host_usr"]["result"] == "ENOENT"
    assert probes["host_home"]["result"] == "ENOENT"
    assert probes["host_etc_hostname"]["result"] == "ENOENT"
    assert probes["host_sys"]["result"] == "ENOENT"
    assert probes["host_oldroot_usr"]["result"] == "ENOENT"
    denied = run_attack(
        "    import os\n"
        "    probes = {}\n"
        "    probes['usr'] = os.stat('/usr').st_ino\n"
        "    notes = {'probes': probes}\n",
        label="host-stat-denied", max_attempts=1)
    assert not isinstance(denied, dict), \
        "Compute 内宿主路径探测未被拒绝"


def test_proc_absent_and_identity_fixed(run_attack):
    """B3/B4(2.6.0j 升级):/proc 不可见与 pidns 身份由 EDIC 的 Worker
    实测(report 阶段,可信代码)证明;Builder 在 Compute 内列目录/
    取 pid 的尝试被零 import 合同 + final filter 拒绝(更强语义)。"""
    run = run_attack("    pass\n", label="proc-absent",
                     max_attempts=1)
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert edic["proc"]["mounted"] is False
    assert edic["proc"]["listing_empty"] is True
    assert edic["proc"]["self_status"] == "ENOENT"
    assert edic["pidns_self_pid"] == 1
    assert edic["supervisor"]["worker_pidns_pid"] == 1
    assert edic["uts_hostname"] == "builder-worker"
    assert edic["netns_interfaces"] == ["lo"]
    denied = run_attack(
        "    import os\n"
        "    entries = os.listdir('/proc')\n"
        "    notes = {'proc_entries': entries}\n",
        label="proc-list-denied", max_attempts=1)
    assert not isinstance(denied, dict), \
        "Compute 内列目录未被拒绝"
def test_environment_identity_stable(run_attack):
    """B4:环境身份(白名单 env/uname/cpu/cwd)进入 EDIC 且跨运行
    一致;cwd=/scratch;无宿主专属变量。"""
    r1 = run_attack("    pass\n", label="env-id", max_attempts=1)
    r2 = run_attack("    pass\n", label="env-id", max_attempts=1)
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    e1 = r1["deterministic_input_report"]["environment"]
    e2 = r2["deterministic_input_report"]["environment"]
    assert e1 == e2, "环境身份跨运行漂移"
    assert e1["cwd"] == "/scratch"
    assert e1["environ"]["TZ"] == "UTC"
    assert e1["environ"]["PYTHONHASHSEED"] == "0"
    assert e1["environ"]["HOME"] == "/scratch"
    assert "RL_SB_MOUNTOPTS" in e1["environ"]
    for key in e1["environ"]:
        assert not str(key).startswith("WSL"), f"宿主变量泄漏: {key}"


def test_scratch_fresh_and_writable(run_attack):
    """scratch 每次全新为空(Worker 启动实测进入 EDIC);2.6.0j 起
    Compute 阶段对 scratch 的读写同样被 final filter 拒绝(输入闭包
    收紧:Compute 不再有任何文件通道)。"""
    run = run_attack(
        "    pass\n",
        label="scratch-fresh", max_attempts=1)
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert edic["scratch_initial_listing"] == []
    assert edic["root_readonly"] is True
    denied = run_attack(
        "    with open('/scratch/w.txt', 'w') as fh:\n"
        "        fh.write('ok')\n"
        "    notes = {'wrote': 'ok'}\n",
        label="scratch-write-denied", max_attempts=1)
    assert not isinstance(denied, dict), \
        "Compute 阶段写 scratch 未被拒绝"
def test_dev_nodes_and_entropy_regular_files(run_attack):
    """B1/B2:/dev 只含 null/zero/full/shm + 确定性熵普通文件;无
    真实 random/urandom 设备节点。"""
    run = run_attack("    pass\n", label="dev-nodes", max_attempts=1)
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert set(edic["dev"]["nodes"]) == {
        "null", "zero", "full", "shm", "urandom", "random"}
    assert edic["dev"]["urandom_regular_file"] is True
    assert len(edic["dev"]["deterministic_entropy_sha256_prefix"]) == 16
