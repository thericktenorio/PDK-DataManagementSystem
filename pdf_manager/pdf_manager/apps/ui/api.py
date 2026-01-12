from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from pdf_manager.apps.core.models import Document, ParseJob
from pdf_manager.apps.parser.exceptions import ParserError
from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.types import PageTag, TaggedPage


# Structural MetaData Helper
def _outline_titles_for(tp: TaggedPage) -> list[str]:
    """
    Adapter between the old tp.page.outliens: list[str] world and the new
    tp.page.outline: OutlineInfo | None

    Returns a list of outline titles for this page (currently at most 1),
    or an empty list if no outline info is present.
    """
    outline = getattr(tp.page, "outline", None)
    title = getattr(outline, "title", None) if outline is not None else None
    if title:
        return [str(title)]
    return []


# PATH HELPERS
def _data_dir(path_attr: str, fallback: str) -> str:
    """
    Use settings.<path_attr> if present; otherwise fall back to BASE_DIR/data/<fallback>.
    """
    value = getattr(settings, path_attr, None)
    if value:
        return str(value)
    # Fallback mirrors your repo structure: <project-root>/data/<fallback>
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir is None:
        raise RuntimeError("settings.BASE_DIR is not defined")
    return os.path.join(base_dir, "data", fallback)


INCOMING_DIR = str(settings.INCOMING_DIR)
OUTPUTS_DIR = str(settings.OUTPUTS_DIR)


os.makedirs(INCOMING_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)


# HELPER MEHTODS FOR SERIALIZAITON
def _to_jsonable(o: Any) -> Any:
    if isinstance(o, Enum):
        return o.value  # or str(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)  # or str(o) if you need exact precision carried through
    if isinstance(o, Path):
        return str(o)
    if is_dataclass(o) and not isinstance(o, type):
        return {k: _to_jsonable(v) for k, v in asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_to_jsonable(v) for v in o]
    return o


def _enum_to_json(v):
    """Return JSON-safe value for enums"""
    return v.value if isinstance(v, Enum) else v


def _tags_to_json(
    tags: Iterable[PageTag | Enum | str | None], *, expose: Literal["label", "full"] = "label"
) -> list[str] | list[dict[str, Any]]:
    if expose == "label":
        out: list[str] = []
        for t in tags or []:
            if t is None:
                continue
            if isinstance(t, PageTag):
                out.append(str(t.label))
            elif isinstance(t, Enum):
                out.append(str(t.value))
            else:
                out.append(str(t))
        return out

    # expose == "full"
    out_full: list[dict[str, Any]] = []
    for t in tags or []:
        if t is None:
            continue
        if isinstance(t, PageTag):
            out_full.append(
                {
                    "label": str(t.label),
                    "score": float(getattr(t, "score", 1.0)),
                    "meta": getattr(t, "meta", None),
                }
            )
        elif isinstance(t, Enum):
            out_full.append({"label": str(t), "score": 1.0, "meta": None})
    return out_full


def _ui_status(status_enum: str) -> str:
    """
    Map internal enum to UI-friendly status.
    PENDING -> processing, SUCCESS -> done, FAILED -> error
    """
    s = (status_enum or "").upper()
    if s == "PENDING":
        return "processing"
    if s == "SUCCESS":
        return "done"
    if s == "FAILED":
        return "error"
    return s.lower() or "processing"


def _result_to_json(result) -> dict[str, Any]:
    """
    Convert Parseresult to a JSON-serializable dict.
    Only expose page tags (not raw page objects).
    """
    payload = {
        "job_id": str(result.job_id),
        "status": "done",
        "fields": result.extracted_fields,  # will be sanitized below
        "pages": [
            {
                "tags": _tags_to_json(getattr(tp, "tags", []), expose="label"),
                "outlines": _outline_titles_for(tp),
                "section_key": getattr(tp, "section_key", None),
            }
            for tp in (result.tagged_pages or [])
        ],
        "message": result.message,
        # MAIN cleaned/reordered packet (unchanged semantics)
        "output_pdf_path": (str(result.output_subset_path) if result.output_subset_path else None),
        # Signature Packet
        "signature_pdf_path": (
            str(result.signature_packet_path)
            if getattr(result, "signature_packet_path", None)
            else None
        ),
        # Payment Voucher Packet
        "payment_voucher_pdf_path": (
            str(result.payment_voucher_packet_path)
            if getattr(result, "payment_voucher_packet_path", None)
            else None
        ),
    }
    return _to_jsonable(payload)


