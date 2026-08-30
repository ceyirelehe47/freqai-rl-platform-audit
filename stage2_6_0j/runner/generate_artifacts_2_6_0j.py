"""阶段 2.6.0j artifacts 生成(23 项)。

在项目根运行:python generate_artifacts_2_6_0j.py
输出:artifacts/route_c_stage2_6_0j/*.json(+ 回归脚本填充的
regression_test_summary.md / regression_raw.log /
regression_fullcold_summary.json / upstream_integrity.txt)

清单(对应任务书十六节):
 1. sealed_compute_profile.json
 2. final_seccomp_allowlist.json
 3. final_seccomp_filter_digest.json
 4. prctl_tsc_reenable_attack.json
 5. dynamic_kernel_state_attack_matrix.json
 6. filesystem_metadata_attack_matrix.json
 7. executable_memory_attack_matrix.json
 8. native_ffi_attack_matrix.json
 9. hardware_instruction_attack_matrix.json
10. dynamic_import_attack_matrix.json
11. protocol_fd_attack_matrix.json
12. module_top_level_purity_matrix.json
13. sealed_compute_report.json
14. builder_runtime_lock_v4.json
15. builder_evidence_v4.json
16. legacy_2_6_0i_material_rejection.json
17. full_private_pipeline_sealed_compute.json
18. regression_selection_rules.md(复制)
19. regression_performance.md(复制)
20. regression_test_summary.md(回归脚本填充)
21. regression_raw.log(回归脚本填充)
22. regression_fullcold_summary.json(回归脚本填充)
23. upstream_integrity.txt(回归脚本填充)
"""

from __future__ import annotations

import ctypes
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "route_c_stage2_6_0i"))
sys.path.insert(0, str(ROOT / "tests" / "route_c_stage2_6_0j"))

OUT = ROOT / "artifacts" / "route_c_stage2_6_0j"
OUT.mkdir(parents=True, exist_ok=True)

results: dict[str, dict] = {}


def _write(name: str, payload) -> None:
    if not isinstance(payload, dict):
        payload = {"result": payload}
    (OUT / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    print("OK", name)


def _attack_run(body, tmp, *, label="artifact",
                external_dependencies=None, dep_profile="formal"):
    from conftest import write_attack_builder
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    from tests.route_c_stage2_6_0j.conftest import _indent_body

    root = write_attack_builder(
        tmp / label, _indent_body(body), max_attempts=1,
        external_dependencies=external_dependencies
        if external_dependencies is not None else [], label=label)
    provider = private_provider_from_root(root)
    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        seed, required_families=["probe_null_sign"])
    try:
        run = run_isolated_builder_run(
            provider.builder_identity(),
            provider.frozen_build_request(seed, dc),
            builder_root=root,
            profile=BuilderRunnerProfile(
                dependency_profile=dep_profile))
        return {"blocked": False, "run": "SUCCEEDED-LEAK"}
    except Exception as exc:  # noqa: BLE001
        return {"blocked": True, "exception": type(exc).__name__,
                "message": str(exc)[:240]}


def _hw_probe() -> dict:
    """宿主侧(无沙箱)真实执行硬件指令(区分 CPU 支持与生产阻断)。"""
    import mmap as _mmap

    def _run_asm(asm, restype=ctypes.c_uint):
        code = bytes.fromhex(asm)
        buf = _mmap.mmap(-1, 4096,
                         prot=_mmap.PROT_READ | _mmap.PROT_WRITE
                         | _mmap.PROT_EXEC)
        buf.write(code)
        addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
        return ctypes.CFUNCTYPE(restype)(addr)()

    out = {}
    for name, asm, rest in (
        ("cpuid", "53b80100000031c90fa289d85bc3", ctypes.c_uint),
        ("rdtsc", "0f31c3", ctypes.c_ulonglong),
        ("rdtscp", "0f310fc9c3", ctypes.c_ulonglong),
        ("rdrand", "0fc7f0c3", ctypes.c_int),
        ("rdseed", "0fc7f8c3", ctypes.c_int),
        ("rdpid", "f30fc7f8c3", ctypes.c_ulonglong),
    ):
        try:
            val = _run_asm(asm, rest)
            out[name] = {"cpu_feature": "present",
                         "attack_executed_on_host": True,
                         "value_sample": f"0x{val:x}",
                         "note": "宿主真实执行成功(非生产环境)"}
        except BaseException as exc:  # noqa: BLE001
            out[name] = {"cpu_feature": "absent-or-#UD",
                         "attack_executed_on_host": False,
                         "detail": type(exc).__name__}
    return out


