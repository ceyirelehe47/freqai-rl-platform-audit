#!/usr/bin/env bash
set -uo pipefail
python3 - <<'PY'
import os, time, subprocess
r, w = os.pipe()
os.set_blocking(w, False)
fill = b"x" * 4096; n = 0
while True:
    try: n += os.write(w, fill)
    except BlockingIOError: break
print("filled:", n)
os.set_blocking(w, True)
p = subprocess.Popen(["bash", "-c", 'trap "" TERM; sleep 30'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
time.sleep(0.3)
print("alive before TERM:", p.poll() is None,
      "members:", os.getpgid(p.pid))
os.killpg(os.getpgid(p.pid), 15)
time.sleep(0.5)
import glob
def members(pgid):
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try:
            t = open(f"/proc/{d}/stat").read()
            rp = t.rindex(")")
            f = t[rp+2:].split()
            if int(f[2]) == pgid and f[0] != "Z": out.append(d)
        except Exception: pass
    return out
pg = os.getpgid(p.pid)
print("after TERM alive:", p.poll() is None, "members:", members(pg))
time.sleep(1.2)
print("t+1.7s alive:", p.poll() is None, "members:", members(pg))
try: os.killpg(pg, 9)
except ProcessLookupError: pass
p.wait(timeout=5)
# 排空管道
os.set_blocking(r, False)
try:
    while True:
        if not os.read(r, 65536): break
except BlockingIOError: pass
os.close(r); 
try: os.close(w)
except OSError: pass
print("done")
PY
