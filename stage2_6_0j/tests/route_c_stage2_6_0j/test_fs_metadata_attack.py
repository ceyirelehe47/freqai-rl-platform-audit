"""工作包 D/G3:文件系统动态状态与元数据攻击矩阵。

Compute 阶段的 stat/statx/statfs/statvfs/xattr/inode/设备号/链接数/
时间戳/目录序全部被 final filter 拒绝,不得影响 pack;模块顶层的
元数据访问在资格阶段被 AST 纯度验证拒绝。
"""

from __future__ import annotations


def test_os_stat_metadata_attack(run_attack2j):
    """G3:os.stat('/manifest.json').st_ino/st_dev/st_nlink 注入。"""
    body = (
        "import os\n"
        "st = os.stat('/manifest.json')\n"
        "notes = {'ino': st.st_ino, 'dev': st.st_dev,\n"
        "         'nlink': st.st_nlink, 'mtime': st.st_mtime}\n"
    )
    outcome = run_attack2j(body, label="stat-ino")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_raw_statx_attack(run_attack2j):
    """G3:raw statx syscall(nr 332)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "buf = ctypes.create_string_buffer(256)\n"
        "rc = libc.syscall(ctypes.c_long(332), ctypes.c_long(-100),\n"
        "                  b'/manifest.json', ctypes.c_long(0x7ff),\n"
        "                  ctypes.c_long(0x0fff), buf)\n"
        "notes = {'statx_rc': rc}\n"
    )
    outcome = run_attack2j(body, label="statx")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_statfs_statvfs_attack(run_attack2j):
    """G3:statfs(137)/fstatfs(138) raw + os.statvfs 剩余块数。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "buf = ctypes.create_string_buffer(120)\n"
        "rc1 = libc.syscall(ctypes.c_long(137), b'/', buf)\n"
        "bfree = int.from_bytes(buf[16:24], 'little')\n"
        "notes = {'statfs_rc': rc1, 'f_bfree': bfree}\n"
    )
    outcome = run_attack2j(body, label="statfs")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_xattr_attack(run_attack2j):
    """G3:getxattr(191)/listxattr(raw syscall 路径)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "rc = libc.syscall(ctypes.c_long(191), b'/manifest.json',\n"
        "                  b'user.x', ctypes.c_void_p(0),\n"
        "                  ctypes.c_long(0))\n"
        "notes = {'getxattr_rc': rc}\n"
    )
    outcome = run_attack2j(body, label="xattr")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_directory_order_attack(run_attack2j):
    """G3:os.listdir('/builder_pkg') 目录项顺序注入。"""
    body = (
        "import os\n"
        "entries = os.listdir('/builder_pkg')\n"
        "notes = {'dir_order': entries}\n"
    )
    outcome = run_attack2j(body, label="dir-order")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_scratch_read_attack(run_attack2j):
    """D1:Compute 阶段读任何文件(open 被 final filter 拒)。"""
    body = (
        "data = open('/manifest.json', 'rb').read(64)\n"
        "notes = {'manifest_head': str(data[:16])}\n"
    )
    outcome = run_attack2j(body, label="scratch-read")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_open_scratch_write_then_read_attack(run_attack2j):
    """D1 变体:写 scratch 再读回(Compute 内 open 双向全拒)。"""
    body = (
        "with open('/scratch/leak.txt', 'w') as fh:\n"
        "    fh.write('x')\n"
        "val = open('/scratch/leak.txt').read()\n"
        "notes = {'roundtrip': val}\n"
    )
    outcome = run_attack2j(body, label="scratch-roundtrip")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_module_top_level_metadata_rejected(run_attack2j):
    """G8/D3:模块顶层 os.stat——资格阶段(纯度验证)拒绝。

    write_attack_builder 把 body 放在 build_pack 体内;本测试构造
    顶层语句攻击(直接写独立 builder 文件)。
    """
    import json as _json

    from tests.route_c_stage2_6_0i.conftest import write_attack_builder

    # run_attack2j 的 label 目录复用:直接手工构造顶层攻击包
    import tempfile

    root_dir = tempfile.mkdtemp(prefix="toplevel-stat-")
    from pathlib import Path

    root = Path(root_dir)
    src = (
        "'''顶层元数据攻击 builder。'''\n"
        "import os\n"
        "TOP_INO = os.stat('/manifest.json').st_ino\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    pack = {\n"
        "        'schema': 'exam-pack-v1', 'name': request['pack_name'],\n"
        "        'version': request['pack_version'], 'visibility':\n"
        "        'mock_hidden', 'charter_hash': '', 'spec_versions': {},\n"
        "        'timeframe': request['timeframe'],\n"
        "        'episodes': [{'family': 'probe_null_sign',\n"
        "                      'params': {'episode_bars': 96}, 'seed': 1,\n"
        "                      'split': 'null_control',\n"
        "                      'timeframe': request['timeframe']}],\n"
        "        'notes': {'ino': TOP_INO},\n"
        "    }\n"
        "    log = {'format': 'builder-attempt-log-v2',\n"
        "           'max_attempts': 1, 'attempts': [\n"
        "               {'attempt': 0, 'verdict': 'accept',\n"
        "                'reject_reasons': []}],\n"
        "           'selected_attempt': 0}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': log, 'error': None}\n"
    )
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    (root / "provider_config.json").write_text(_json.dumps({
        "entrypoint_module": "builder_attack",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"], "pair_count_per_family": 2,
        "max_attempts": 1, "root_label": "toplevel-stat",
    }), encoding="utf-8")

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

    provider = private_provider_from_root(root)
    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        pack=seed, required_families=["probe_null_sign"])
    try:
        run = run_isolated_builder_run(
            provider.builder_identity(),
            provider.frozen_build_request(seed, dc),
            builder_root=root, profile=BuilderRunnerProfile())
    except Exception as exc:  # noqa: BLE001
        assert "顶层纯度" in str(exc) or "os" in str(exc), str(exc)
        return
    raise AssertionError(f"顶层 os.stat 攻击未被拒绝: {run['pack_hash']}")
