"""Shared path safety, Windows reparse-point, and safe cleanup guards for extract_assets."""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

_NON_FS_PROVIDER_RE = re.compile(r"^[A-Za-z0-9_.-]+::")
_UNC_SCHEME_RE = re.compile(r"^(?:file://[^/]|(?:Microsoft\.PowerShell\.Core\\)?FileSystem::(?:\\\\|//)|\\\\|//)", re.IGNORECASE)
_DEFAULT_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_UNSAFE_OUT_FILENAME_CHARS_RE = re.compile(r'[\x00-\x1f\x7f$`|&;^%#<>"*?:]+')
_MAX_OUTPUT_STEM_LEN = 150


def _assert_no_ntfs_ads(raw_path: str, label: str) -> None:
    """Reject Windows NTFS Alternate Data Streams (colons after the drive letter)."""
    t = raw_path.strip()
    if not t:
        return
    low = t.lower()
    if low.startswith(("http://", "https://")):
        return
    if low.startswith("filesystem::"):
        t = t[len("filesystem::") :]
        low = t.lower()
    elif low.startswith("microsoft.powershell.core\\filesystem::"):
        t = t[len("microsoft.powershell.core\\filesystem::") :]
        low = t.lower()
    if low.startswith("file:///"):
        parsed = urlparse(t)
        t = unquote(parsed.path or "")
        if len(t) >= 3 and t[0] == "/" and t[2] == ":":
            t = t[1:]
    # Strip legitimate single-letter Windows drive prefix (e.g. C:\...)
    body = t[2:] if (len(t) >= 2 and t[0].isalpha() and t[1] == ":") else t
    if ":" in body:
        raise ValueError(f"Refusing NTFS Alternate Data Stream / colon in path for {label}: {raw_path}")


def is_windows_reserved_name(segment: str) -> bool:
    """Return True when `segment` ends with '.' or matches a Windows reserved device name."""
    if not segment:
        return False
    base_stem = segment.split(".", 1)[0].rstrip(" ").upper()
    return segment.endswith(".") or base_stem in _WINDOWS_RESERVED_DEVICE_NAMES


def sanitize_output_filename(path_obj: Path) -> tuple[Path, bool]:
    """Sanitize the leaf filename of an output path while preserving its parent directory and benign Unicode."""
    orig_name = path_obj.name
    if not orig_name:
        return path_obj, False

    raw_suffix = path_obj.suffix
    raw_stem = path_obj.stem if raw_suffix else orig_name

    clean_suffix = _UNSAFE_OUT_FILENAME_CHARS_RE.sub("", raw_suffix).rstrip(" .")
    if clean_suffix and not clean_suffix.startswith("."):
        clean_suffix = "." + clean_suffix

    stem = _UNSAFE_OUT_FILENAME_CHARS_RE.sub("_", raw_stem)
    stem = re.sub(r"_+", "_", stem).strip(" .")
    if not stem or stem.strip("_") == "":
        stem = "document"
    if len(stem) > _MAX_OUTPUT_STEM_LEN:
        stem = stem[:_MAX_OUTPUT_STEM_LEN].rstrip(" .") or "document"

    base_first = stem.split(".", 1)[0].rstrip(" ").upper()
    if base_first in _WINDOWS_RESERVED_DEVICE_NAMES:
        stem = f"doc_{stem}"
        if len(stem) > _MAX_OUTPUT_STEM_LEN:
            stem = stem[:_MAX_OUTPUT_STEM_LEN].rstrip(" .")

    new_name = f"{stem}{clean_suffix}".rstrip(" .")
    if not new_name:
        new_name = "document" + clean_suffix
    changed = new_name != orig_name
    return (path_obj.with_name(new_name) if changed else path_obj), changed


def get_repo_root() -> Path:
    """Resolve workspace/repository root containing tools/ regardless of frozen vs script execution."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent.parent
    return Path(__file__).resolve().parent.parent.parent


def get_tools_dir() -> Path:
    """Resolve tools/ directory containing reader_shell.html."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


def _norm_abs_str(raw_path: str | Path) -> str:
    """Normalize local path string without dereferencing symlinks or junctions."""
    return os.path.abspath(str(raw_path)).rstrip("\\/")


