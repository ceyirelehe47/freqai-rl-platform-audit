"""内容寻址 Runtime Environment Bundle(阶段 2.6.0i:工作包 A)。

正式 Builder Worker 的整个只读根文件系统在启动前由可信 Supervisor
组装为一个**内容寻址 staging 树**(硬链接优先,跨设备回退复制),并
计算逐文件 manifest(rbm- 摘要):

    <staging>/
      bin/ lib/ ssl/ etc/ share/ conda-meta/ ...   <- conda env(硬链接)
      lib/x86_64-linux-gnu/*.so.*                  <- 系统库闭包(复制)
      lib64/ld-linux-x86-64.so.2                   <- 动态链接器(复制)
      runtime/rl_builder_runtime/...               <- Runner 运行时(复制)
      builder_pkg/...                              <- 受承诺 Builder 包(复制)
      dev-internal/{urandom,random}                <- 确定性虚拟熵源(生成)
      manifest.json / bundle_meta.json             <- 内容清单与归属元数据
      dev/ proc/ tmp/ run/ scratch/ oldroot/       <- 骨架(启动时 tmpfs/挂载)

安全性质(对应 2.6.0i A1/A3/A4/A5):
- 可见只读文件全集 == manifest 已承诺全集(pivot 后宿主路径不可命名);
- RECORD 只作辅助元数据(dist 归属);内容绑定以 manifest 为准;
- RECORD 解析用标准 csv,拒绝绝对路径/../重复路径,无哈希条目显式记录;
- 设备/FIFO/socket 拒绝;symlink 绑定目标且必须解析回 env 内;
- 组装后任何内容变化(含硬链接别名就地改写)由全量重哈希发现。

Worker 在 pivot 后、exec 前对本 manifest 做全量复验(验证的是**实际
挂载内容**);Supervisor 在运行结束后再次复验 staging(TOCTOU/E10)。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path

RUNTIME_BUNDLE_MANIFEST_FORMAT = "builder-runtime-bundle-manifest-v1"
RUNTIME_BUNDLE_META_FORMAT = "builder-runtime-bundle-meta-v1"
BUNDLE_MANIFEST_FILENAME = "manifest.json"
BUNDLE_META_FILENAME = "bundle_meta.json"

#: 组装时排除的路径(确定性:排除物不属于 Worker 可见输入)
BUNDLE_EXCLUDE_DIRS = frozenset({"__pycache__"})
BUNDLE_EXCLUDE_SUFFIXES = (".pyc", ".pyo")

#: staging 骨架空目录(启动时被 tmpfs/挂载覆盖或保持为空;全部进 manifest)
SKELETON_DIRS = ("dev", "proc", "tmp", "run", "scratch", "oldroot")

#: 确定性虚拟熵源(字节由固定种子链生成;内容进 manifest = 受承诺)
DETERMINISTIC_ENTROPY_SEED = b"rl-builder-deterministic-entropy-v1"
DETERMINISTIC_ENTROPY_BYTES = 65536

#: 系统库搜索根(按序解析 DT_NEEDED;bundle 内 lib/ 优先)
SYSLIB_SEARCH_ROOTS = (
    "/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu",
    "/lib64", "/usr/lib64", "/lib", "/usr/lib",
)


class BundleError(RuntimeError):
    """Bundle 组装/验证失败(fail closed;消息已脱敏)。"""


# ------------------------------------------------------------ 哈希工具
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parallel_hash(pairs, *, jobs: int = 4):
    """并行哈希:线程池编排独立子进程(避免 Supervisor 自身 fork 语义)。

    仅限宿主视图(子进程需要可用的 sys.executable);沙箱内串行。
    """
    if jobs <= 1 or len(pairs) < 512:
        return {p: _serial_hash_one(p, s) for p, _, s in pairs}
    import concurrent.futures as cf

    chunk = (len(pairs) + jobs - 1) // jobs
    chunks = [pairs[i:i + chunk] for i in range(0, len(pairs), chunk)]
    merged: dict[str, str] = {}
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        for part in pool.map(_run_hash_subprocess, chunks):
            merged.update(part)
    return merged


def _serial_hash_one(abs_path: str, size: int) -> str:
    st = os.lstat(abs_path)
    if stat.S_ISLNK(st.st_mode):
        return "symlink:" + os.readlink(abs_path)
    if not stat.S_ISREG(st.st_mode):
        return "irregular"
    if st.st_size != size:
        return "size-mismatch"
    return sha256_file(Path(abs_path))


def _run_hash_subprocess(chunk):
    """用独立子进程哈希一批文件(避免 Supervisor 自身 fork 语义)。

    脚本首行携带身份标记(rl_builder_runtime.bundle-parallel-hash):
    Builder 阶段访问守卫以此识别 Supervisor 的复验 worker——它只
    读取 staging 内容,不触碰任何候选材料。
    """
    script = (
        "# rl_builder_runtime.bundle-parallel-hash\n"
        "import json,sys,hashlib,os,stat\n"
        "pairs=json.load(sys.stdin)\n"
        "out=[]\n"
        "for p,e,s in pairs:\n"
        "    try:\n"
        "        st=os.lstat(p)\n"
        "        if stat.S_ISLNK(st.st_mode):\n"
        "            out.append([p,'symlink:'+os.readlink(p)]);continue\n"
        "        if not stat.S_ISREG(st.st_mode):\n"
        "            out.append([p,'irregular']);continue\n"
        "        if st.st_size!=s:\n"
        "            out.append([p,'size-mismatch']);continue\n"
        "        h=hashlib.sha256()\n"
        "        with open(p,'rb') as fh:\n"
        "            for c in iter(lambda:fh.read(1<<20),b''):h.update(c)\n"
        "        out.append([p,h.hexdigest()])\n"
        "    except OSError as exc:\n"
        "        out.append([p,'oserr:%d'%exc.errno])\n"
        "sys.stdout.write(json.dumps(out))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(chunk), capture_output=True, text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        raise BundleError("并行哈希子进程失败(fail closed)")
    return dict((p, v) for p, v in json.loads(proc.stdout))


# ------------------------------------------------------------ ELF 解析
def elf_needed_and_interp(path: os.PathLike | str):
    """ELF64 的 (DT_NEEDED 列表, PT_INTERP);非 ELF 返回 (None, None)。

    DT_STRTAB 是虚拟地址,经 PT_LOAD (vaddr -> 文件偏移) 映射解析。
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None, None
    if len(data) < 64 or data[:5] != b"\x7fELF\x02" or data[5] != 1 \
            or data[6] != 1:
        return None, None
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x36)[0]
    e_phnum = struct.unpack_from("<H", data, 0x38)[0]
    loads: list[tuple[int, int, int]] = []
    needed: list[str] = []
    interp = None
    dyn_off = dyn_filesz = None

    def vaddr_to_off(v: int) -> int | None:
        for vaddr, off, filesz in loads:
            if vaddr <= v < vaddr + filesz:
                return off + (v - vaddr)
        return None

    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 56 > len(data):
            break
        p_type = struct.unpack_from("<I", data, off)[0]
        if p_type == 3:  # PT_INTERP
            p_offset = struct.unpack_from("<Q", data, off + 8)[0]
            end = data.index(b"\0", p_offset)
            interp = data[p_offset:end].decode("utf-8", "replace")
        elif p_type == 2:  # PT_DYNAMIC
            dyn_off = struct.unpack_from("<Q", data, off + 8)[0]
            dyn_filesz = struct.unpack_from("<Q", data, off + 32)[0]
        elif p_type == 1:  # PT_LOAD
            loads.append((
                struct.unpack_from("<Q", data, off + 16)[0],
                struct.unpack_from("<Q", data, off + 8)[0],
                struct.unpack_from("<Q", data, off + 32)[0]))
    if dyn_off is None or dyn_filesz is None \
            or dyn_off + dyn_filesz > len(data):
        return needed, interp
    entries = []
    strtab = None
    for j in range(dyn_filesz // 16):
        tag, val = struct.unpack_from("<QQ", data, dyn_off + j * 16)
        if tag == 0:
            break
        entries.append((tag, val))
        if tag == 5:
            strtab = val
    if strtab is None:
        return needed, interp
    stroff = vaddr_to_off(strtab)
    if stroff is None:
        return needed, interp
    for tag, val in entries:
        if tag == 1:
            s = vaddr_to_off(strtab + val)
            if s is None:
                continue
            e2 = data.index(b"\0", s)
            try:
                needed.append(data[s:e2].decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return needed, interp


def syslib_closure(env_root: Path) -> tuple[dict[str, str], list[str]]:
    """env 内全部 ELF 的 DT_NEEDED 传递闭包 -> (soname -> 宿主路径)。

    bundle 自带 lib/ 优先解析(env 内库留在 env 树内,不进 syslib 集)。
    返回的第二项是 rpath 域名(如 libtorch_cpu.so,由 $ORIGIN 解析,
    已随 env 树提交,不需要系统路径)。
    """
    env_lib = env_root / "lib"
    sonames: dict[str, str] = {}
    rpath_names: list[str] = []
    queue: list[str] = []
    for root, dirs, files in os.walk(env_root):
        dirs[:] = [d for d in dirs if d not in BUNDLE_EXCLUDE_DIRS]
        for f in files:
            if f.endswith(BUNDLE_EXCLUDE_SUFFIXES):
                continue
            needed, interp = elf_needed_and_interp(os.path.join(root, f))
            if needed is None and interp is None:
                continue
            if needed:
                queue.extend(needed)
            if interp:
                p = Path(interp)
                if not (env_root / "lib" / p.name).exists() and p.exists():
                    sonames[p.name] = str(p)
    seen = set(queue)
    while queue:
        name = queue.pop()
        if name in sonames or name == "linux-vdso.so.1":
            continue
        cand = env_lib / name
        if cand.exists():
            sonames[name] = str(cand)   # env 内库:随 env 树提交
            continue
        src = None
        for root in SYSLIB_SEARCH_ROOTS:
            p = Path(root) / name
            if p.exists():
                src = str(p)
                break
        if src is None:
            rpath_names.append(name)    # 由 $ORIGIN/rpath 在 env 内解析
            continue
        sonames[name] = src
        for n in (elf_needed_and_interp(src)[0] or []):
            if n not in seen and n != "linux-vdso.so.1":
                seen.add(n)
                queue.append(n)
    return sonames, sorted(set(rpath_names))


# ------------------------------------------------------------ RECORD 解析
def parse_record_csv(text: str, *, label: str) -> list[dict]:
    """A4:标准 csv 解析 RECORD;安全相关异常一律 fail closed。

    每个条目返回 {path, hash_sha256|None, size|None};URL-safe base64
    形如 sha256=<43字符无填充>。拒绝:绝对路径、..逃逸、重复路径、
    非 sha256 的有哈希条目(其他算法显式记录为 other_algo)。
    """
    import base64
    import csv
    import io

    entries: list[dict] = []
    seen: set[str] = set()
    reader = csv.reader(io.StringIO(text))
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise BundleError(f"{label} RECORD csv 解析失败: {exc}")
    for row in rows:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) < 3:
            raise BundleError(
                f"{label} RECORD 条目字段不足({len(row)}):安全相关"
                f"异常不得静默跳过")
        rel, hash_spec, size_spec = row[0].strip(), row[1].strip(), \
            row[2].strip()
        if not rel:
            raise BundleError(f"{label} RECORD 存在空路径条目")
        if rel.startswith("/"):
            raise BundleError(
                f"{label} RECORD 条目是绝对路径({rel!r} 前缀,"
                f"已脱敏)")
        if rel in seen:
            raise BundleError(f"{label} RECORD 重复路径条目(已脱敏)")
        seen.add(rel)
        # "../" 层级是 pip 惯例(脚本指向 site-packages 外但仍在
        # distribution 安装树内):保留并标记;解析到 bundle 外时由
        # 调用方(dist_ownership)记入 escape 标志
        traversal = rel.split("/")[0] == ".." or "/../" in f"/{rel}/"
        entry = {"path": rel, "sha256": None, "size": None,
                 "hash_algo": None, "traversal": traversal}
        if hash_spec:
            algo, _, value = hash_spec.partition("=")
            if algo != "sha256":
                entry["hash_algo"] = algo
            else:
                if len(value) != 43 or not value.replace("-", "a").replace(
                        "_", "a").isalnum():
                    raise BundleError(
                        f"{label} RECORD sha256 值非 URL-safe base64"
                        f"(已脱敏)")
                try:
                    digest = base64.urlsafe_b64decode(value + "=")
                    if len(digest) != 32:
                        raise ValueError
                    entry["sha256"] = digest.hex()
                    entry["hash_algo"] = "sha256"
                except (ValueError, TypeError) as exc:
                    raise BundleError(
                        f"{label} RECORD sha256 值解码失败(已脱敏)") from exc
        if size_spec:
            try:
                entry["size"] = int(size_spec)
            except ValueError as exc:
                raise BundleError(
                    f"{label} RECORD size 字段非整数(已脱敏)") from exc
        entries.append(entry)
    return entries


def dist_ownership_from_bundle(
        staging_root: Path) -> tuple[dict[str, list[str]], list[dict]]:
    """从 bundle 内 site-packages 的 RECORD 建立路径 -> dist 归属映射。

    返回 (owners, namespace_pkgs);同一文件被多个 distribution 声明
    视为多义(导入闭包遇到时 fail closed)。RECORD 只是辅助元数据:
    bundle manifest 才是内容权威。
    """
    owners: dict[str, list[str]] = {}
    ambiguous: list[dict] = []
    sp = staging_root / "lib" / "python3.11" / "site-packages"
    if not sp.is_dir():
        return owners, ambiguous
    for dist_info in sorted(sp.glob("*.dist-info")):
        record = dist_info / "RECORD"
        if not record.is_file():
            continue
        # 归属名优先取 METADATA Name(importlib.metadata 语义);
        # dist-info 目录名可能含版本后缀(如 numpy-2.4.6)
        dist_name = dist_info.name[:-len(".dist-info")]
        metadata_path = dist_info / "METADATA"
        if metadata_path.is_file():
            for line in metadata_path.read_text(
                    encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("name:"):
                    declared = line.partition(":")[2].strip()
                    if declared:
                        dist_name = declared
                    break
        try:
            entries = parse_record_csv(
                record.read_text(encoding="utf-8", errors="strict"),
                label=dist_name)
        except (BundleError, UnicodeDecodeError):
            # RECORD 损坏的 distribution:其文件全部标记为不可归属
            ambiguous.append({"distribution": dist_name,
                              "problem": "record-unparsable"})
            continue
        for e in entries:
            abs_rel = (sp / e["path"]).resolve(strict=False)
            try:
                rel = str(Path(abs_rel).relative_to(staging_root))
            except ValueError:
                # 解析到 bundle 外:记入逃逸标志(不进入归属映射)
                ambiguous.append({"distribution": dist_name,
                                  "problem": "path-escape",
                                  "traversal": bool(e.get("traversal"))})
                continue
            rel = Path(rel).as_posix()
            owners.setdefault(rel, []).append(dist_name)
    for rel, names in owners.items():
        if len(names) > 1:
            ambiguous.append({"path": rel,
                              "distributions": sorted(set(names))})
    return {k: sorted(set(v)) for k, v in owners.items()}, ambiguous


# ------------------------------------------------------------ 熵源文件
def deterministic_entropy_bytes() -> bytes:
    """确定性虚拟熵源内容(固定种子 sha256 链;每次组装完全一致)。"""
    out = bytearray()
    counter = 0
    block = DETERMINISTIC_ENTROPY_SEED
    while len(out) < DETERMINISTIC_ENTROPY_BYTES:
        block = hashlib.sha256(block + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:DETERMINISTIC_ENTROPY_BYTES])


# ------------------------------------------------------------ manifest
def bundle_manifest_digest(manifest: dict) -> str:
    """manifest 的 canonical 摘要(rbm-)。"""
    return "rbm-" + hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def scan_bundle_tree(staging_root: Path, *, jobs: int = 1) -> list[dict]:
    """扫描 staging 树,产出排序 manifest 条目(文件/符号链接/目录)。

    jobs>1 时文件哈希走并行子进程(宿主视图;沙箱内组装用串行)。
    """
    entries: list[dict] = []
    staging_root = Path(staging_root)
    files_to_hash: list[Path] = []
    for root, dirs, files in os.walk(staging_root):
        dirs[:] = sorted(d for d in dirs
                         if d not in BUNDLE_EXCLUDE_DIRS)
        rel_root = Path(root).relative_to(staging_root)
        for d in dirs:
            src = Path(root) / d
            if src.is_symlink():
                entries.append({
                    "path": (rel_root / d).as_posix(),
                    "type": "symlink", "target": os.readlink(src)})
            else:
                entries.append({
                    "path": (rel_root / d).as_posix(), "type": "dir"})
        for f in sorted(files):
            if f.endswith(BUNDLE_EXCLUDE_SUFFIXES):
                continue
            src = Path(root) / f
            rel = (rel_root / f).as_posix()
            st = src.lstat()
            if stat.S_ISLNK(st.st_mode):
                entries.append({"path": rel, "type": "symlink",
                                "target": os.readlink(src)})
                continue
            if not stat.S_ISREG(st.st_mode):
                raise BundleError(
                    f"bundle 含非普通文件 {rel!r}(设备/FIFO/socket 被拒绝;"
                    f"A5;已脱敏)")
            entries.append({"path": rel, "type": "file",
                            "size": st.st_size,
                            "mode": st.st_mode & 0o777,
                            "sha256": ""})
            files_to_hash.append(src)
    entries.sort(key=lambda e: e["path"])
    if files_to_hash:
        pairs = [(str(p), "", p.stat().st_size) for p in files_to_hash]
        hashes = _parallel_hash(pairs, jobs=jobs)
        for e in entries:
            if e["type"] == "file":
                e["sha256"] = hashes[str(staging_root / e["path"])]
    return entries


def build_manifest(staging_root: Path, *, python_version: str,
                   syslibs: dict[str, str], rpath_names: list[str],
                   jobs: int = 1) -> dict:
    entries = scan_bundle_tree(staging_root, jobs=jobs)
    return {
        "format": RUNTIME_BUNDLE_MANIFEST_FORMAT,
        "python_version": python_version,
        "entries": entries,
        "syslib_sonames": sorted(syslibs),
        "rpath_resolved_names": sorted(rpath_names),
        "deterministic_entropy": {
            "urandom_sha256": hashlib.sha256(
                deterministic_entropy_bytes()).hexdigest(),
        },
    }


def verify_runtime_bundle(staging_root: Path, manifest: dict, *,
                          jobs: int = 4,
                          expect_digest: str | None = None,
                          skip_prefixes: tuple[str, ...] = ()) -> dict:
    """全量复验:实际 staging 树 == manifest(逐文件哈希 + 结构)。

    fail closed:任何额外/缺失/内容变化/类型变化立即抛 BundleError。
    skip_prefixes:运行时挂载点(相对路径前缀,如 "dev/")——挂载视图
    验证时跳过;其内容由挂载摘要与 EDIC 探针管辖。manifest.json 文件
    自身总是跳过(自举;其完整性由自洽摘要与 evidence 期望值保证)。
    """
    staging_root = Path(staging_root)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise BundleError("manifest 缺少条目(无法验证)")

    def _skipped(rel: str) -> bool:
        return rel == BUNDLE_MANIFEST_FILENAME or any(
            rel == p[:-1] or rel.startswith(p) for p in skip_prefixes)

    entries = [e for e in entries if not _skipped(e["path"])]
    expected_files = [e for e in entries if e.get("type") == "file"]
    expected_links = {e["path"]: e.get("target")
                      for e in entries if e.get("type") == "symlink"}
    expected_dirs = {e["path"] for e in entries if e.get("type") == "dir"}
    expected_paths = {e["path"] for e in entries}
    # 1) 结构 walk(廉价先检:额外/缺失路径)
    actual_paths: set[str] = set()
    for root, dirs, files in os.walk(staging_root):
        dirs[:] = sorted(d for d in dirs
                         if d not in BUNDLE_EXCLUDE_DIRS
                         and not _skipped(
                             (Path(root).relative_to(staging_root) / d)
                             .as_posix()))
        rel_root = Path(root).relative_to(staging_root)
        for d in dirs:
            actual_paths.add((rel_root / d).as_posix())
        for f in files:
            if not f.endswith(BUNDLE_EXCLUDE_SUFFIXES) \
                    and not _skipped((rel_root / f).as_posix()):
                actual_paths.add((rel_root / f).as_posix())
    extra = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    if extra or missing:
        raise BundleError(
            f"bundle 结构与 manifest 不一致(TOCTOU/篡改;fail closed):"
            f"额外 {extra[:6]},缺失 {missing[:6]}(已脱敏)")
    # 2) 符号链接目标
    for rel, target in expected_links.items():
        actual_target = os.readlink(staging_root / rel)
        if actual_target != target:
            raise BundleError(
                f"bundle 符号链接目标变化 {rel!r}(已脱敏)")
    # 3) 并行/串行全量哈希
    pairs = [(str(staging_root / e["path"]), e["sha256"], e["size"])
             for e in expected_files]
    actual = _parallel_hash(pairs, jobs=jobs)
    for e in expected_files:
        got = actual.get(str(staging_root / e["path"]))
        if got != e["sha256"]:
            raise BundleError(
                f"bundle 文件内容与 manifest 不一致({e['path']!r} 前缀,"
                f"已脱敏;hardlink 别名就地改写或直接篡改被发现)")
    if expect_digest is not None and bundle_manifest_digest(manifest) \
            != expect_digest:
        raise BundleError("manifest 摘要与期望不符(fail closed)")
    return {
        "verified_files": len(expected_files),
        "verified_symlinks": len(expected_links),
        "verified_dirs": len(expected_dirs),
        "digest": bundle_manifest_digest(manifest),
    }


# ------------------------------------------------------------ 组装
def _link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)
        return "link"
    except OSError as exc:
        if exc.errno in (18, 1):  # EXDEV / EPERM(跨设备或 overlay)
            shutil.copy2(src, dst)
            return "copy"
        raise


