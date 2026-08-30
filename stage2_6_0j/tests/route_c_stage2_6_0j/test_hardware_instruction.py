"""工作包 E1/G4:硬件原生指令攻击矩阵(RDRAND/RDSEED/RDPID/CPUID/
RDTSC/RDTSCP)。

判定合同(任务书 E1):必须区分
- CPU 不支持(指令真实执行 #UD);
- 内核/虚拟机未暴露(CPUID 位缺失但指令可用——本环境实测存在);
- 生产机制阻断(沙箱内攻击失败);
- 攻击真实执行成功(不得发生)。

每条指令:宿主侧真实执行记录能力;沙箱内攻击必须因无 exec 映射
能力(final filter PROT_EXEC 拒绝)而失败。
"""

from __future__ import annotations

import pytest

from rl_builder_runtime.sealed_compute import validate_top_level_purity


def test_hw_probe_records_real_capability(hw_probe):
    """宿主侧真实执行记录(artifact 依据;不伪装成生产阻断)。"""
    assert set(hw_probe) == {"cpuid", "rdtsc", "rdtscp", "rdrand",
                             "rdseed", "rdpid"}
    # RDTSC/RDTSCP/CPUID 在 x86_64 必然可用
    assert hw_probe["cpuid"]["available"] is True
    assert hw_probe["rdtsc"]["available"] is True
    # RDRAND 的 CPUID 位在本 WSL 被 hypervisor 隐藏但指令真实可执行
    # ——hw_probe 记录真实执行结果,不依赖 CPUID 位


def _rdrand_body():
    return (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "if not page:\n"
        "    notes = {'rdrand': 'mmap-denied'}\n"
        "else:\n"
        "    ctypes.memmove(page, b'\\x0f\\xc7\\xf0\\xc3', 4)\n"
        "    libc.mprotect(page, 4096, 5)\n"
        "    fn = ctypes.CFUNCTYPE(ctypes.c_int)(page)\n"
        "    notes = {'rdrand': fn()}\n"
    )


def test_rdrand_attack_blocked(run_attack2j):
    """G4:RDRAND 机器码执行(经 RWX/mprotect RX 路径)必须被拒。"""
    outcome = run_attack2j(_rdrand_body(), label="rdrand")
    assert not isinstance(outcome, dict), "RDRAND 进入 pack"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_rdseed_attack_blocked(run_attack2j):
    """G4:RDSEED(0F C7 /8)机器码执行。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "ctypes.memmove(page, b'\\x0f\\xc7\\xf8\\xc3', 4)\n"
        "libc.mprotect(page, 4096, 5)\n"
        "fn = ctypes.CFUNCTYPE(ctypes.c_int)(page)\n"
        "notes = {'rdseed': fn()}\n"
    )
    outcome = run_attack2j(body, label="rdseed")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_cpuid_attack_blocked(run_attack2j):
    """G4:CPUID 指令(普通指令,仅能经机器码页执行)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "ctypes.memmove(page, bytes.fromhex('53b8000000'\n"
        "                    '0031c90fa289d85bc3'), 14)\n"
        "libc.mprotect(page, 4096, 5)\n"
        "fn = ctypes.CFUNCTYPE(ctypes.c_uint)(page)\n"
        "notes = {'cpuid_eax0': fn()}\n"
    )
    outcome = run_attack2j(body, label="cpuid")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_rdpid_attack_blocked(run_attack2j):
    """G4:RDPID(若 CPU 不支持则记录;攻击路径仍必须被 exec-memory
    边界拒绝,与 CPU 支持无关)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "ctypes.memmove(page, bytes.fromhex('f30fc7f8c3'), 5)\n"
        "libc.mprotect(page, 4096, 5)\n"
        "fn = ctypes.CFUNCTYPE(ctypes.c_ulonglong)(page)\n"
        "notes = {'rdpid': fn()}\n"
    )
    outcome = run_attack2j(body, label="rdpid")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_rdtscp_attack_blocked(run_attack2j):
    """G4:RDTSCP(PR_SET_TSC_SIGSEGV + 无法 prctl 重开)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "ctypes.memmove(page, bytes.fromhex('0f310fc9c3'), 5)\n"
        "libc.mprotect(page, 4096, 5)\n"
        "fn = ctypes.CFUNCTYPE(ctypes.c_ulonglong)(page)\n"
        "notes = {'rdtscp': fn()}\n"
    )
    outcome = run_attack2j(body, label="rdtscp")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_capability_matrix_documented(hw_probe, tmp_path):
    """E1:能力矩阵 artifact(进入 stage 报告的原始数据)。"""
    import json

    matrix = {
        "probe_environment": "host-no-sandbox (real execution)",
        "instructions": hw_probe,
        "verdict_rule": "CPU 不支持 != 生产阻断;沙箱内攻击由"
                        "final filter PROT_EXEC 拒绝与 TSC SIGSEGV 阻断",
    }
    out = tmp_path / "hardware_instruction_attack_matrix.json"
    out.write_text(json.dumps(matrix, ensure_ascii=False, indent=1,
                              sort_keys=True), encoding="utf-8")
    assert out.is_file()
    # RDRAND/RDSEED 必须被真实测试(不得缺失)
    for name in ("rdrand", "rdseed", "rdpid", "cpuid", "rdtsc",
                 "rdtscp"):
        assert name in matrix["instructions"]
        assert "available" in matrix["instructions"][name]


def test_purity_ast_rejects_ctypes_top_level():
    """G8:顶层 ctypes/os/numpy 源码被 AST 验证拒绝;顶层调用(含
    time.time)被字面量规则拒绝(random/time/threading 在 allowlist:
    冻结时钟/受承诺播种/线程创建被 syscall 拒,均无未承诺输入)。"""
    for src in (
        "import ctypes\n",
        "import os\n",
        "import numpy\n",
        "V = time.time()\n",
        "import time\nT = time.time()\n",
    ):
        r = validate_top_level_purity(src, "m")
        assert not r["ok"], src
    # allowlist 模块顶层 import 合法,顶层调用仍被字面量规则拒
    for src in ("import time\n", "import random\n",
                "import threading\n"):
        r = validate_top_level_purity(src, "m")
        assert r["ok"], (src, r["problems"])
