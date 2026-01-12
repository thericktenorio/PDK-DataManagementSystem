from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from django.conf import settings

from .types import FileMeta, ParseJob


def _sha256_file(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _enforece_size(path: Path) -> None:
    max_bytes = int(settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"File exceeds max upload size: {size} > {max_bytes} bytes "
            f"({settings.MAX_UPLOAD_SIZE_MB} MB)"
        )


def _enforce_extension(path: Path) -> None:
    if path.suffix.lower() not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {path.suffix}")


def _virus_scan_stub(path: Path) -> None:
    """
    MVP placeholder. Hook here for ClamAV or external scanner.
    Raise ValueError if 'infected' is detected (simulated via filename flag).
    """
    if "EICAR" in path.name.upper():
        raise ValueError("Virus scan failed: EICAR signature stub.")


def ingest_local_file(input_path: Path, template_key: str | None = None) -> ParseJob:
    """
    Validates and stores a local file into /data/incoming, returning a ParseJob.
    """
    input_path = input_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    _enforce_extension(input_path)
    _enforece_size(input_path)
    _virus_scan_stub(input_path)

    # Copy to incoming with a stable, collision-free name: {uuid}.pdf
    job_id = uuid.uuid4().hex
    stored_name = f"{job_id}{input_path.suffix.lower()}"
    destination = Path(settings.INCOMING_DIR) / stored_name
    shutil.copy2(input_path, destination)

    sha = _sha256_file(destination)
    meta = FileMeta(
        original_name=input_path.name,
        stored_path=destination,
        size_bytes=destination.stat().st_size,
        sha256=sha,
    )
    job = ParseJob(job_id=job_id, template_key=template_key, file=meta)
    job.ensure_outputs_dir()
    return job