def assemble_runtime_bundle(
        *, env_root: Path | str, staging_root: Path | str,
        runtime_src: Path | str, builder_pkg_root: Path | str,
        hostname: str = "builder-worker",
        jobs: int = 4) -> dict:
    """组装内容寻址 bundle staging 并返回 manifest(含 rbm- 摘要)。

    staging 必须不存在(全新);组装后由调用方在 exec 前与运行后各做
    一次 verify_runtime_bundle。
    """
    env_root = Path(env_root).resolve()
    staging_root = Path(staging_root)
    runtime_src = Path(runtime_src)
    builder_pkg_root = Path(builder_pkg_root)
    if staging_root.exists():
        raise BundleError("staging 已存在,拒绝覆盖(全新组装,防复用污染)")
    if not env_root.is_dir() or not (env_root / "lib" / "python3.11"
                                     ).is_dir():
        raise BundleError("conda env 根不合法(缺 lib/python3.11)")
    staging_root.mkdir(parents=True)
    stats = {"link": 0, "copy": 0, "symlink": 0}

    def _copy_filtered(src_dir: Path, dst_dir: Path, label: str):
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs
                             if d not in BUNDLE_EXCLUDE_DIRS)
            rel_root = Path(root).relative_to(src_dir)
            (dst_dir / rel_root).mkdir(parents=True, exist_ok=True)
            for d in dirs:
                s = Path(root) / d
                if s.is_symlink():
                    target = os.readlink(s)
                    _check_symlink_target(s, target, src_dir, label)
                    os.symlink(target, dst_dir / rel_root / d)
                    stats["symlink"] += 1
            for f in sorted(files):
                if f.endswith(BUNDLE_EXCLUDE_SUFFIXES):
                    continue
                s = Path(root) / f
                d = dst_dir / rel_root / f
                if s.is_symlink():
                    target = os.readlink(s)
                    _check_symlink_target(s, target, src_dir, label)
                    os.symlink(target, d)
                    stats["symlink"] += 1
                    continue
                st = s.lstat()
                if not stat.S_ISREG(st.st_mode):
                    raise BundleError(
                        f"{label} 源含非普通文件(设备/FIFO 拒绝;"
                        f"A5;已脱敏)")
                kind = _link_or_copy(s, d)
                stats[kind] += 1

    # 1) conda env(硬链接;符号链接绑定并验证目标在 env 内)
    _copy_filtered(env_root, staging_root, label="conda env")
    # 2) 系统库闭包(复制:跨设备/overlay)
    syslibs, rpath_names = syslib_closure(env_root)
    (staging_root / "lib" / "x86_64-linux-gnu").mkdir(
        parents=True, exist_ok=True)
    (staging_root / "lib64").mkdir(parents=True, exist_ok=True)
    for name, src in sorted(syslibs.items()):
        dst = staging_root / "lib64" / name \
            if name == "ld-linux-x86-64.so.2" \
            else staging_root / "lib" / "x86_64-linux-gnu" / name
        shutil.copy2(src, dst)
    # 3) Runner 运行时与 Builder 包(复制,与 0h staging 语义一致)
    _copy_filtered(runtime_src, staging_root / "runtime" / "rl_builder_runtime",
                   label="rl_builder_runtime")
    _copy_filtered(builder_pkg_root, staging_root / "builder_pkg",
                   label="builder package")
    # 4) 确定性虚拟熵源(内容固定;启动时 ro bind 到 /dev/{u,}random)
    entropy = deterministic_entropy_bytes()
    di = staging_root / "dev-internal"
    di.mkdir()
    (di / "urandom").write_bytes(entropy)
    (di / "random").write_bytes(entropy)
    # 5) 骨架空目录
    for d in SKELETON_DIRS:
        (staging_root / d).mkdir()
    # 6) 归属元数据先落盘(进入 manifest 条目,哈希绑定);manifest.json
    #    自身不进条目(自举:其完整性由 manifest_digest 自洽与 evidence
    #    期望值保证,树验证时显式跳过)
    python_version = _env_python_version(env_root)
    owners, ambiguous = dist_ownership_from_bundle(staging_root)
    syslib_sources = {k: str(v) for k, v in syslibs.items()}
    entropy_sha = hashlib.sha256(entropy).hexdigest()
    meta = {
        "format": RUNTIME_BUNDLE_META_FORMAT,
        "python": {"executable": "/bin/python3.11",
                   "prefix": "/", "version": python_version},
        "dist_ownership": owners,
        "ambiguous_dist_paths": ambiguous,
        "syslib_sources": syslib_sources,
        "rpath_resolved_names": sorted(rpath_names),
        "deterministic_entropy_sha256": entropy_sha,
        "hostname": hostname,
    }
    (staging_root / BUNDLE_META_FILENAME).write_text(
        json.dumps(meta, sort_keys=True, ensure_ascii=False))
    manifest = build_manifest(
        staging_root, python_version=python_version, syslibs=syslibs,
        rpath_names=rpath_names, jobs=jobs)
    manifest["bundle_hostname"] = hostname
    digest = bundle_manifest_digest(manifest)
    manifest["manifest_digest"] = digest
    (staging_root / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False))
    return {"manifest": manifest, "digest": digest, "meta": meta,
            "stats": dict(stats), "staging_root": str(staging_root),
            "syslib_count": len(syslibs)}


