"""
HTTP client for pdf_manager parser API (Phase 4.2).

Contract: POST /api/upload/ → GET /api/jobs/{id}/?detail=1
"""
from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import requests
from django.conf import settings


class PDFManagerError(Exception):
    """Raised when pdf_manager returns an error or is unreachable."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class PDFManagerClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ):
        self.base_url = (base_url or settings.PDF_MANAGER_BASE_URL).rstrip("/")
        self.timeout = timeout_seconds or settings.PDF_MANAGER_TIMEOUT_SECONDS
        self.api_key = api_key if api_key is not None else settings.PDF_MANAGER_API_KEY

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def upload_pdf(self, *, file_obj, filename: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/upload/"
        try:
            resp = requests.post(
                url,
                files={"file": (filename, file_obj, "application/pdf")},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PDFManagerError(f"Parser service unreachable: {exc}") from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PDFManagerError(
                f"Parser returned non-JSON response ({resp.status_code})",
                status_code=resp.status_code,
            ) from exc

        if resp.status_code >= 400 or payload.get("status") == "error":
            message = payload.get("error") or payload.get("message") or resp.text
            raise PDFManagerError(
                str(message),
                status_code=resp.status_code,
                payload=payload,
            )

        return payload

    def get_job(self, job_id: UUID | str, *, detail: bool = False) -> dict[str, Any]:
        url = f"{self.base_url}/api/jobs/{job_id}/"
        if detail:
            url = f"{url}?detail=1"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise PDFManagerError(f"Parser service unreachable: {exc}") from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PDFManagerError(
                f"Parser returned non-JSON response ({resp.status_code})",
                status_code=resp.status_code,
            ) from exc

        if resp.status_code >= 400:
            message = payload.get("error") or payload.get("message") or resp.text
            raise PDFManagerError(
                str(message),
                status_code=resp.status_code,
                payload=payload,
            )

        return payload

    def poll_until_done(
        self,
        job_id: UUID | str,
        *,
        detail: bool = True,
        max_wait_seconds: float | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> dict[str, Any]:
        """
        Poll job status until done/error or timeout.
        MVP upload path is synchronous; this supports a future async parser.
        """
        deadline = time.monotonic() + (max_wait_seconds or float(self.timeout))
        last_payload: dict[str, Any] = {}

        while time.monotonic() < deadline:
            last_payload = self.get_job(job_id, detail=detail)
            status = (last_payload.get("status") or "").lower()
            if status in {"done", "error"}:
                if status == "error":
                    raise PDFManagerError(
                        last_payload.get("error") or "Parser job failed",
                        payload=last_payload,
                    )
                return last_payload
            time.sleep(poll_interval_seconds)

        raise PDFManagerError(
            "Parser job timed out",
            payload=last_payload,
        )

    def upload_and_fetch_detail(self, *, file_obj, filename: str) -> dict[str, Any]:
        """
        Upload a PDF and return the full job detail payload.
        """
        upload_payload = self.upload_pdf(file_obj=file_obj, filename=filename)
        job_id = upload_payload.get("job_id")
        if not job_id:
            raise PDFManagerError("Parser upload did not return job_id", payload=upload_payload)

        status = (upload_payload.get("status") or "").lower()
        if status == "done" and upload_payload.get("fields"):
            return upload_payload

        detail = self.poll_until_done(job_id, detail=True)
        detail.setdefault("job_id", str(job_id))
        return detail

    def set_job_disposition(
        self,
        job_id: UUID | str,
        *,
        status: str,
    ) -> dict[str, Any]:
        """
        Mark a completed parse job as CANCELLED or APPLIED (Path A global upload).
        """
        url = f"{self.base_url}/api/jobs/{job_id}/disposition/"
        try:
            resp = requests.post(
                url,
                json={"status": status},
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PDFManagerError(f"Parser service unreachable: {exc}") from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PDFManagerError(
                f"Parser returned non-JSON response ({resp.status_code})",
                status_code=resp.status_code,
            ) from exc

        if resp.status_code >= 400 or payload.get("status") == "error":
            message = payload.get("error") or payload.get("message") or resp.text
            raise PDFManagerError(
                str(message),
                status_code=resp.status_code,
                payload=payload,
            )
        return payload

    def download_output(self, job_id: UUID | str, *, bundle: bool = False) -> requests.Response:
        """
        Stream a parser output PDF (main packet) or ZIP bundle (signature + vouchers).
        """
        segment = "outputs" if bundle else "output"
        url = f"{self.base_url}/api/jobs/{job_id}/{segment}/"
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PDFManagerError(f"Parser service unreachable: {exc}") from exc

        if resp.status_code >= 400:
            raise PDFManagerError(
                f"Parser download failed ({resp.status_code})",
                status_code=resp.status_code,
            )
        return resp
