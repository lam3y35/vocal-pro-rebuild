"""Checksum-verified, resumable, atomic model-weight installer for VocalPro.

Demucs checkpoint file names are ``<signature>-<sha256[:8]>.th``; the 8 hex chars are the first bytes of the
file's SHA-256 (this is what ``torch.hub.load_state_dict_from_url(check_hash=True)`` verifies). This module makes
the install step explicit and failure-safe:

* download to ``<file>.part`` (HTTP Range resume after a dropped connection),
* verify SHA-256 prefix (or a full SHA-256 when given) BEFORE the atomic rename,
* on checksum mismatch delete the partial file (never leave a corrupt checkpoint in the cache),
* on network loss keep ``.part`` for resume and raise a structured ``ModelInstallError``.

CLI:  python -m vocalpro_worker.model_installer --list | --verify | <model> [<model> ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

CHUNK = 1 << 20


class ModelInstallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def expected_prefix_from_name(filename: str) -> Optional[str]:
    """``955717e8-8726e21a.th`` -> ``8726e21a``."""
    stem = Path(filename).stem
    if "-" in stem:
        tail = stem.rsplit("-", 1)[1]
        if len(tail) >= 6 and all(c in "0123456789abcdef" for c in tail):
            return tail
    return None


def download_verified(
    url: str,
    dest: Path,
    expected_sha256: Optional[str] = None,
    progress: Optional[Callable[[int, Optional[int]], None]] = None,
    timeout: float = 30.0,
) -> Path:
    """Download ``url`` to ``dest`` with resume + checksum verification + atomic rename."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = (expected_sha256 or expected_prefix_from_name(dest.name) or "").lower()
    if dest.exists() and (not expected or sha256_file(dest).startswith(expected)):
        return dest  # already installed and valid
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0

    req = urllib.request.Request(url, headers={"User-Agent": "VocalPro-installer/1.0"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https URL from pinned list / local test server
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and part.exists():  # already complete on the server side
            resp = None
        else:
            raise ModelInstallError("DOWNLOAD_HTTP", f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelInstallError("NETWORK_LOST", f"Cannot reach {url}: {exc}") from exc

    if resp is not None:
        with resp:
            status = getattr(resp, "status", 200)
            total_hdr = resp.headers.get("Content-Length")
            total = int(total_hdr) + (have if status == 206 else 0) if total_hdr else None
            mode = "ab" if (have and status == 206) else "wb"
            if mode == "wb":
                have = 0
            written = have
            try:
                with part.open(mode) as f:
                    while True:
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        written += len(block)
                        if progress:
                            progress(written, total)
            except OSError as exc:
                import errno

                if getattr(exc, "errno", None) == errno.ENOSPC:
                    part.unlink(missing_ok=True)
                    raise ModelInstallError("DISK_FULL", f"No space left while writing {part}") from exc
                raise ModelInstallError("NETWORK_LOST", f"Connection lost after {written} bytes: {exc}") from exc
            except Exception as exc:  # http.client.IncompleteRead etc.
                raise ModelInstallError("NETWORK_LOST", f"Connection lost after {written} bytes: {exc}") from exc
            if total is not None and written < total:
                raise ModelInstallError("NETWORK_LOST", f"Short read: {written}/{total} bytes (kept .part for resume)")

    actual = sha256_file(part)
    if expected and not actual.startswith(expected):
        part.unlink(missing_ok=True)
        raise ModelInstallError("CHECKSUM_MISMATCH", f"{dest.name}: sha256 {actual[:16]}... != expected {expected}")
    os.replace(part, dest)
    return dest


def checkpoints_dir() -> Path:
    if os.environ.get("VOCALPRO_MODELS_DIR"):
        p = Path(os.environ["VOCALPRO_MODELS_DIR"])
        if (p / "checkpoints").is_dir():
            return p / "checkpoints"
        return p
    try:
        import torch

        return Path(torch.hub.get_dir()) / "checkpoints"
    except Exception:
        return Path.home() / ".cache" / "torch" / "hub" / "checkpoints"


def model_files(model_name: str) -> list[tuple[str, str]]:
    """(filename, url) for every checkpoint needed by a Demucs model name (bags expanded)."""
    import yaml
    from demucs import pretrained

    files = pretrained._parse_remote_files(pretrained.REMOTE_ROOT / "files.txt")  # sig -> url
    yaml_path = pretrained.REMOTE_ROOT / f"{model_name}.yaml"
    sigs = [model_name]
    if yaml_path.exists():
        sigs = list(yaml.safe_load(yaml_path.read_text())["models"])
    out: list[tuple[str, str]] = []
    for sig in sigs:
        url = files.get(sig)
        if url is None:
            raise ModelInstallError("UNKNOWN_MODEL", f"No download URL for signature {sig} of {model_name}")
        out.append((url.rsplit("/", 1)[1], url))
    return out


def install_model(model_name: str, target: Optional[Path] = None, progress=None) -> list[Path]:
    target = target or checkpoints_dir()
    return [download_verified(url, target / name, progress=progress) for name, url in model_files(model_name)]


def verify_installed(model_name: str, target: Optional[Path] = None) -> dict[str, str]:
    target = target or checkpoints_dir()
    report: dict[str, str] = {}
    for name, _ in model_files(model_name):
        p = target / name
        if not p.exists():
            report[name] = "MISSING"
        else:
            report[name] = "OK" if sha256_file(p).startswith(expected_prefix_from_name(name) or "") else "CORRUPT"
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="vocalpro_worker.model_installer")
    ap.add_argument("models", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--target", type=Path)
    a = ap.parse_args(argv)
    names = a.models or ["htdemucs"]
    try:
        if a.list:
            for n in names:
                print(json.dumps({n: [f for f, _ in model_files(n)]}))
            return 0
        for n in names:
            if a.verify:
                print(json.dumps({n: verify_installed(n, a.target)}))
            else:
                paths = install_model(n, a.target)
                print(json.dumps({n: [{"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size} for p in paths]}))
    except ModelInstallError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
