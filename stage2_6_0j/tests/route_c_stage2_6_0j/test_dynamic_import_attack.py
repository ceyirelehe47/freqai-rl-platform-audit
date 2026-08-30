"""工作包 A2/G6:Compute 阶段动态 import 与代码生成攻击矩阵。

build_pack 运行期间的 import/importlib/exec/eval/compile/marshal/
pickle/sys.modules 篡改/meta_path 注入/zip 加载全部被拒:
- 机制层:final filter 拒 open/openat(动态 import 需要文件读);
- 语义层:audit hook 的 compute 违规清单(import/compile/exec 事件)
  在结果采信前拒绝。
"""

from __future__ import annotations


def test_import_inside_build_pack_rejected(run_attack2j):
    """G6:build_pack 内 import(allowlist 内模块也一样——零 import)。"""
    outcome = run_attack2j(
        "    import math\n"
        "    v = math.sqrt(4.0)\n"
        "    notes = {'v': v}\n",
        label="import-math")
    assert not isinstance(outcome, dict), "Compute 内 import 未被拒绝"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_dunder_import_rejected(run_attack2j):
    """G6:__import__('math')(已加载模块命中 sys.modules)——事件层
    违规拒绝(允许缓存命中 import 等于允许 sys 等危险模块)。"""
    outcome = run_attack2j(
        "    m = __import__('math')\n"
        "    notes = {'v': m.sqrt(4.0)}\n",
        label="dunder-import")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_importlib_rejected(run_attack2j):
    """G6:importlib.import_module(未预加载模块触发真实 find/load,
    openat 被 final filter 拒)。"""
    outcome = run_attack2j(
        "    import importlib\n"
        "    m = importlib.import_module('colorsys')\n"
        "    notes = {'m': m.__name__}\n",
        label="importlib")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_importlib_reload_rejected(run_attack2j):
    """G6:importlib.reload 重新执行已加载模块顶层。"""
    outcome = run_attack2j(
        "    import importlib, sys\n"
        "    importlib.reload(sys.modules['json'])\n"
        "    notes = {'reloaded': True}\n",
        label="importlib-reload")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_eval_exec_compile_rejected(run_attack2j):
    """G6:eval/exec/compile 动态代码生成。"""
    for label, stmt in (
        ("eval", "    v = eval('1 + 1')\n"),
        ("exec", "    exec('v = 2')\n"),
        ("compile", "    c = compile('x = 1', '<s>', 'exec')\n"),
    ):
        outcome = run_attack2j(stmt, label=f"codegen-{label}")
        assert not isinstance(outcome, dict), f"{label} 未被拒绝"
        assert outcome[0] in ("BuilderRunnerError",
                              "BuilderProvenanceError")


def test_marshal_code_object_rejected(run_attack2j):
    """G6:marshal 加载可执行 code object(字节常量内嵌)。"""
    import marshal

    code = compile("VALUE = 41 + 1", "<attack>", "exec")
    blob = marshal.dumps(code).hex()
    outcome = run_attack2j(
        f"    import marshal\n"
        f"    code = marshal.loads(bytes.fromhex('{blob}'))\n"
        f"    ns = {{}}\n"
        f"    exec(code, ns)\n"
        f"    notes = {{'v': ns['VALUE']}}\n",
        label="marshal-code")
    assert not isinstance(outcome, dict), "marshal code 未被拒绝"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_pickle_callable_rejected(run_attack2j):
    """G6:pickle 载入可执行对象(pickle 模块不在 allowlist,Compute
    内 import 即被 final filter 的 openat 拒绝;载入路径不可达)。"""
    outcome = run_attack2j(
        "    import pickle\n"
        "    fn = pickle.loads(pickle.dumps(print))\n"
        "    notes = {'v': str(fn)}\n",
        label="pickle-callable")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_sys_modules_tamper_rejected(run_attack2j):
    """G6:修改 sys.modules(注入/删除模块)。"""
    outcome = run_attack2j(
        "    import sys\n"
        "    sys.modules['fake_mod'] = None\n"
        "    notes = {'injected': 'fake_mod' in sys.modules}\n",
        label="sysmodules-tamper")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_meta_path_hook_rejected(run_attack2j):
    """G6:修改 sys.meta_path(注入 import finder)。"""
    outcome = run_attack2j(
        "    import sys, importlib.abc, importlib.util, types\n"
        "    class EvilFinder(importlib.abc.MetaPathFinder):\n"
        "        def find_spec(self, fullname, path=None, target=None):\n"
        "            if fullname == 'evil_mod':\n"
        "                return importlib.util.spec_from_loader(\n"
        "                    fullname, EvilLoader())\n"
        "    class EvilLoader(importlib.abc.Loader):\n"
        "        def create_module(self, spec):\n"
        "            m = types.ModuleType(spec.name)\n"
        "            m.X = 1\n"
        "            return m\n"
        "        def exec_module(self, module):\n"
        "            pass\n"
        "    sys.meta_path.insert(0, EvilFinder())\n"
        "    import evil_mod\n"
        "    notes = {'x': evil_mod.X}\n",
        label="metapath-hook")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_zipimport_rejected(run_attack2j, tmp_path):
    """G6:zipimport(Prepare 期 zip 在 Compute 内加载)。"""
    outcome = run_attack2j(
        "    import sys, zipimport\n"
        "    sys.path.insert(0, '/builder_pkg/lib.zip')\n"
        "    mod = zipimport.zipimporter('/builder_pkg/lib.zip')\n"
        "    m = mod.load_module('zmod')\n"
        "    notes = {'x': getattr(m, 'X', None)}\n",
        label="zipimport", extra_files={})
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_sourcefileloader_rejected(run_attack2j):
    """G6:SourceFileLoader 从源码加载模块。"""
    outcome = run_attack2j(
        "    from importlib.machinery import SourceFileLoader\n"
        "    m = SourceFileLoader('smod', '/builder_pkg/helpers.py')"
        ".load_module()\n"
        "    notes = {'m': m.__name__}\n",
        label="sourcefileloader")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")