def _check_symlink_target(link: Path, target: str, root: Path, label: str):
    """A5:symlink 绑定 link 与最终目标;目标必须解析回源根内。"""
    if target.startswith("/"):
        resolved = Path(target)
    else:
        resolved = (link.parent / target).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise BundleError(
            f"{label} 符号链接目标逃逸源根(A5 拒绝;已脱敏)") from exc


def _env_python_version(env_root: Path) -> str:
    # -c 脚本首行携带身份标记(Builder 阶段访问守卫识别 Supervisor
    # 的组装子进程;不触碰任何候选材料)。PYTHONHOME 指向真实 env:
    # 微型 env(mini conda 布局,无完整 stdlib)的 python 副本需要
    # 宿主解释器的 stdlib 才能完成初始化;bundle 内实际运行的是
    # env_root/bin/python3.11 的硬链接,其版本与真实 env 一致。
    real_prefix = Path(sys.executable).resolve().parent.parent
    child_env = dict(os.environ)
    child_env["PYTHONHOME"] = str(real_prefix)
    out = subprocess.run(
        [str(env_root / "bin" / "python3.11"), "-c",
         "# rl_builder_runtime.bundle-env-version\n"
         "import platform;print(platform.python_version())"],
        capture_output=True, text=True, timeout=60, env=child_env)
    if out.returncode != 0:
        raise BundleError("env python --version 失败(fail closed)")
    return out.stdout.strip().split()[-1]


