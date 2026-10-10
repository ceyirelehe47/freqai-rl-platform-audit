# -*- coding: utf-8 -*-
# Corrective probe: projection-based three-way compare + mtime-based old-scene check
import hashlib, json, os, subprocess, sys, time, datetime
from pathlib import Path

OUT = Path("/home/cryptorl/tmp_rcw_r3")
P3 = "/home/cryptorl/projects/crypto_rl_qaf_v3"
D3 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3"
PIN = "/home/cryptorl/release_pin_qaf_v3"
P2 = "/home/cryptorl/projects/crypto_rl_qaf_v2"
D2 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2"
P1 = "/home/cryptorl/projects/crypto_rl"
REPO = "/mnt/f/trading/freqai-rl-audit"

EXCL = ("__pycache__", ".pytest_cache", ".cache", ".git")
def scan(root):
    m = {}
    for f in Path(root).rglob("*"):
        try:
            if not f.is_file() or f.is_symlink():
                continue
            rel = f.relative_to(root).as_posix()
            b = f.read_bytes()
        except OSError:
            continue
        if any(p in EXCL for p in rel.split("/")):
            continue
        m[rel] = hashlib.sha256(b.replace(b"\r", b"")).hexdigest()
    return m

def project_deploy(m):
    # deploy-layout keys: src/rl_curriculum/x, tests/route_c_stage2_6_1/x, stage2_6_1_runner/x
    out = {}
    for k, v in m.items():
        if k.startswith("src/rl_curriculum/") or k.startswith("tests/route_c_stage2_6_1/") \
           or k.startswith("stage2_6_1_runner/"):
            out[k] = v
    return out

def project_repo(m):
    # repo-layout (PIN): strip stage2_6_1/ and map runner to deploy name
    out = {}
    for k, v in m.items():
        if k.startswith("stage2_6_1/src/rl_curriculum/"):
            out["src/rl_curriculum/" + k[len("stage2_6_1/src/rl_curriculum/"):]] = v
        elif k.startswith("stage2_6_1/tests/route_c_stage2_6_1/"):
            out["tests/route_c_stage2_6_1/" + k[len("stage2_6_1/tests/route_c_stage2_6_1/"):]] = v
        elif k.startswith("stage2_6_1/runner/"):
            out["stage2_6_1_runner/" + k[len("stage2_6_1/runner/"):]] = v
    return out

P3m = scan(P3); D3m = scan(D3); PINm = scan(PIN)
p3 = project_deploy(P3m); d3 = project_deploy(D3m); pin = project_repo(PINm)
res = {}
for name, (x, y) in {"P3D3": (p3, d3), "P3PIN": (p3, pin), "D3PIN": (d3, pin)}.items():
    shared = set(x) & set(y)
    diff = sorted(k for k in shared if x[k] != y[k])
    res[name] = {"shared": len(shared), "equal": len(shared) - len(diff),
                 "diff_samples": diff[:10]}
print("THREEWAY_PROJECTED " + json.dumps(res, indent=1))
# composition hints
for label, mm in (("P3", p3), ("D3", d3), ("PINproj", pin)):
    comp = {}
    for k in mm:
        top = k.split("/")[0]
        comp[top] = comp.get(top, 0) + 1
    print("COMP_" + label + " " + json.dumps(comp))
(OUT / "three_way_rcw2.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

print("== old scene mtimes (local tz) ==")
def newest(root, n=5):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in EXCL]
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                out.append((os.path.getmtime(fp), fp))
            except OSError:
                pass
    out.sort(reverse=True)
    return out[:n]
for root in (P2, D2):
    top = newest(root)
    print("NEWEST_" + root.split("/")[-1])
    for t, fp in top:
        print("  %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)), fp))
# any file at/after 2026-10-06 00:00 local?
cutoff = time.mktime(time.strptime("2026-10-06 00:00:00", "%Y-%m-%d %H:%M:%S"))
viol = {}
for root in (P2, D2):
    bad = [fp for t, fp in newest(root, 10**9) if t >= cutoff]
    viol[root] = bad
print("P2_D2_FILES_AFTER_1006 " + json.dumps({k: v[:8] for k, v in viol.items()}))

print("== rt_runs by date ==")
runs = sorted((Path(P1) / "r17_rt_runs").glob("2026100[56]*"))
by = {}
for r in runs:
    by[r.name[:8]] = by.get(r.name[:8], 0) + 1
print("RT_RUNS_BY_DAY " + json.dumps(by) + " total=" + str(len(runs)))

print("== crypto_rl synced src files vs candidate blobs ==")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
for rel in ("stage2_6_1/src/rl_curriculum/curriculum261_r17_admission_substance.py",
            "stage2_6_1/src/rl_curriculum/__init__.py"):
    p = subprocess.run(["git", "-C", REPO, "show", "85a879a46d0a20831644eb9aae52e0537436713f:" + rel],
                       capture_output=True)
    blob = p.stdout
    dep = P1 + "/src/rl_curriculum/" + rel.split("/")[-1]
    raw = sha(dep)
    blob_raw = hashlib.sha256(blob).hexdigest()
    blob_cr = hashlib.sha256(blob.replace(b"\r", b"")).hexdigest()
    print("SYNC %s deployed=%s blob_raw_eq=%s blob_crstrip_eq=%s" % (rel.split("/")[-1], raw[:16], raw == blob_raw, raw == blob_cr))