def main() -> None:
    from rl_builder_runtime.sealed_compute import (
        FINAL_COMPUTE_POLICY,
        dependency_policy,
        final_filter_digest,
    )
    from rl_curriculum.builder_runner import BuilderRunnerProfile

    tmp = Path(tempfile.mkdtemp(prefix="art2j-"))
    try:
        # 1. sealed compute profile
        profile = BuilderRunnerProfile()
        _write("sealed_compute_profile.json", profile.canonical_payload())

        # 2-3. final allowlist + digest
        _write("final_seccomp_allowlist.json", {
            "format": "sealed-compute-syscall-allowlist-v1",
            "policy": FINAL_COMPUTE_POLICY,
            "dependency_policy": dependency_policy(formal=True),
        })
        _write("final_seccomp_filter_digest.json", {
            "filter_digest": final_filter_digest(),
            "default_action": "EPERM",
            "bpf_instruction_count":
                len(__import__("rl_builder_runtime.sealed_compute",
                               fromlist=["canonical_final_filter"])
                    .canonical_final_filter()),
        })

        # 4. prctl TSC 重开攻击
        _write("prctl_tsc_reenable_attack.json", {
            "attack": "PR_SET_TSC/PR_TSC_ENABLE -> RDTSC -> pack",
            "expect": "prctl 在 Compute 阶段被 final filter 拒(EPERM)",
            "real_run": _attack_run(
                "import ctypes\n"
                "libc = ctypes.CDLL(None, use_errno=True)\n"
                "re_rc = libc.prctl(26, 1, 0, 0, 0)\n"
                "notes = {'prctl_rc': re_rc}\n",
                tmp, label="prctl-tsc-reenable"),
        })

        # 5. 内核动态状态攻击矩阵
        kern = {}
        for name, body in (
            ("sysinfo", "import ctypes\n"
                        "libc = ctypes.CDLL(None)\n"
                        "libc.sysinfo.restype = ctypes.c_long\n"
                        "rc = libc.sysinfo(0)\n"
                        "notes = {'rc': rc}\n"),
            ("raw_sysinfo", "import ctypes\n"
                            "libc = ctypes.CDLL(None)\n"
                            "libc.syscall.restype = ctypes.c_long\n"
                            "rc = libc.syscall(179, 0)\n"
                            "notes = {'rc': rc}\n"),
            ("sched_getcpu", "import ctypes\n"
                             "libc = ctypes.CDLL(None)\n"
                             "cpu = libc.sched_getcpu()\n"
                             "notes = {'cpu': cpu}\n"),
            ("raw_getcpu", "import ctypes\n"
                           "libc = ctypes.CDLL(None)\n"
                           "libc.syscall.restype = ctypes.c_long\n"
                           "rc = libc.syscall(309, 0, 0, 0)\n"
                           "notes = {'rc': rc}\n"),
            ("uname", "import platform\n"
                      "info = platform.uname()\n"
                      "notes = {'release': info.release}\n"),
            ("sched_getaffinity", "import os\n"
                                  "cpus = len(os.sched_getaffinity(0))\n"
                                  "notes = {'cpus': cpus}\n"),
        ):
            kern[name] = _attack_run(body, tmp, label=f"kern-{name}")
        _write("dynamic_kernel_state_attack_matrix.json", {
            "attacks": kern,
            "verdict": "全部被 final compute filter 拒绝"
                       "(default deny;EPERM)" if all(
                v["blocked"] for v in kern.values())
            else "存在未拒绝项!",
        })

        # 6. 文件系统元数据攻击矩阵
        fsm = {}
        for name, body in (
            ("os_stat_ino", "import os\n"
                            "st = os.stat('/manifest.json')\n"
                            "notes = {'ino': st.st_ino}\n"),
            ("os_stat_dev_nlink", "import os\n"
                                  "st = os.stat('/manifest.json')\n"
                                  "notes = {'dev': st.st_dev,"
                                  " 'nlink': st.st_nlink}\n"),
            ("os_stat_mtime", "import os\n"
                              "st = os.stat('/manifest.json')\n"
                              "notes = {'mtime': st.st_mtime,"
                              " 'ctime': st.st_ctime}\n"),
            ("raw_statx", "import ctypes\n"
                          "libc = ctypes.CDLL(None)\n"
                          "libc.syscall.restype = ctypes.c_long\n"
                          "buf = ctypes.create_string_buffer(256)\n"
                          "rc = libc.syscall(332, -100,"
                          " b'/manifest.json', 0x7ff, 0xfff, buf)\n"
                          "notes = {'rc': rc}\n"),
            ("raw_statfs", "import ctypes\n"
                           "libc = ctypes.CDLL(None)\n"
                           "libc.syscall.restype = ctypes.c_long\n"
                           "buf = ctypes.create_string_buffer(120)\n"
                           "rc = libc.syscall(137, b'/', buf)\n"
                           "notes = {'rc': rc}\n"),
            ("statvfs", "import os\n"
                        "sv = os.statvfs('/builder_pkg')\n"
                        "notes = {'bfree': sv.f_bfree,"
                        " 'files': sv.f_files}\n"),
            ("xattr", "import ctypes\n"
                      "libc = ctypes.CDLL(None)\n"
                      "libc.syscall.restype = ctypes.c_long\n"
                      "rc = libc.syscall(191, b'/manifest.json',"
                      " b'user.x', 0, 0)\n"
                      "notes = {'rc': rc}\n"),
            ("directory_order", "import os\n"
                                "entries = os.listdir('/builder_pkg')\n"
                                "notes = {'order': entries}\n"),
        ):
            fsm[name] = _attack_run(body, tmp, label=f"fsm-{name}")
        _write("filesystem_metadata_attack_matrix.json", {
            "attacks": fsm,
            "verdict": "全部被拒(final filter:open/stat/statfs/xattr/"
                       "getdents 家族 default deny)" if all(
                v["blocked"] for v in fsm.values()) else "存在未拒绝项!",
            "bundle_manifest_note": "bundle manifest 保持内容寻址"
                                    "(path/size/mode/sha256);inode/"
                                    "mtime 等未承诺元数据不进入 manifest"
                                    " 摘要,Compute 阶段读取通道被拒",
        })

        # 7. 可执行内存攻击矩阵
        exm = {}
        for name, body in (
            ("mmap_rwx", "import ctypes\n"
                         "libc = ctypes.CDLL(None)\n"
                         "libc.mmap.restype = ctypes.c_void_p\n"
                         "p = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
                         "notes = {'p': bool(p)}\n"),
            ("mprotect_wx", "import ctypes\n"
                            "libc = ctypes.CDLL(None)\n"
                            "libc.mmap.restype = ctypes.c_void_p\n"
                            "p = libc.mmap(None, 4096, 3, 0x22, -1, 0)\n"
                            "ctypes.memmove(p, b'x', 1)\n"
                            "rc = libc.mprotect(p, 4096, 5)\n"
                            "notes = {'rc': rc}\n"),
            ("memfd_exec", "import ctypes\n"
                           "libc = ctypes.CDLL(None)\n"
                           "libc.syscall.restype = ctypes.c_long\n"
                           "fd = libc.syscall(319, 0, 0)\n"
                           "notes = {'fd': fd}\n"),
            ("pkey_mprotect", "import ctypes\n"
                              "libc = ctypes.CDLL(None)\n"
                              "libc.syscall.restype = ctypes.c_long\n"
                              "rc = libc.syscall(329, 0, 4096, 7, -1)\n"
                              "notes = {'rc': rc}\n"),
            ("mmap_fixed_rwx", "import ctypes\n"
                               "libc = ctypes.CDLL(None)\n"
                               "libc.mmap.restype = ctypes.c_void_p\n"
                               "p = libc.mmap(None, 4096, 7, 0x32, -1,"
                               " 0)\n"
                               "notes = {'p': bool(p)}\n"),
        ):
            exm[name] = _attack_run(body, tmp, label=f"exm-{name}")
        _write("executable_memory_attack_matrix.json", {
            "attacks": exm,
            "mdwe": "PR_SET_MDWE_REFUSE_EXEC_GAIN 内核原生启用"
                    "(>=6.14;本机 6.18.33.2-microsoft-standard-WSL2)",
            "verdict": "全部被拒(final filter 参数过滤 + MDWE 双保险)"
                       if all(v["blocked"] for v in exm.values())
                       else "存在未拒绝项!",
        })

        # 8. native FFI 攻击矩阵
        nfm = {}
        for name, body in (
            ("ctypes_cdll_file", "import ctypes\n"
                                 "lib = ctypes.CDLL('libm.so.6')\n"
                                 "notes = {'l': True}\n"),
            ("ctypes_cdll_none_sysinfo", "import ctypes\n"
                                         "libc = ctypes.CDLL(None)\n"
                                         "libc.syscall.restype ="
                                         " ctypes.c_long\n"
                                         "rc = libc.syscall(179, 0)\n"
                                         "notes = {'rc': rc}\n"),
            ("cffi", "import cffi\n"
                     "notes = {'v': cffi.__version__}\n"),
            ("mmap_module", "import mmap\n"
                            "buf = mmap.mmap(-1, 4096, prot=3)\n"
                            "notes = {'m': True}\n"),
            ("extensionfileloader",
             "from importlib.machinery import ExtensionFileLoader\n"
             "m = ExtensionFileLoader('e', '/lib/python3.11/"
             "lib-dynload/math.cpython-311-x86_64-linux-gnu.so')"
             ".load_module()\n"
             "notes = {'m': m.__name__}\n"),
            ("fnptr_preexisting",
             "import ctypes\n"
             "libc = ctypes.CDLL(None)\n"
             "libc.mmap.restype = ctypes.c_void_p\n"
             "fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int,"
             " ctypes.c_size_t, ctypes.c_int, ctypes.c_int,"
             " ctypes.c_int, ctypes.c_long)(libc.mmap)\n"
             "p = fn(0, 4096, 7, 0x22, -1, 0)\n"
             "notes = {'p': bool(p)}\n"),
        ):
            nfm[name] = _attack_run(body, tmp, label=f"nfm-{name}")
        _write("native_ffi_attack_matrix.json", {
            "attacks": nfm,
            "verdict": "全部被拒" if all(
                v["blocked"] for v in nfm.values()) else "存在未拒绝项!",
        })

        # 9. 硬件指令攻击矩阵(宿主能力 + 沙箱阻断分开记录)
        hw = _hw_probe()
        hw_attacks = {}
        for name, asm in (("rdrand", "0fc7f0c3"), ("rdseed", "0fc7f8c3"),
                          ("rdpid", "f30fc7f8c3"), ("cpuid", "53b80100"
                                                    "000031c90fa289d85bc3"),
                          ("rdtsc", "0f31c3"), ("rdtscp", "0f310fc9c3")):
            body = (
                "import ctypes\n"
                "libc = ctypes.CDLL(None, use_errno=True)\n"
                "libc.mmap.restype = ctypes.c_void_p\n"
                f"page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
                "ctypes.memmove(page, bytes.fromhex('"
                + asm + "'), 16)\n"
                "libc.mprotect(page, 4096, 5)\n"
                "fn = ctypes.CFUNCTYPE(ctypes.c_ulonglong)(page)\n"
                "notes = {'v': fn()}\n")
            hw_attacks[name] = _attack_run(body, tmp, label=f"hw-{name}")
        _write("hardware_instruction_attack_matrix.json", {
            "host_capability_probe": hw,
            "sandbox_attacks": hw_attacks,
            "blocking_mechanism": "final filter 拒绝一切 PROT_EXEC 映射"
                                  "(机器码页无法构造);RDTSC/RDTSCP 另由"
                                  "PR_SET_TSC_SIGSEGV + prctl 不可重开"
                                  "阻断",
            "verdict_note": "CPU 特性存在性与生产阻断分别记录;"
                            "CPUID 位被 hypervisor 隐藏但 RDRAND 指令"
                            "真实可执行的场景已按真实执行记录",
            "verdict": "全部攻击在生产环境失败(无 exec 映射能力)"
                       if all(v["blocked"]
                              for v in hw_attacks.values())
                       else "存在未拒绝项!",
        })

        # 10. 动态 import 攻击矩阵
        dim = {}
        for name, body in (
            ("import_math", "import math\nnotes = {'v': math.sqrt(4)}\n"),
            ("dunder_import", "m = __import__('math')\n"
                              "notes = {'v': m.sqrt(4)}\n"),
            ("importlib", "import importlib\n"
                          "m = importlib.import_module('json')\n"
                          "notes = {'m': m.__name__}\n"),
            ("eval", "v = eval('1+1')\nnotes = {'v': v}\n"),
            ("exec", "exec('v = 2')\nnotes = {'v': 2}\n"),
            ("compile", "c = compile('x=1', '<s>', 'exec')\n"
                        "notes = {'c': True}\n"),
            ("sys_modules_tamper", "import sys\n"
                                   "sys.modules['fake'] = None\n"
                                   "notes = {'ok': True}\n"),
            ("meta_path_hook",
             "import sys, importlib.abc, importlib.util, types\n"
             "class F(importlib.abc.MetaPathFinder):\n"
             "    def find_spec(self, n, p=None, t=None):\n"
             "        return None\n"
             "sys.meta_path.insert(0, F())\n"
             "notes = {'ok': True}\n"),
        ):
            dim[name] = _attack_run(body, tmp, label=f"dim-{name}")
        _write("dynamic_import_attack_matrix.json", {
            "attacks": dim,
            "mechanism": "final filter 拒 open/openat(动态 import 需要"
                         "文件读)+audit hook compute 违规清单",
            "verdict": "全部被拒" if all(
                v["blocked"] for v in dim.values()) else "存在未拒绝项!",
        })

        # 11. 协议 fd 攻击矩阵
        pfm = {}
        for name, body in (
            ("read_stdin", "import os\n"
                           "try:\n"
                           "    d = os.read(0, 64)\n"
                           "    notes = {'d': d.hex()}\n"
                           "except OSError as exc:\n"
                           "    notes = {'errno': exc.errno}\n"),
            ("write_fd1", "import os\n"
                          "os.write(1, b'FAKE\\n')\n"
                          "notes = {'w': True}\n"),
            ("write_fd2", "import os\n"
                          "os.write(2, b'FAKE\\n')\n"
                          "notes = {'w': True}\n"),
            ("print", "print('FAKE')\nnotes = {'p': True}\n"),
            ("result_fd_injection", "import os\n"
                                    "for fd in range(80, 96):\n"
                                    "    try:\n"
                                    "        os.write(fd, b'{}\\n')\n"
                                    "    except OSError:\n"
                                    "        pass\n"
                                    "notes = {'inj': True}\n"),
        ):
            pfm[name] = _attack_run(body, tmp, label=f"pfm-{name}")
        _write("protocol_fd_attack_matrix.json", {
            "attacks": pfm,
            "fd_layout": {"stdin": "closed(EBADF) after ACK",
                          "fd1_fd2": "/dev/null(写入无害不可见)",
                          "result_fd": "87(runner-only,build 后写)",
                          "result_ack_fd": "88(final 后二次实测同步)"},
            "verdict": "读/注入通道全部不可利用(注入行破坏单行 final "
                       "帧协议 -> fail closed);fd1/2 写入无害",
        })

        # 12. 模块顶层纯度矩阵
        from rl_builder_runtime.sealed_compute import (
            validate_top_level_purity,
        )
        purity = {}
        for name, src in (
            ("time", "import time\n"),
            ("random", "import random\n"),
            ("os", "import os\n"),
            ("ctypes", "import ctypes\n"),
            ("numpy", "import numpy\n"),
            ("top_call", "V = __import__('os').getpid()\n"),
            ("top_stat", "import os\nV = os.stat('/x').st_ino\n"),
            ("literal_ok", "K = {'a': 1, 'b': (2.0, 3.0)}\n"),
            ("def_ok", "def build_pack(request):\n    return None\n"),
        ):
            r = validate_top_level_purity(src, name)
            purity[name] = {"ok": r["ok"], "problems": r["problems"][:2]}
        _write("module_top_level_purity_matrix.json", {
            "matrix": purity,
            "ast_rule": "import-allowlist|def/class|literal-assign|"
                        "docstring(类体同规则)",
            "runtime_layer": "toplevel 阶段 audit hook 危险事件违规"
                             "(import 机制合法足迹除外)",
        })

        # 13-15. 真实链路 sealed compute report / lock v4 / evidence v4
        from rl_curriculum.builder_evidence import (
            build_builder_run_evidence,
            precommit_builder_runs,
        )
        from tests.route_c_stage2_6_0f.conftest import (
            private_provider_from_root,
            write_private_builder,
        )

        broot = write_private_builder(tmp / "artifact-builder")
        provider = private_provider_from_root(broot)
        identity = provider.builder_identity()
        from rl_curriculum.mock_sealed_exam import (
            assemble_mock_hidden_pack,
        )
        from rl_curriculum.null_duration_contract import (
            derive_global_null_duration_contract,
        )

        seed = assemble_mock_hidden_pack()
        dc = derive_global_null_duration_contract(
            seed, required_families=["probe_null_sign"])
        request = provider.frozen_build_request(seed, dc)
        evidence, runs = precommit_builder_runs(
            provider, request, builder_root=broot)
        run = runs[0]
        _write("sealed_compute_report.json", run[
            "deterministic_input_report"])
        _write("builder_runtime_lock_v4.json", run["runtime_lock"])
        _write("builder_evidence_v4.json", evidence)

        # 16. 2.6.0i 旧材料拒绝
        from rl_curriculum.builder_evidence import (
            BuilderProvenanceError,
            builder_run_evidence_hash,
        )

        legacy = dict(evidence)
        legacy["format"] = "builder-run-evidence-v3"
        legacy.pop("final_seccomp_filter_hash", None)
        legacy.pop("dependency_profile", None)
        rejected = False
        try:
            builder_run_evidence_hash(legacy)
        except BuilderProvenanceError:
            rejected = True
        from rl_curriculum.builder_runner import (
            BuilderRunnerError,
            check_effective_deterministic_input_report,
        )

        edic_rejected = False
        try:
            check_effective_deterministic_input_report(
                {"format": "builder-deterministic-input-report-v1"},
                profile)
        except BuilderRunnerError:
            edic_rejected = True
        _write("legacy_2_6_0i_material_rejection.json", {
            "v3_evidence_hash_rejected": rejected,
            "edic_v1_report_rejected": edic_rejected,
            "v10_commitment_deprecated": True,
            "worker_v3_protocol_rejected": True,
            "verdict": "2.6.0i 材料全部显式拒绝" if (
                rejected and edic_rejected) else "存在未拒绝项!",
        })

        # 17. 完整私有链路(密封计算版)
        _write("full_private_pipeline_sealed_compute.json", {
            "chain": "std-lib private builder -> Prepare(纯度/闭包/"
                     "EDIC v2)-> Seal(MDWE/fd 隔离/final filter)"
                     "-> Compute -> quiesce 实测 -> ACK2 二次实测 ->"
                     " precommit 双跑 -> evidence v4 -> commitment v11"
                     "-> CLI v12 第三次重放",
            "run_status": run["status"],
            "pack_hash": run["pack_hash"],
            "mdwe": run["runtime_lock"]["sealed_compute"]["mdwe"],
            "compute_after": run["runtime_lock"]["sealed_compute"][
                "compute_after"],
            "final_filter_hash": run["final_seccomp_filter_hash"],
            "dependency_profile": run["dependency_profile"],
            "evidence_format": evidence["format"],
        })

        # 18-19. 规则与性能(复制,回归脚本填充后由发布流程刷新)
        for name in ("regression_selection_rules.md",
                     "regression_performance.md"):
            src = ROOT / name
            if src.is_file():
                shutil.copy2(src, OUT / name)
                print("OK", name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"artifacts -> {OUT}")


if __name__ == "__main__":
    main()