def assert_local_no_unc_path(path_value: str | Path | None, param_name: str = "Path") -> None:
    """Reject UNC/network paths and remote file:// URIs."""
    if path_value is None:
        return
    t = str(path_value).strip()
    if not t:
        return
    if _UNC_SCHEME_RE.match(t):
        raise ValueError(f"Refusing UNC/network path for {param_name}: {path_value}")
    if ntpath.splitdrive(t)[0].startswith(("\\\\", "//")):
        raise ValueError(f"Refusing UNC/network path for {param_name}: {path_value}")
    if t.lower().startswith("file://"):
        parsed = urlparse(t)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raise ValueError(f"Refusing UNC/network path for {param_name}: {path_value}")
    _assert_no_ntfs_ads(t, param_name)


def file_uri_to_local_path(uri: str) -> str:
    """Convert a local file:/// URI to an OS path, blocking remote UNC hosts."""
    assert_local_no_unc_path(uri, "TranscriptMediaUri")
    if not uri.lower().startswith("file:///"):
        return uri
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path or "")
    if sys.platform == "win32" and len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    local = raw_path.replace("/", os.sep)
    assert_local_no_unc_path(local, "TranscriptMediaUri")
    return local


def is_reparse_point(path: Path | str) -> bool:
    """Return True for symlinks or Windows junctions while ignoring OS cloud-sync placeholders."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    if sys.platform == "win32":
        attrs = getattr(st, "st_file_attributes", 0)
        file_attr_reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        if (attrs & file_attr_reparse) == 0:
            return False
        tag = getattr(st, "st_reparse_tag", 0)
        sym_tag = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
        junc_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
        return tag in (sym_tag, junc_tag)
    return False


def _validate_non_fs_prefix(raw_path: str, label: str) -> None:
    if _NON_FS_PROVIDER_RE.match(raw_path) and not raw_path.lower().startswith("filesystem::"):
        raise ValueError(f"Refusing non-filesystem path for {label}: {raw_path}")
    if not raw_path.lower().startswith(("file://", "http://", "https://")) and re.match(r"^[A-Za-z]{2,}:", raw_path):
        raise ValueError(f"Refusing non-filesystem path for {label}: {raw_path}")


def assert_safe_output_path(
    target_path: str | Path | None,
    label: str = "OutputPath",
    is_directory: bool = False,
) -> Path | None:
    """Block symlinks/junctions on output directory/file and workspace/temp ancestors."""
    if target_path is None:
        return None
    raw = str(target_path).strip()
    if not raw:
        return None
    _validate_non_fs_prefix(raw, label)
    assert_local_no_unc_path(raw, label)

    raw_body = raw[2:] if (len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":") else raw
    for seg in re.split(r"[\\/]+", raw_body):
        if seg and seg not in (".", "..") and is_windows_reserved_name(seg):
            raise ValueError(f"Refusing reserved/invalid Windows filename for {label}: {raw}")

    norm_target = _norm_abs_str(raw)
    tail_target = ntpath.splitdrive(norm_target)[1]
    for seg in re.split(r"[\\/]+", tail_target):
        if seg and is_windows_reserved_name(seg):
            raise ValueError(f"Refusing reserved/invalid Windows filename for {label}: {norm_target}")
    anchors: list[str] = []
    for cand in (get_repo_root(), Path.cwd(), Path(tempfile.gettempdir())):
        na = _norm_abs_str(cand)
        if na and na.lower() not in [a.lower() for a in anchors]:
            anchors.append(na)

    matched_anchor = ""
    norm_lower = norm_target.lower()
    for a in anchors:
        prefix = a.lower() + os.sep
        if norm_lower.startswith(prefix) and len(a) > len(matched_anchor):
            matched_anchor = a

    if matched_anchor:
        rel = norm_target[len(matched_anchor) :].lstrip("\\/")
        probe = matched_anchor
        for seg in re.split(r"[\\/]+", rel):
            if not seg:
                continue
            probe = os.path.join(probe, seg)
            if os.path.lexists(probe) and is_reparse_point(probe):
                raise ValueError(f"Refusing to write through symlink/junction (ReparsePoint) for {label}: {probe}")
    else:
        cursor = norm_target
        drive_root = _norm_abs_str(ntpath.splitdrive(norm_target)[0] + os.sep)
        while cursor and cursor.lower() != drive_root.lower():
            if os.path.lexists(cursor) and is_reparse_point(cursor):
                raise ValueError(f"Refusing to write through symlink/junction (ReparsePoint) for {label}: {cursor}")
            parent = os.path.dirname(cursor).rstrip("\\/")
            if not parent or parent == cursor:
                break
            cursor = parent

    if os.path.lexists(norm_target):
        if is_reparse_point(norm_target):
            raise ValueError(f"Refusing to overwrite symlink/junction (ReparsePoint) for {label}: {norm_target}")
        is_dir = os.path.isdir(norm_target)
        if is_directory and not is_dir:
            raise ValueError(f"Expected directory path for {label}, found file: {norm_target}")
        if not is_directory and is_dir:
            raise ValueError(f"Expected file path for {label}, found directory: {norm_target}")

    return Path(norm_target)


def resolve_safe_out_directory(
    out_dir: str | Path,
    param_name: str = "-OutDir",
    create: bool = False,
) -> Path:
    """Validate output directory against UNC/reparse points, optionally creating it."""
    raw = str(out_dir or "")
    if not raw.strip():
        raise ValueError(f"{param_name} cannot be empty.")
    assert_local_no_unc_path(raw, param_name)
    out_full = assert_safe_output_path(raw, label=param_name, is_directory=True)
    assert out_full is not None
    if out_full.exists():
        with os.scandir(out_full) as it:
            for entry in it:
                if is_reparse_point(entry.path):
                    raise ValueError(
                        f"Refusing to write into {param_name} containing symlink/junction: {entry.path}"
                    )
    elif create:
        out_full.mkdir(parents=True, exist_ok=True)
    return out_full


def resolve_safe_sub_image_path(base_dir: Path, relative_src: str) -> Path | None:
    """Resolve relative local <img> src strictly inside `base_dir`, blocking traversal and reparse points."""
    trimmed = (relative_src or "").strip()
    if not trimmed:
        raise ValueError("Empty local image src is not allowed.")
    if trimmed.startswith(("/", "\\")) or ":" in trimmed:
        raise ValueError(f"Path traversal / unsafe image src blocked: {relative_src}")

    rel_win = trimmed.replace("/", os.sep)
    if ntpath.isabs(rel_win):
        raise ValueError(f"Path traversal / rooted image src blocked: {relative_src}")

    norm_base = _norm_abs_str(base_dir)
    norm_target = _norm_abs_str(os.path.join(norm_base, rel_win))
    if not norm_target.lower().startswith(norm_base.lower() + os.sep):
        raise ValueError(f"Path traversal blocked: image src '{relative_src}' escapes base directory '{norm_base}'")

    if os.path.lexists(norm_base) and is_reparse_point(norm_base):
        raise ValueError(f"Blocked reparse point (symlink/junction) at image base directory: {norm_base}")

    rel = norm_target[len(norm_base) :].lstrip("\\/")
    probe = norm_base
    for seg in re.split(r"[\\/]+", rel):
        if not seg:
            continue
        probe = os.path.join(probe, seg)
        if not os.path.lexists(probe):
            return None
        if is_reparse_point(probe):
            raise ValueError(f"Blocked reparse point (symlink/junction) in image path: {probe}")

    if not os.path.lexists(norm_target):
        return None
    if os.path.isdir(norm_target):
        raise ValueError(f"Expected image file, found directory: {norm_target}")
    return Path(norm_target)


def _blocked_system_roots() -> set[str]:
    vals: set[str] = set()
    for env_key in ("USERPROFILE", "PUBLIC", "WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
        val = os.environ.get(env_key, "").strip()
        if val:
            vals.add(_norm_abs_str(val).lower())
    return vals


def get_allowed_crop_input_roots(
    json_dir: Path,
    dest_dir: Path,
    repo_root: Path | None = None,
) -> list[str]:
    """Return canonical workspace/input roots allowed for source page_png images."""
    blocked = _blocked_system_roots()
    root = repo_root if repo_root is not None else get_repo_root()
    candidates = [root, json_dir, dest_dir, Path.cwd()]

    roots: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        norm = _norm_abs_str(cand)
        drive_root = _norm_abs_str(ntpath.splitdrive(norm)[0] + os.sep)
        if not norm or norm.lower() == drive_root.lower():
            continue
        if norm.lower() in blocked:
            continue
        if norm.lower() not in seen:
            seen.add(norm.lower())
            roots.append(norm)
    return roots


def resolve_safe_crop_input_file(raw_page_path: str, allowed_roots: list[str] | list[Path]) -> Path:
    """Validate source crop image stays inside allowed workspace/input roots with no reparse points."""
    if not raw_page_path or not raw_page_path.strip():
        raise ValueError("Missing page_png in crop spec.")
    trimmed = raw_page_path.strip()
    _validate_non_fs_prefix(trimmed, "page_png")
    assert_local_no_unc_path(trimmed, "page_png")
    abs_src = _norm_abs_str(trimmed)

    matched_root = None
    abs_lower = abs_src.lower()
    for r in allowed_roots:
        r_norm = _norm_abs_str(r)
        if abs_lower.startswith(r_norm.lower() + os.sep):
            matched_root = r_norm
            break
    if not matched_root:
        raise ValueError(
            f"Path traversal blocked: page_png '{raw_page_path}' resolves outside allowed directories ({abs_src})"
        )

    if os.path.lexists(matched_root) and is_reparse_point(matched_root):
        raise ValueError(f"Blocked reparse point (symlink/junction) at input root: {matched_root}")

    rel = abs_src[len(matched_root) :].lstrip("\\/")
    probe = matched_root
    for seg in re.split(r"[\\/]+", rel):
        if not seg:
            continue
        probe = os.path.join(probe, seg)
        if not os.path.lexists(probe):
            raise FileNotFoundError(f"Source page PNG not found: {raw_page_path}")
        if is_reparse_point(probe):
            raise ValueError(f"Blocked reparse point (symlink/junction) in page_png path: {probe}")

    if not os.path.isfile(abs_src):
        raise FileNotFoundError(f"Source page PNG not found: {raw_page_path}")
    return Path(abs_src)


def resolve_safe_crop_out_file(dest_dir: Path, out_name: str, invalid_chars: set[str] | None = None) -> Path:
    """Enforce out_name is a bare filename inside `dest_dir` and refuse symlink overwrite."""
    bad_chars = invalid_chars if invalid_chars is not None else _DEFAULT_INVALID_FILENAME_CHARS
    if not out_name or not out_name.strip():
        raise ValueError("Missing out_name in crop spec.")
    name = out_name.strip()
    if (
        name in (".", "..")
        or ntpath.isabs(name)
        or os.path.basename(name) != name
        or any(ord(ch) < 32 or ch in bad_chars for ch in name)
    ):
        raise ValueError(
            f"Path traversal blocked: invalid out_name '{out_name}' (must be a plain filename inside OutDir)"
        )
    base_stem = name.split(".", 1)[0].rstrip(" ").upper()
    if name.endswith(".") or base_stem in _WINDOWS_RESERVED_DEVICE_NAMES:
        raise ValueError(
            f"Path traversal blocked: reserved/invalid Windows filename '{out_name}' (must be a plain filename inside OutDir)"
        )

    norm_dest = _norm_abs_str(dest_dir)
    if os.path.lexists(norm_dest) and is_reparse_point(norm_dest):
        raise ValueError(f"Blocked reparse point (symlink/junction) at OutDir: {norm_dest}")

    out_file = _norm_abs_str(os.path.join(norm_dest, name))
    if not out_file.lower().startswith(norm_dest.lower() + os.sep):
        raise ValueError(f"Path traversal blocked: '{out_name}' resolves outside '{norm_dest}'")

    if os.path.lexists(out_file):
        if is_reparse_point(out_file):
            raise ValueError(f"Refusing to overwrite symlink/reparse point: {out_file}")
        if os.path.isdir(out_file):
            raise ValueError(f"Refusing to overwrite directory with image file: {out_file}")
    return Path(out_file)


def _is_within_system_temp(path_str: str) -> bool:
    """True when `path_str` is the system temp dir or below it (8.3 short names tolerated via samefile)."""
    temp_dirs: list[str] = []
    for cand in (tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", "")):
        if cand and cand.strip() and os.path.isdir(cand) and cand not in temp_dirs:
            temp_dirs.append(cand)
    if not temp_dirs:
        return False
    cursor = _norm_abs_str(path_str)
    while cursor:
        for t in temp_dirs:
            try:
                if os.path.samefile(cursor, t):
                    return True
            except OSError:
                pass
        parent = os.path.dirname(cursor)
        if not parent or parent == cursor:
            break
        cursor = parent
    return False


def get_allowed_work_roots(repo_root: Path | None = None) -> list[str]:
    """Return canonical `work` roots eligible for cleanup.

    Always the workspace `<repo>/work`. A `<CWD>/work` root is only added when CWD lies inside the
    system temp directory (isolated test/sandbox runs), so a drifted CWD can never delete an
    unrelated user folder that happens to be named `work`.
    """
    roots: list[str] = []
    seen: set[str] = set()
    blocked = _blocked_system_roots()

    r_root = _norm_abs_str(repo_root if repo_root is not None else get_repo_root())
    r_drive = _norm_abs_str(ntpath.splitdrive(r_root)[0] + os.sep)
    if r_root and r_root.lower() != r_drive.lower():
        repo_work = _norm_abs_str(os.path.join(r_root, "work"))
        seen.add(repo_work.lower())
        roots.append(repo_work)

    cwd = _norm_abs_str(Path.cwd())
    cwd_drive = _norm_abs_str(ntpath.splitdrive(cwd)[0] + os.sep)
    if cwd and cwd.lower() != cwd_drive.lower() and cwd.lower() not in blocked and _is_within_system_temp(cwd):
        cwd_work = _norm_abs_str(os.path.join(cwd, "work"))
        if cwd_work.lower() not in seen:
            seen.add(cwd_work.lower())
            roots.append(cwd_work)
    return roots


def _assert_no_reparse_points_in_tree(root_work_dir: str, target_dir: str) -> None:
    """Reject symlinks/junctions anywhere from allowed `work` root down through all descendants."""
    rel = target_dir[len(root_work_dir) :].lstrip("\\/")
    segments = [s for s in re.split(r"[\\/]+", rel) if s]

    probe = root_work_dir
    if not os.path.lexists(probe):
        raise FileNotFoundError(f"Missing directory: {probe}")
    if is_reparse_point(probe):
        raise ValueError(f"Refusing to clean reparse point (symlink/junction): {probe}")
    for seg in segments:
        probe = os.path.join(probe, seg)
        if not os.path.lexists(probe):
            raise FileNotFoundError(f"Missing directory: {probe}")
        if is_reparse_point(probe):
            raise ValueError(f"Refusing to clean reparse point (symlink/junction): {probe}")

    queue: list[str] = [target_dir]
    while queue:
        cur = queue.pop(0)
        if is_reparse_point(cur):
            raise ValueError(f"Refusing to clean directory containing symlink/junction: {cur}")
        with os.scandir(cur) as it:
            for entry in it:
                if is_reparse_point(entry.path):
                    raise ValueError(f"Refusing to clean entry because it is a symlink/junction: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    queue.append(entry.path)


def validate_clean_dir(
    target_dir: str | Path | None,
    protected_paths: list[str | Path] | None = None,
    repo_root: Path | None = None,
) -> str | None:
    """Run every `safe_clean_dir` safety check without deleting anything.

    Returns the absolute directory to remove, or None when there is nothing to clean (empty value or
    missing directory). Raises ValueError for an unsafe target. Callers that write output files should
    call this before writing, so a bad `-CleanDir` fails the run while the output folder is still untouched.
    """
    if not target_dir or not str(target_dir).strip():
        return None
    raw = str(target_dir).strip()
    _validate_non_fs_prefix(raw, "-CleanDir")
    assert_local_no_unc_path(raw, "-CleanDir")
    abs_target = _norm_abs_str(raw)

    matched_work_root = None
    target_lower = abs_target.lower()
    for w_root in get_allowed_work_roots(repo_root=repo_root):
        w_lower = w_root.lower()
        if target_lower == w_lower or target_lower.startswith(w_lower + os.sep):
            matched_work_root = w_root
            break
    if not matched_work_root:
        raise ValueError(
            f"Refusing to clean unsafe directory (only 'work' or subdirectories inside 'work\\' are allowed): {abs_target}"
        )

    for p in protected_paths or []:
        if not p:
            continue
        abs_p = _norm_abs_str(p)
        p_lower = abs_p.lower()
        if p_lower == target_lower or p_lower.startswith(target_lower + os.sep):
            raise ValueError(f"Refusing to clean '{abs_target}' because output file '{abs_p}' resides inside it.")

    if not os.path.lexists(abs_target):
        return None
    if is_reparse_point(abs_target):
        raise ValueError(f"Refusing to clean reparse point (symlink/junction): {abs_target}")
    if not os.path.isdir(abs_target):
        raise ValueError(f"Refusing to clean non-directory path: {abs_target}")

    _assert_no_reparse_points_in_tree(matched_work_root, abs_target)
    return abs_target


def safe_clean_dir(
    target_dir: str | Path | None,
    protected_paths: list[str | Path] | None = None,
    repo_root: Path | None = None,
) -> None:
    """Safely remove `work/` or a subdirectory inside `work/`, tolerating cloud/AV file locks with warning."""
    abs_target = validate_clean_dir(target_dir, protected_paths=protected_paths, repo_root=repo_root)
    if abs_target is None:
        return

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            shutil.rmtree(abs_target)
            last_err = None
            break
        except OSError as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.4)

    if not os.path.lexists(abs_target):
        print(f"Cleaned temp directory -> {abs_target}")
    elif last_err is not None:
        print(
            f"WARNING: Could not fully clean temp directory (locked by sync/antivirus?): {abs_target} ({last_err})",
            file=sys.stderr,
        )
