"""工作包 E1:考试条件不可命令行改写(密封 EvalConfig)。
阶段 2.6.0b 更新:--no-subprocess 已删除(CLI v3 源码级断言其不存在);
参数级拒绝断言不再携带该旗标,正式候选一律系统级沙箱执行。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rl_curriculum.hidden_exam_cli import main as exam_main
from tests.route_c_stage2_6_0a.conftest import run_cli

PROJ_ROOT = Path(__file__).resolve().parents[2]


def test_fee_override_rejected(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    rc = exam_main([
        "--sealed-manifest", str(tmp / "commitment.json"),
        "--pack", str(tmp / "pack.json"),
        "--checkpoint", str(sealed_exam_env["checkpoint"]),
        "--context", str(tmp / "ctx.json"),
        "--out", str(tmp / "out.json"),
        "--builder-provider", "mock",
        "--fee", "0.0001",
    ])
    assert rc == 2  # 参数级拒绝
    assert not (tmp / "out.json").exists()


def test_slippage_and_window_overrides_rejected(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    for extra in (["--slippage", "5.0"],
                  ["--window-size", "4"],
                  ["--initial-cash", "1000.0"]):
        rc = exam_main([
            "--sealed-manifest", str(tmp / "commitment.json"),
            "--pack", str(tmp / "pack.json"),
            "--checkpoint", str(sealed_exam_env["checkpoint"]),
            "--context", str(tmp / "ctx.json"),
            "--out", str(tmp / "out.json"),
            "--builder-provider", "mock",
            *extra,
        ])
        assert rc == 2, extra


def test_sealed_manifest_required(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    rc = exam_main([
        "--pack", str(tmp / "pack.json"),
        "--checkpoint", str(sealed_exam_env["checkpoint"]),
        "--context", str(tmp / "ctx.json"),
        "--out", str(tmp / "out.json"),
        "--builder-provider", "mock",
    ])
    assert rc == 2


def test_no_force_continue_flag_exists():
    """不存在'忽略哈希/强制继续'参数;--no-subprocess 已删除(C1)。"""
    import inspect
    import re

    import pytest

    import rl_curriculum.hidden_exam_cli as cli

    src = inspect.getsource(cli.main)
    defined = set(re.findall(r"add_argument\(\s*[\"']([^\"']+)", src))
    for forbidden in ("--ignore-hash", "--force", "--skip-verify",
                      "--no-verify", "--no-subprocess"):
        assert forbidden not in defined
    # argparse 对已删除旗标直接报未识别(SystemExit=2)
    with pytest.raises(SystemExit):
        cli.main(["--pack", "x", "--out", "y", "--no-subprocess"])
        "--builder-provider", "mock",


def test_cli_help_shows_sealed_contract():
    out = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli", "--help"],
        capture_output=True, text=True, cwd=str(PROJ_ROOT / "src"),
        timeout=60)
    text = out.stdout + out.stderr
    assert "--sealed-manifest" in text
    assert "--checkpoint" in text
