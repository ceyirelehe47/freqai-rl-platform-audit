# ---------------------------------------- 回执入口与临时件所有权
# This block is inserted into r17_c3_engineering_slice.py without adding a
# runtime dependency. Its imports also permit testing the exact block alone.
import errno as _receipt_errno
import stat as _receipt_stat
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ReportTargetRejected(Exception):
    """回执目标未通过写前准入；不得为本次回执创建任何对象。"""


class ReceiptWriteError(Exception):
    """写入/发布/清理失败；保留首个错误及所有后续清理错误。"""

    def __init__(self, message, *, primary_error=None, cleanup_errors=(),
                 temporary_path=None, published_path=None):
        super().__init__(message)
        self.primary_error = primary_error
        self.cleanup_errors = tuple(cleanup_errors)
        self.temporary_path = temporary_path
        self.published_path = published_path


def _receipt_absolute(p: Path) -> Path:
    """固定相对路径基准，保留尚未经过文件系统解析的 '..'。"""
    raw = os.fspath(p)
    if not isinstance(raw, str) or not raw or '\x00' in raw:
        raise ReportTargetRejected(f"非法回执/输入路径: {raw!r}")
    path = Path(raw)
    return path if path.is_absolute() else Path.cwd() / path


def _resolve_target_strict(p: Path) -> Path:
    """严格解析现存部分，只允许普通、向下的新建后缀。

    不使用 strict=False，也不依赖 ALLOW_MISSING 的版本存在性。
    先让标准库严格解析完整路径；只有 ENOENT 才逐级剥离缺失的
    普通末端组件，再将该后缀接到严格确认的现存目录上。现存但
    无法解析的链接、缺失后缀中的 '..'、ENOTDIR/EACCES/ELOOP 等
    均拒绝。不是自行实现链接展开，也不词法消除链接后的 '..'。
    """
    original = _receipt_absolute(p)
    probe = original
    missing: list[str] = []
    try:
        # Ask the kernel about the original, uncollapsed path first. This
        # prevents a library's canonicalization from hiding ENOTDIR at
        # e.g. file/../new, including across Python maintenance versions.
        try:
            os.lstat(original)
        except FileNotFoundError:
            pass
        while True:
            try:
                resolved = Path(os.path.realpath(probe, strict=True))
            except FileNotFoundError:
                if probe.parent == probe or probe.name in ('', '.', '..'):
                    raise ReportTargetRejected(
                        f"缺失祖先/后缀无法可靠解析: {original}")
                # Strict resolution can fail because an EXISTING link is
                # dangling. That is not an ordinary missing component.
                try:
                    os.lstat(probe)
                except FileNotFoundError:
                    missing.append(probe.name)
                    probe = probe.parent
                    continue
                raise ReportTargetRejected(
                    f"现存条目无法严格解析(悬空祖先等): {probe}")
            if missing:
                st = os.stat(resolved)
                if not _receipt_stat.S_ISDIR(st.st_mode):
                    raise NotADirectoryError(
                        _receipt_errno.ENOTDIR,
                        '新建后缀的现存祖先不是目录', str(resolved))
            return resolved.joinpath(*reversed(missing))
    except (OSError, ValueError, RuntimeError) as exc:
        raise ReportTargetRejected(
            f"路径解析失败，拒绝写入: {original}; "
            f"{type(exc).__name__}(errno={getattr(exc, 'errno', None)}): "
            f"{exc}") from exc


def _receipt_lstat_or_missing(path: Path):
    """只把 FileNotFoundError 当成缺失；其他错误不得吞成 False。"""
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ReportTargetRejected(
            f"无法确认目录条目: {path}; "
            f"{type(exc).__name__}(errno={getattr(exc, 'errno', None)}): "
            f"{exc}") from exc


def _assert_report_target_safe(report_path: Path,
                               protect_roots: list) -> Path:
    """原末端条目不跟随检查；所有写入消费返回的同一确认目标。

    静态路径/链接及普通 I/O 故障范围。并非抵御管理员在准入后
    并发替换祖先目录的通用沙箱。原末端任何条目存在都拒绝，即使
    它是跨目录悬空链接。允许指向健康安全目录的父目录链接。
    """
    raw = _receipt_absolute(report_path)
    if raw.name in ('', '.', '..'):
        raise ReportTargetRejected(f"回执需要新文件名: {raw}")

    # Resolve the ORIGINAL PARENT, not the symlink target's parent. This
    # preserves the identity of the terminal directory entry for lstat.
    parent = _resolve_target_strict(raw.parent)
    parent_st = _receipt_lstat_or_missing(parent)
    if parent_st is not None and not _receipt_stat.S_ISDIR(parent_st.st_mode):
        raise ReportTargetRejected(
            f"回执父目录不是目录(ENOTDIR): {parent}")
    target = parent / raw.name
    if _receipt_lstat_or_missing(target) is not None:
        raise ReportTargetRejected(
            f"回执原末端条目已存在(链接含悬空同样拒绝，不覆盖): {target}")

    protected = [_resolve_target_strict(Path(p)) for p in protect_roots]
    for prot in protected:
        if (target == prot or prot in target.parents
                or parent == prot or prot in parent.parents):
            raise ReportTargetRejected(
                f"回执目标/临时件父目录位于只读输入内: {target} ⊆ {prot}")

    # Preserve the earlier contract for a pre-set fixed .tmp link. The
    # writer itself uses another exclusively created name.
    fixed_tmp = target.with_suffix(target.suffix + '.tmp')
    tmp_st = _receipt_lstat_or_missing(fixed_tmp)
    if tmp_st is not None and _receipt_stat.S_ISLNK(tmp_st.st_mode):
        raise ReportTargetRejected(
            f"固定名临时件已是链接(不跟随、不清理): {fixed_tmp}")
    return target