def _detail_payload_from_job(job) -> dict[str, Any]:
    """
    Build a detail payload from a persisted ParseJob.
    """
    return {
        "fields": job.result_fields or {},
        "pages": job.result_pages or [],
        "message": job.result_message or "",
        "output_pdf_path": job.output_pdf_path,
        "signature_pdf_path": job.signature_pdf_path,
        "payment_voucher_pdf_path": job.payment_voucher_pdf_path,
    }


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as r:
        for chunk in iter(lambda: r.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# HELPER TO COLLECT ALL OUTPUT FILES
def _job_output_files(job: ParseJob) -> list[str]:
    """
    Return a list of existing PDF paths for this parse job
    - main output pdf
    - signature pdf
    - payment voucher pdf
    """
    paths: list[str] = []
    for path in (job.output_pdf_path, job.signature_pdf_path, job.payment_voucher_pdf_path):
        if path and os.path.exists(path):
            paths.append(path)

    return paths


# ENDPOINTS
@require_http_methods(["POST"])
def upload_api(request):
    """
    Receives PDF (multipart/form-data, field name 'file'),
    persists ParseJob, kicks off synchronous parse for MVP,
    and returns {job_id}.
    @ Later phase, swap to async (Celery/RQ) without changing the UI contract.
    """
    if "file" not in request.FILES:
        return HttpResponseBadRequest("No file provided")

    f = request.FILES["file"]
    if not f.name.lower().endswith(".pdf"):
        return HttpResponseBadRequest("Only .pdf files are allowed")

    '''
    # ----------FALLBACK PATHWAY (no DB)----------
    if ParseJob is None or Document is None:
        try:
            # write to unique temp file then let the facade handle ingestion + pipeline
            tmp_fd, tmp_path = tempfile.mkstemp(dir=INCOMING_DIR, prefix="upload_", suffix=".pdf")
            os.close(tmp_fd)
            with open(tmp_path, "wb") as dest:
                for chunk in f.chunks():
                    dest.write(chunk)

            # facade.run() used to perform ingestion + pipeline
            facade = PDFParserFacade()
            result = facade.run(tmp_path)  # Expects: fields, pages(tags), message, output_pdf_path
            """
            UI will immediately redirect to results page by "job_id" -
            if no DB job, return short-lived token or echo fields inline.
            for simplicity, fabricate transient id '000000-000-000-0000000'
            """

            # Return a transient, non-persisted "job"
            payload = _result_to_json(result)
            payload = _to_jsonable(payload)
            # payload["job_id"] = "00000000-0000-0000-0000-000000000000"
            return JsonResponse(payload)
        except ParserError as e:
            return JsonResponse({"error": str(e)}, status=400)
    '''

    # ---------- DB-BACKED Path ----------
    # stage 1: write unique temp file and compute checksum
    tmp_fd, temp_path = tempfile.mkstemp(dir=INCOMING_DIR, prefix="upload_", suffix=".pdf")
    os.close(tmp_fd)
    try:
        with open(temp_path, "wb") as dest:
            for chunk in f.chunks():
                dest.write(chunk)

        checksum = _sha256_file(temp_path)

        with transaction.atomic():
            doc, _ = Document.objects.get_or_create(
                checksum=checksum,
                defaults={"filename": f.name},
            )
            job = ParseJob.objects.create(
                document=doc,
                status=ParseJob.Status.PENDING,
                started_at=timezone.now(),
            )

        # normalize incoming file name to {job_uuid}.pdf
        in_path = os.path.join(INCOMING_DIR, f"{job.job_uuid}.pdf")
        if temp_path != in_path:
            os.replace(temp_path, in_path)

        # stage 2: run pipeline simultaneously
        try:
            facade = PDFParserFacade()
            result = facade.parse(job_id=job.job_uuid, file_path=in_path)

            job.result_fields = _to_jsonable(result.extracted_fields)
            job.result_pages = _to_jsonable(
                [
                    {
                        "tags": _tags_to_json(getattr(tp, "tags", []), expose="label"),
                        "outlines": _outline_titles_for(tp),
                        "section_key": getattr(tp, "section_key", None),
                    }
                    for tp in (result.tagged_pages or [])
                ]
            )
            job.result_message = _to_jsonable(result.message)

            # MAIN cleaned/reordered packet
            job.output_pdf_path = (
                str(result.output_subset_path) if result.output_subset_path else None
            )

            # Signature Requests packet
            job.signature_pdf_path = (
                str(result.signature_packet_path)
                if getattr(result, "signature_packet_path", None)
                else None
            )

            # Payment Voucher packet
            job.payment_voucher_pdf_path = (
                str(result.payment_voucher_packet_path)
                if getattr(result, "payment_voucher_packet_path", None)
                else None
            )

            job.status = ParseJob.Status.SUCCESS
            job.finished_at = timezone.now()
            job.save(
                update_fields=[
                    "result_fields",
                    "result_pages",
                    "result_message",
                    "output_pdf_path",
                    "signature_pdf_path",
                    "payment_voucher_pdf_path",
                    "status",
                    "finished_at",
                    "updated_at",
                ]
            )

            return JsonResponse({"job_id": str(job.job_uuid), "status": "done"})

        except ParserError as e:
            job.status = ParseJob.Status.FAILED
            job.result_message = str(e)
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "result_message", "finished_at", "updated_at"])
            return JsonResponse(
                {"job_id": str(job.job_uuid), "status": "error", "error": str(e)}, status=400
            )

    finally:
        # clean up only if the temp file still exists (ex. temp file never renamed)
        try:
            if os.path.exists(temp_path) and os.path.basename(temp_path).startswith("upload_"):
                os.remove(temp_path)
        except Exception:
            pass


