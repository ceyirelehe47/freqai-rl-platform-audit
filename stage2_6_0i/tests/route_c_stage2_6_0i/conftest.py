"""阶段 2.6.0i 测试夹具:Builder 密闭确定性输入与 seccomp 边界。

自包含(不 import 0h conftest,避免跨目录耦合):
- write_attack_builder / attack_request:真实生产路径攻击 builder 与
  冻结请求(与 0h 构造器同构);
- formal_profile / run_attack:正式密闭沙箱单次攻击运行;
- mini_env:微型 conda 布局 env(bundle 语义测试的快速载体)。
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TESTS = Path(__file__).resolve().parents[1]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from tests.route_c_stage2_6_0f.conftest import (  # noqa: E402
    private_provider_from_root,
)

FAMS = ("probe_null_sign",)

PACK_TMPL = """    pack = {{
        'schema': 'exam-pack-v1',
        'name': request['pack_name'],
        'version': request['pack_version'],
        'visibility': 'mock_hidden',
        'charter_hash': '',
        'spec_versions': {{}},
        'timeframe': request['timeframe'],
        'episodes': [
            {{'family': 'probe_null_sign',
             'params': {{'episode_bars': 96}}, 'seed': 1,
             'split': 'null_control',
             'timeframe': request['timeframe']}}],
        'notes': {notes},
    }}
"""


def _result_tail(max_attempts=2, accepts=1):
    if max_attempts == 1:
        accepts = 0  # 单 attempt 场景:直接 accept(拒绝前置条目为空)
    attempts = []
    for i in range(accepts):
        attempts.append("{'attempt': %d, 'verdict': 'reject', "
                        "'reject_reasons': ['p%d']}" % (i, i))
    attempts.append("{'attempt': %d, 'verdict': 'accept', "
                    "'reject_reasons': []}" % accepts)
    body = ", ".join(attempts)
    return (
        "    log = {'format': 'builder-attempt-log-v2',\n"
        "           'max_attempts': %d,\n"
        "           'attempts': [%s],\n"
        "           'selected_attempt': %d}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': log, 'error': None}\n"
        % (max_attempts, body, accepts))


def write_attack_builder(root: Path, body: str, *, max_attempts: int = 2,
                         extra_files: dict | None = None,
                         external_dependencies: list | None = None,
                         label: str = "attack-builder-0i",
                         notes: str = "{}") -> Path:
    """写入攻击 builder root(body 是 build_pack 函数体的语句序列)。"""
    root.mkdir(parents=True, exist_ok=True)
    src = (
        "'''2.6.0i 攻击 builder(测试专用)。'''\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        f"{body}"
        f"{PACK_TMPL.format(notes=notes)}"
        f"{_result_tail(max_attempts=max_attempts)}"
    )
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    cfg = {
        "entrypoint_module": "builder_attack",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": max_attempts,
        "root_label": label,
    }
    if external_dependencies is not None:
        cfg["external_dependencies"] = external_dependencies
    (root / "provider_config.json").write_text(
        json.dumps(cfg), encoding="utf-8")
    for name, content in (extra_files or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return root


def attack_request(provider, pack, duration_contract):
    """从攻击 provider 派生 v3 冻结请求。"""
    return provider.frozen_build_request(pack, duration_contract)


@pytest.fixture()
def formal_profile():
    from rl_curriculum.builder_runner import BuilderRunnerProfile

    return BuilderRunnerProfile()


@pytest.fixture(scope="session")
def seed_pack_and_dc():
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        pack=seed, required_families=list(FAMS))
    return seed, dc


@pytest.fixture()
def run_attack(tmp_path, seed_pack_and_dc):
    """真实生产路径单次攻击运行。

    _run(body, external_dependencies=[...], profile=None, ...) ->
    成功返回 run record dict;失败返回 ("异常类型名", "消息")。
    """
    seed, dc = seed_pack_and_dc
    from rl_curriculum.builder_runner import run_isolated_builder_run

    def _run(body: str, *, external_dependencies=None, profile=None,
             max_attempts: int = 1, label: str = "attack-0i",
             extra_files: dict | None = None,
             bundle_pool=None):
        root = write_attack_builder(
            tmp_path / label, body, max_attempts=max_attempts,
            external_dependencies=external_dependencies
            if external_dependencies is not None else [],
            label=label, extra_files=extra_files)
        provider = private_provider_from_root(root)
        identity = provider.builder_identity()
        request = provider.frozen_build_request(seed, dc)
        try:
            return run_isolated_builder_run(
                identity, request, builder_root=root,
                profile=profile
                or __import__("rl_curriculum.builder_runner",
                              fromlist=["BuilderRunnerProfile"])
                .BuilderRunnerProfile(),
                bundle_pool=bundle_pool)
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__, str(exc)

    return _run


def make_mini_env(base: Path) -> Path:
    """微型 conda 布局 env(bundle 组装语义的快速载体;测试直用)。

    含:bin/python3.11(真实解释器副本)+ libpython、lib/python3.11/
    {os.py, site-packages 两个假 distribution 共享 namespace 包 nsp}。
    """
    import os

    env = base / "mini_env"
    (env / "bin").mkdir(parents=True)
    (env / "lib" / "python3.11" / "site-packages").mkdir(parents=True)
    shutil.copy2(sys.executable, env / "bin" / "python3.11")
    os.chmod(env / "bin" / "python3.11", 0o755)
    # conda python 经 rpath $ORIGIN/../lib 找 libpython:复制使其可启动
    libpython = Path(sys.executable).parent.parent / "lib" / \
        "libpython3.11.so.1.0"
    if libpython.is_file():
        shutil.copy2(libpython, env / "lib" / "libpython3.11.so.1.0")
    (env / "lib" / "python3.11" / "os.py").write_text("x = 1\n")
    sp = env / "lib" / "python3.11" / "site-packages"
    for dist, version, mod_file, content in (
            ("nspkg_a", "1.0", "nsp/a_impl.py", "VALUE = 'a'\n"),
            ("nspkg_b", "2.0", "nsp/b_impl.py", "VALUE = 'b'\n")):
        di = sp / f"{dist}.dist-info"
        di.mkdir()
        mod = sp / mod_file
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text(content)
        digest = hashlib.sha256(content.encode()).digest()
        b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        rel = mod.relative_to(sp).as_posix()
        (di / "RECORD").write_text(
            f"{rel},sha256={b64},{len(content)}\n"
            f"{dist}.dist-info/METADATA,,\n"
            f"{dist}.dist-info/RECORD,,\n")
        (di / "METADATA").write_text(
            f"Name: {dist}\nVersion: {version}\n")
    return env


@pytest.fixture()
def mini_env(tmp_path):
    return make_mini_env(tmp_path)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "stage2_6_0i: 阶段 2.6.0i 密闭输入闭包测试")


@pytest.fixture(scope="session")
def schema():
    from rl_curriculum.probe_charter import probe_observation_schema

    return probe_observation_schema()


@pytest.fixture(scope="session")
def cfg():
    from rl_curriculum.mock_sealed_exam import default_eval_config

    return default_eval_config()


@pytest.fixture(scope="session")
def null_qual_chain(schema, cfg):
    sys.path.insert(0, str(TESTS))
    from null_qual_cache import cached_null_qual_chain

    return cached_null_qual_chain(schema, cfg)
