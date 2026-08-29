import subprocess
from pathlib import Path

V = Path("/home/cryptorl/projects/crypto_rl/vendor/freqtrade")
OUT = Path("/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_0i"
           "/upstream_integrity.txt")
head = subprocess.run(["git", "-C", str(V), "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
status = subprocess.run(["git", "-C", str(V), "status", "--porcelain"],
                        capture_output=True, text=True).stdout.strip()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(
    "# upstream integrity (vendor/freqtrade)\n"
    "expected HEAD: 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5\n"
    f"actual HEAD:   {head}\n"
    f"worktree: {'clean' if not status else 'DIRTY:\\n' + status}\n",
    encoding="utf-8")
print(OUT.read_text())
