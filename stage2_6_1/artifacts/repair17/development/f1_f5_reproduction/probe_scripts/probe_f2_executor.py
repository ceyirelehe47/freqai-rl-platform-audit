"""F2 反例探针:R16 execgov 执行者身份未闭合(真实模块行为验证)。

在真实 curriculum261_r16_execgov 上验证:
  C1 fork 子进程继承 session 对象与锁 fd → owns() 仍 True;
  C2 fork 子进程凭 env token 通过 verify_executor_token
     (委派记录 executor_pid=父进程;子进程非被委派执行者);
  C3 fork 子进程可 release 父会话(owns 通过 → _require_owned 通过);
  C4 spawn 的全新解释器进程复制 env token → verify_executor_token
     通过(bearer token;与当前执行者无关)。

隔离 CURRICULUM261_R16_STATE_ROOT 临时目录;零正式数据访问;
namespace 使用探针专用名。只读断言 R16 现状行为,不修改仓库文件。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.home() / "projects" / "crypto_rl" / "src"))

from rl_curriculum.curriculum261_r16_execgov import (  # noqa: E402
    R16FormalSession,
    R16AuthorizationError,
    R16_EXECUTOR_TOKEN_ENV,
    verify_executor_token,
)

PROBE_NS = "qualification_r16_f2_probe"
PROJ_SRC = Path.home() / "projects" / "crypto_rl" / "src"
results: dict[str, object] = {}

tmp = tempfile.mkdtemp(prefix="r17_f2_probe_")
os.environ["CURRICULUM261_R16_STATE_ROOT"] = tmp

session = R16FormalSession.acquire({
    "probe": "r17-f2", "mode": "probe", "iteration": "r16"})
session.record_exposure_started("f2-probe-digest")
grant = session.issue_generation_grant(namespaces=(PROBE_NS,))
token = grant.token

# -- C1/C2: fork 子进程(真实 fork;继承对象/fd/env) -------------------
r_pipe, w_pipe = os.pipe()
pid = os.fork()
if pid == 0:
    # 子进程:非被委派执行者,却持有继承的 session 对象与 env token
    out: dict[str, object] = {}
    out["child_owns_true"] = bool(session.owns())
    try:
        v = verify_executor_token(token, PROBE_NS)
        out["child_verify_token_passed"] = True
        out["child_verify_facts"] = v
    except R16AuthorizationError as exc:
        out["child_verify_token_passed"] = False
        out["child_verify_error"] = str(exc)[:200]
    os.write(w_pipe, json.dumps(out).encode())
    os.close(w_pipe)
    os._exit(0)
os.close(w_pipe)
with os.fdopen(r_pipe, "rb") as fh:
    fork_out = json.loads(fh.read())
os.waitpid(pid, 0)
results["fork_child"] = fork_out

# -- C4: spawn 全新解释器(仅复制 env token;须在 C3 release 之前) ---
import tempfile as _tf
_child = _tf.NamedTemporaryFile(
    "w", suffix="_f2_spawn.py", delete=False, encoding="utf-8")
with _child:
    _child.write(
        "import json, sys\n"
        "sys.path.insert(0, r'" + str(PROJ_SRC) + "')\n"
        "from rl_curriculum.curriculum261_r16_execgov import "
        "verify_executor_token, R16AuthorizationError\n"
        "try:\n"
        f"    v = verify_executor_token({token!r}, {PROBE_NS!r})\n"
        "    print(json.dumps({'spawn_verify_passed': True, "
        "'facts': v}))\n"
        "except R16AuthorizationError as e:\n"
        "    print(json.dumps({'spawn_verify_passed': False, "
        "'error': str(e)[:200]}))\n")
child_env = dict(os.environ)
child_env[R16_EXECUTOR_TOKEN_ENV] = token
child_env["CURRICULUM261_R16_STATE_ROOT"] = tmp
p = subprocess.run([sys.executable, _child.name], env=child_env,
                   capture_output=True, text=True, timeout=60)
try:
    results["spawn_child"] = json.loads(p.stdout.strip().splitlines()[-1])
except Exception:  # noqa: BLE001
    results["spawn_child"] = {"parse_error": p.stdout[-300:],
                              "stderr": p.stderr[-300:]}
os.unlink(_child.name)

if not fork_out.get("child_release_succeeded"):
    pass  # C3 改由下方第二个 fork 承担

# -- C3: fork 子进程可 release 父会话(在 C4 之后单独执行) ------------
r2, w2 = os.pipe()
pid2 = os.fork()
if pid2 == 0:
    out3: dict[str, object] = {}
    try:
        session.release(summary="child released parent session")
        out3["child_release_succeeded"] = True
    except Exception as exc:  # noqa: BLE001
        out3["child_release_succeeded"] = False
        out3["child_release_error"] = f"{type(exc).__name__}: {exc}"[:200]
    os.write(w2, json.dumps(out3).encode())
    os.close(w2)
    os._exit(0)
os.close(w2)
with os.fdopen(r2, "rb") as fh:
    fork3_out = json.loads(fh.read())
os.waitpid(pid2, 0)
results["fork_child_release"] = fork3_out
fork_out["child_release_succeeded"] = fork3_out.get(
    "child_release_succeeded")

results["defect_confirmation"] = {
    "C1_fork_child_owns": fork_out.get("child_owns_true")
    is True and "缺陷成立:fork 子进程 owns()==True",
    "C2_fork_child_verify_token": fork_out.get(
        "child_verify_token_passed") is True and
        "缺陷成立:非被委派的 fork 子进程凭继承 token 通过验证",
    "C3_fork_child_release": fork_out.get(
        "child_release_succeeded") is True and
        "缺陷成立:fork 子进程可 release 父会话",
    "C4_spawn_verify_token": (results["spawn_child"].get(
        "spawn_verify_passed") if isinstance(
        results.get("spawn_child"), dict) else None),
    "root_cause": "verify_executor_token 不验证当前执行者实例;"
                  "executor_delegated 的 executor_pid 仅记录不校验;"
                  "owns() 仅检查 released 标志与 lock_fh 非 None",
}

out_path = Path("/mnt/e/trading/freqai-rl-audit/stage2_6_1/artifacts/"
                "repair17/development/f1_f5_reproduction/"
                "f2_executor_identity_counterexample.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
json.dump({"format": "r17-f2-counterexample-v1",
           "module_under_test":
               "rl_curriculum.curriculum261_r16_execgov@d2ee974",
           "state_root": tmp, "results": results},
          open(out_path, "w"), indent=1, ensure_ascii=False)
print(json.dumps(results["defect_confirmation"], indent=1,
                 ensure_ascii=False))
print("written:", out_path)