def load_bundle_manifest(staging_root: Path | str) -> dict:
    p = Path(staging_root) / BUNDLE_MANIFEST_FILENAME
    if not p.is_file():
        raise BundleError("bundle manifest 文件缺失(fail closed)")
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BundleError(f"bundle manifest 无法解析(已脱敏)") from exc
    if manifest.get("format") != RUNTIME_BUNDLE_MANIFEST_FORMAT:
        raise BundleError("bundle manifest format 不符(fail closed)")
    if bundle_manifest_digest(
            {k: v for k, v in manifest.items() if k != "manifest_digest"}
    ) != str(manifest.get("manifest_digest") or ""):
        raise BundleError("bundle manifest 自身摘要不自洽(被改写)")
    return manifest


def load_bundle_meta(staging_root: Path | str) -> dict:
    p = Path(staging_root) / BUNDLE_META_FILENAME
    if not p.is_file():
        raise BundleError("bundle meta 文件缺失(fail closed)")
    meta = json.loads(p.read_text(encoding="utf-8"))
    if meta.get("format") != RUNTIME_BUNDLE_META_FORMAT:
        raise BundleError("bundle meta format 不符(fail closed)")
    return meta


def verify_mounted_bundle(staging_root: Path | str, *,
                          skip_prefixes: tuple[str, ...] = ()) -> dict:
    """挂载视图内(pivot 后、exec 前)的 manifest 自验证(串行哈希)。"""
    staging = Path(staging_root)
    manifest = load_bundle_manifest(staging)
    digest = manifest["manifest_digest"]
    core = {k: v for k, v in manifest.items() if k != "manifest_digest"}
    # 结构与逐文件复验(串行;jobs=1;跳过运行时挂载点)
    result = verify_runtime_bundle(
        staging, core, jobs=1, expect_digest=digest,
        skip_prefixes=skip_prefixes)
    return result