def _receipt_remove_owned(path: Path, identity: tuple) -> None:
    """只能删除本次创建且文件身份未改变的普通文件；缺失可接受。"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if (not _receipt_stat.S_ISREG(st.st_mode)
            or (st.st_dev, st.st_ino) != tuple(identity)):
        raise OSError(_receipt_errno.ESTALE,
                      '本次对象的文件身份已改变，拒绝清理', str(path))
    os.unlink(path)


def _atomic_write_receipt(path: Path, payload: dict,
                          owned_id: tuple | None = None) -> tuple:
    """只创建最终结果；更新仅限调用方传入的本次候选所有权。

    路径必须来自共享准入的 confirmed。临时件只有在 os.open 的
    O_EXCL 创建实际成功后才取得清理责任；包装/写入/flush/fsync/
    close/发布失败分别保留。清理失败不遮盖初始错误。若发布后
    清理失败，尝试撤下本次发布且身份仍一致的候选，避免遗留可被
    误读为成功的本次回执；绝不回滚/删除其他调用的既有目标。
    """
    path = Path(path)
    tmp = None
    fd = None
    stream = None
    temp_created = False
    temp_id = None
    published = False
    primary = None
    cleanup_errors = []

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.{stamp}.tmp')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(tmp, flags, 0o600)
        temp_created = True  # ownership starts HERE, never at name choice
        st = os.fstat(fd)
        temp_id = (st.st_dev, st.st_ino)
        stream = os.fdopen(fd, 'w', encoding='utf-8')
        fd = None  # successfully transferred descriptor ownership
        stream.write(json.dumps(payload, ensure_ascii=False, indent=1))
        stream.flush()
        os.fsync(stream.fileno())
    except BaseException as exc:
        primary = exc
    finally:
        # Do not let a close error replace a write/fsync error.
        if stream is not None:
            try:
                stream.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if fd is not None:
            try:
                os.close(fd)
            except BaseException as exc:
                cleanup_errors.append(exc)

    if primary is None and not cleanup_errors:
        try:
            if owned_id is None:
                os.link(tmp, path)  # final-name collision never replaces it
            else:
                st = os.lstat(path)
                if (not _receipt_stat.S_ISREG(st.st_mode)
                        or (st.st_dev, st.st_ino) != tuple(owned_id)):
                    raise OSError(_receipt_errno.ESTALE,
                                  '回执目标不属于本次候选，拒绝替换', str(path))
                os.replace(tmp, path)
            published = True
        except BaseException as exc:
            primary = exc

    if temp_created:
        if temp_id is None:
            # Creation succeeded but identity capture failed: retaining an
            # explicitly unconfirmed temporary is safer than deleting an
            # unverified pathname. The primary fstat error is kept.
            cleanup_errors.append(OSError(
                _receipt_errno.ESTALE, '无法确认临时件身份，未删除', str(tmp)))
        else:
            try:
                _receipt_remove_owned(tmp, temp_id)
            except BaseException as exc:
                cleanup_errors.append(exc)

    if primary is not None or cleanup_errors:
        if published and temp_id is not None:
            try:
                _receipt_remove_owned(path, temp_id)
                published = False
            except BaseException as exc:
                cleanup_errors.append(exc)
        details = []
        if primary is not None:
            details.append(f'initial={type(primary).__name__}: {primary}')
        details.extend(f'cleanup={type(e).__name__}: {e}' for e in cleanup_errors)
        message = (f'回执写入未完成: {path}; ' + '; '.join(details)
                   + f'; temporary={tmp}; candidate_still_published={published}')
        # Preserve process-level interrupts, but still perform owned cleanup.
        if primary is not None and not isinstance(primary, Exception):
            if cleanup_errors and hasattr(primary, 'add_note'):
                primary.add_note(message)
            raise primary
        for exc in cleanup_errors:
            if not isinstance(exc, Exception):
                if hasattr(exc, 'add_note'):
                    exc.add_note(message)
                raise exc
        err = ReceiptWriteError(
            message, primary_error=primary, cleanup_errors=cleanup_errors,
            temporary_path=tmp, published_path=path if published else None)
        raise err from (primary if primary is not None else cleanup_errors[0])
    return temp_id
