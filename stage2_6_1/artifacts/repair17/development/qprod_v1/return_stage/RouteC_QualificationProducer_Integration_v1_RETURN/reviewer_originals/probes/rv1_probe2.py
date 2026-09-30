# RV1 probe 2: protected_old_roots derivation vs actual tree layouts.
import sys
from pathlib import Path
SRC = "/home/cryptorl/projects/crypto_rl/src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import rl_curriculum.curriculum261_qprod_context as cx

pkg = Path(cx.__file__).resolve().parent
print("pkg_dir:", pkg)
print("parents[1]:", pkg.parents[1])
print("parents[2]:", pkg.parents[2])
print("parents[3]:", pkg.parents[3])
roots = cx.protected_old_roots()
print("protected_old_roots():", [str(r) for r in roots])
frozen = pkg.parents[1] / "artifacts" / "route_c_stage2_6_1_repair17"
print("actual deploy frozen root exists:", frozen.is_dir(), frozen)
if frozen.is_dir():
    try:
        out = cx.harden_root(frozen / "qprod_probe_child", label="probe",
                             create=False)
        print("GAP-CONFIRMED: harden_root ACCEPTED path inside frozen root:",
              out)
    except cx.QProdContextError as exc:
        print("harden_root rejected (protection effective):", str(exc)[:120])
# repo-tree replication (pure logic, no import of repo tree)
repo_pkg = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/src/rl_curriculum")
for base in (repo_pkg.parents[2], repo_pkg.parents[3]):
    art = base / "artifacts"
    print("repo-derivation candidate:", art, "is_dir=", art.is_dir())
print("repo actual artifacts dir:",
      (repo_pkg.parents[1] / "artifacts").is_dir(),
      repo_pkg.parents[1] / "artifacts")