@require_http_methods(["GET", "HEAD"])
def job_status_api(request, job_id):
    """
    gives job status summary. if called w/ ?detail=1 and job is 'done'
    then include the persisted fields/pages/message/output path fo Results page
    can render w/o extra round trips.
    """
    if ParseJob is None:
        # no db jobs - nothing to poll in MVP fallback
        return JsonResponse({"status": "done"})

    try:
        job = ParseJob.objects.select_related("document").get(job_uuid=job_id)
    except ParseJob.DoesNotExist as err:
        raise Http404("Job not found") from err

    detail = request.GET.get("detail") == "1"

    payload: dict[str, Any] = {
        "job_id": str(job.job_uuid),
        "status": _ui_status(job.status),
        "filename": job.document.filename,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }

    if detail and job.status == ParseJob.Status.SUCCESS:
        payload.update(_detail_payload_from_job(job))

    return JsonResponse(payload)


"""
CURRENTLY : You need to click a button to download the pdf packet (main packet only).
TODO : 3 documents should be downloaded (signatures, main & payment vouchers if applicable)
TODO : these docs should download AUTOMATICALLY, no need to click a button
TODO : refactor job_output_api()
"""


@require_http_methods(["GET", "HEAD"])
def job_output_api(request, job_id):
    """
    streams saved subset PDF for a completed job (by job_uuid).
    """
    if ParseJob is None:
        return HttpResponseBadRequest("Job output unavailable without DB job tracking.")

    try:
        job = ParseJob.objects.get(job_uuid=job_id)
    except ParseJob.DoesNotExist as err:
        raise Http404("Job not found") from err

    if job.status != ParseJob.Status.SUCCESS:
        return HttpResponseBadRequest("Job not completed")

    if job.output_pdf_path and os.path.exists(job.output_pdf_path):
        return FileResponse(
            open(job.output_pdf_path, "rb"),  # noqa: SIM115 (FileResponse manages the file handle)
            as_attachment=True,
            filename=os.path.basename(job.output_pdf_path),
        )

    return HttpResponseBadRequest("No output PDF available")


# API TO RETURN ALL OUTPUT PDFs
@require_http_methods(["GET", "HEAD"])
def job_outputs_api(request, job_id):
    """
    Download ALL available PDFs for a completed job
    """
    if ParseJob is None:
        return HttpResponseBadRequest("Job output unavailable without DB job tracking.")

    try:
        job = ParseJob.objects.get(job_uuid=job_id)
    except ParseJob.DoesNotExist as err:
        raise Http404("Job not found") from err

    if job.status != ParseJob.Status.SUCCESS:
        return HttpResponseBadRequest("Job not completed")

    paths = _job_output_files(job)
    if not paths:
        return HttpResponseBadRequest("No PDFs available as output")

    # HEAD: report that outputs exist or don't exist
    if request.method == "HEAD":
        return HttpResponse(status=200)

    # Stream file if only individual file present
    if len(paths) == 1:
        single_path = paths[0]
        return FileResponse(
            open(single_path, "rb"),  # noqa: SIM115
            as_attachment=True,
            filename=os.path.basename(single_path),
        )

    # create in memory ZIP for mutli-file outputs
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zf:
        for p in paths:
            # store w/ basename in zip
            zf.write(p, arcname=os.path.basename(p))

    buffer.seek(0)
    zip_filename = f"job_{job.job_uuid}_outputs.zip"

    response = FileResponse(
        buffer,
        as_attachment=True,
        filename=zip_filename,
    )
    response["Content-Type"] = "application/zip"
    return response
