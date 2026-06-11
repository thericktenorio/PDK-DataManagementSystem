import datetime
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from core.models import (
    Client,
    DailyClearing,
    FilingType,
    Intake,
    LifecycleState,
    Organization,
    ParserStatus,
    Product,
    ProductAssignment,
    ProductAssignmentEvent,
    TaxSeason,
    TaxYear,
)
from core.utils import seed_products_for_tax_year
from core.workflows.lifecycle import cmd_complete_clearing, cmd_enter_clearing

from clearing.services.global_parse import (
    GlobalParseError,
    build_extracted_preview,
    build_match_payload,
    commit_global_upload,
    normalize_tin,
    preview_global_upload,
)

User = get_user_model()

SAMPLE_JOB_ID = "b1c2d3e4-f5a6-7890-bcde-f12345678901"
SAMPLE_DETAIL = {
    "job_id": SAMPLE_JOB_ID,
    "status": "done",
    "fields": {
        "taxpayer_tin": "123-45-6789",
        "taxpayer_full_name": "JOHN DOE",
        "tax_year": "2024",
        "tax_prep_fee": 275.0,
        "has_tpg_pages": True,
        "message_ready": True,
    },
    "message": "Hi John,\n\nYour return is ready.",
    "output_pdf_path": "/data/outputs/main.pdf",
    "signature_pdf_path": "/data/outputs/sig.pdf",
}


def _mock_pdf_client():
    client = MagicMock()
    client.upload_and_fetch_detail.return_value = SAMPLE_DETAIL
    client.get_job.return_value = SAMPLE_DETAIL
    client.set_job_disposition.return_value = {"status": "success"}
    return client


class GlobalParseHelperTests(TestCase):
    def test_normalize_tin_strips_non_digits(self):
        self.assertEqual(normalize_tin("123-45-6789"), "123456789")
        self.assertIsNone(normalize_tin("12345"))

    def test_build_extracted_preview(self):
        extracted = build_extracted_preview(SAMPLE_DETAIL)
        self.assertEqual(extracted["taxpayer_tin"], "123456789")
        self.assertEqual(extracted["taxpayer_full_name"], "JOHN DOE")
        self.assertEqual(extracted["tax_year"], "2024")
        self.assertTrue(extracted["message_ready"])


@override_settings(FEATURE_PARSER_PATH_A=True)
class PathAGlobalUploadTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"preparer-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.http = HttpClient()
        self.http.force_login(self.user)

        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.filing_type = FilingType.objects.filter(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        ).order_by("id").first()
        if self.filing_type is None:
            self.filing_type = FilingType.objects.create(
                filing_type=FilingType.FILING_TYPE_DEFAULT
            )

        self.personal_ft = FilingType.objects.create(filing_type="Married Joint")

        self.existing_client = Client.objects.create(TIN="987654321", name="Existing Client")
        self.existing_tax_year = TaxYear.objects.create(client=self.existing_client, year=2024)
        seed_products_for_tax_year(self.existing_tax_year)
        self.reference_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_PERSONAL_TAXES,
        )

        self.mock_pdf = _mock_pdf_client()

    def _upload_file(self):
        return SimpleUploadedFile(
            "return.pdf",
            b"%PDF-1.4 fake content",
            content_type="application/pdf",
        )

    def _commit_body(self, **overrides):
        body = {
            "parse_job_uuid": SAMPLE_JOB_ID,
            "filing_type_id": self.filing_type.id,
            "product_id": self.reference_product.id,
        }
        body.update(overrides)
        return body

    def test_preview_no_tin_match(self):
        payload = preview_global_upload(self._upload_file(), client=self.mock_pdf)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["parse_job_uuid"], SAMPLE_JOB_ID)
        self.assertIsNone(payload["match"]["client_id"])
        self.mock_pdf.upload_and_fetch_detail.assert_called_once()

    def test_preview_includes_suggested_enrollment(self):
        for ft_value, _ in FilingType.FILING_TYPE_CHOICES:
            FilingType.objects.get_or_create(filing_type=ft_value)

        detail = {
            **SAMPLE_DETAIL,
            "fields": {
                **SAMPLE_DETAIL["fields"],
                "enrollment_signals": {
                    "has_sole_prop_schedule": True,
                    "comparison_num_dependents": 1,
                    "preparer_name": "RICARDO TENORIO",
                },
            },
        }
        self.mock_pdf.upload_and_fetch_detail.return_value = detail

        preparer = User.objects.create_user(
            email=f"ricardo-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
            first_name="RICARDO",
            last_name="TENORIO",
        )

        payload = preview_global_upload(self._upload_file(), client=self.mock_pdf)
        suggested = payload.get("suggested_enrollment") or {}
        self.assertEqual(suggested.get("filing_type"), FilingType.FILING_TYPE_SOLE_PROP)
        self.assertEqual(suggested.get("product_type"), Product.PRODUCT_TYPE_PERSONAL_TAXES)
        self.assertEqual(suggested.get("payment_method"), ProductAssignment.PAYMENT_METHOD_TPG)
        self.assertEqual(suggested.get("preparer_id"), preparer.id)
        self.assertTrue(suggested.get("filing_type_id"))
        self.assertTrue(suggested.get("product_id"))
        self.assertIn("reasons", suggested)

    def test_preview_match_on_clearing(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.upload_and_fetch_detail.return_value = detail

        payload = preview_global_upload(self._upload_file(), client=self.mock_pdf)
        self.assertEqual(payload["match"]["client_id"], self.existing_client.id)
        self.assertTrue(payload["match"]["on_clearing"])
        self.assertEqual(len(payload["match"]["product_assignments"]), 1)

    def test_commit_new_client_creates_client_and_pa(self):
        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="new_client",
            actor=self.user,
            filing_type_id=self.filing_type.id,
            product_id=self.reference_product.id,
            pdf_client=self.mock_pdf,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "new_client")

        client = Client.objects.get(TIN="123456789")
        self.assertEqual(client.name, "JOHN DOE")
        pa = ProductAssignment.objects.get(pk=result["product_assignment_id"])
        self.assertEqual(pa.client_id, client.id)
        self.assertEqual(pa.tax_year.year, 2024)
        self.assertEqual(pa.parser_status, ParserStatus.DONE)
        active_pas = ProductAssignment.objects.filter(client=client, is_active=True)
        self.assertEqual(active_pas.count(), 1)
        self.assertTrue(
            DailyClearing.objects.filter(client=client, is_active=True).exists()
        )
        self.mock_pdf.set_job_disposition.assert_called_with(
            SAMPLE_JOB_ID, status="APPLIED"
        )

    def test_commit_enroll_activates_existing_client(self):
        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.get_job.return_value = detail

        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="enroll",
            actor=self.user,
            client_id=self.existing_client.id,
            filing_type_id=self.filing_type.id,
            product_id=self.reference_product.id,
            pdf_client=self.mock_pdf,
        )
        self.assertEqual(result["client_id"], self.existing_client.id)
        self.assertTrue(
            DailyClearing.objects.filter(
                client=self.existing_client,
                tax_season=self.tax_season,
                is_active=True,
            ).exists()
        )
        pa = ProductAssignment.objects.get(pk=result["product_assignment_id"])
        self.assertEqual(pa.parser_status, ParserStatus.DONE)

    def test_commit_cancel_marks_job_cancelled(self):
        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="cancel",
            actor=self.user,
            pdf_client=self.mock_pdf,
        )
        self.assertEqual(result["action"], "cancel")
        self.mock_pdf.set_job_disposition.assert_called_with(
            SAMPLE_JOB_ID, status="CANCELLED"
        )
        self.assertEqual(Client.objects.filter(TIN="123456789").count(), 0)

    def test_preview_orphan_daily_clearing_routes_to_enroll(self):
        """Stale DailyClearing without active PAs should not trigger conflict."""
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.upload_and_fetch_detail.return_value = detail

        payload = preview_global_upload(self._upload_file(), client=self.mock_pdf)
        self.assertFalse(payload["match"]["on_clearing"])
        self.assertEqual(payload["match"]["product_assignments"], [])

        dc = DailyClearing.objects.get(
            client=self.existing_client,
            tax_season=self.tax_season,
        )
        self.assertFalse(dc.is_active)

    def test_preview_auto_apply_empty_manual_placeholder(self):
        """Single Path B row without parser data should auto-apply, not conflict."""
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.upload_and_fetch_detail.return_value = detail

        payload = preview_global_upload(self._upload_file(), client=self.mock_pdf)
        self.assertTrue(payload["match"]["on_clearing"])
        self.assertEqual(payload["match"]["auto_apply_pa_id"], pa.id)

    def test_commit_apply_to_empty_manual_placeholder(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.get_job.return_value = detail

        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="apply",
            actor=self.user,
            client_id=self.existing_client.id,
            pa_id=pa.id,
            pdf_client=self.mock_pdf,
        )
        self.assertEqual(result["action"], "apply")
        self.assertEqual(result["product_assignment_id"], pa.id)
        pa.refresh_from_db()
        self.assertEqual(pa.parser_status, ParserStatus.DONE)
        self.assertIsNotNone(pa.parse_job_uuid)

    def test_build_match_payload_reconciles_orphan_clearing(self):
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        match = build_match_payload(self.existing_client)
        self.assertFalse(match["on_clearing"])
        dc = DailyClearing.objects.get(
            client=self.existing_client,
            tax_season=self.tax_season,
        )
        self.assertFalse(dc.is_active)

    def test_commit_new_entry_rejects_tin_mismatch(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        wrong_client = Client.objects.create(TIN="000000009", name="Wrong Client")
        self.mock_pdf.get_job.return_value = SAMPLE_DETAIL

        with self.assertRaises(GlobalParseError) as ctx:
            commit_global_upload(
                parse_job_uuid=SAMPLE_JOB_ID,
                action="new_entry",
                actor=self.user,
                client_id=wrong_client.id,
                filing_type_id=self.filing_type.id,
                product_id=self.reference_product.id,
                pdf_client=self.mock_pdf,
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_commit_new_entry_adds_subrow_pa(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.get_job.return_value = detail

        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="new_entry",
            actor=self.user,
            client_id=self.existing_client.id,
            filing_type_id=self.filing_type.id,
            product_id=self.reference_product.id,
            pdf_client=self.mock_pdf,
        )
        self.assertEqual(result["action"], "new_entry")
        self.assertNotEqual(result["product_assignment_id"], pa.id)
        self.assertEqual(
            ProductAssignment.objects.filter(
                client=self.existing_client, is_active=True
            ).count(),
            2,
        )

    def test_commit_replace_voids_old_pa(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        old_pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        old_pa.parse_job_uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        old_pa.save(update_fields=["parse_job_uuid"])
        cmd_enter_clearing(pa_id=old_pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.get_job.return_value = detail

        result = commit_global_upload(
            parse_job_uuid=SAMPLE_JOB_ID,
            action="replace",
            actor=self.user,
            client_id=self.existing_client.id,
            pa_id=old_pa.id,
            pdf_client=self.mock_pdf,
        )
        old_pa.refresh_from_db()
        self.assertEqual(result["voided_product_assignment_id"], old_pa.id)
        self.assertFalse(old_pa.is_active)
        self.assertIsNotNone(old_pa.voided_at)
        self.assertEqual(old_pa.void_reason, ProductAssignment.VoidReason.PDF_REPLACED)
        self.assertEqual(old_pa.superseded_by_id, result["product_assignment_id"])
        self.assertTrue(
            ProductAssignmentEvent.objects.filter(
                product_assignment=old_pa,
                event_type=ProductAssignmentEvent.EventType.PARSE_SUPERSEDED,
            ).exists()
        )

    def test_commit_replace_blocked_when_locked(self):
        intake = Intake.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )
        default_product = Product.objects.get(
            tax_year=self.existing_tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
        )
        old_pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.existing_client,
            intake=intake,
            tax_year=self.existing_tax_year,
            product=default_product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=old_pa.id, actor=self.user)
        old_pa.payment_method = ProductAssignment.PAYMENT_METHOD_CASH
        old_pa.preparer = self.user
        old_pa.closing_message_text = "Ready."
        old_pa.fee = Decimal("150.00")
        old_pa.save(
            update_fields=["payment_method", "preparer", "closing_message_text", "fee"]
        )
        cmd_complete_clearing(pa_id=old_pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.existing_client,
            tax_season=self.tax_season,
            is_active=True,
        )

        detail = {
            **SAMPLE_DETAIL,
            "fields": {**SAMPLE_DETAIL["fields"], "taxpayer_tin": "987654321"},
        }
        self.mock_pdf.get_job.return_value = detail

        with self.assertRaises(GlobalParseError) as ctx:
            commit_global_upload(
                parse_job_uuid=SAMPLE_JOB_ID,
                action="replace",
                actor=self.user,
                client_id=self.existing_client.id,
                pa_id=old_pa.id,
                pdf_client=self.mock_pdf,
            )
        self.assertIn("already completed clearing", str(ctx.exception))

    @patch("clearing.views.preview_global_upload")
    def test_preview_view_success(self, mock_preview):
        mock_preview.return_value = {
            "status": "success",
            "parse_job_uuid": SAMPLE_JOB_ID,
            "extracted": {"taxpayer_tin": "123456789"},
            "match": {"client_id": None},
        }
        url = reverse("clearing:parse_pdf_global_preview")
        resp = self.http.post(url, {"file": self._upload_file()}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["parse_job_uuid"], SAMPLE_JOB_ID)

    @patch("clearing.views.commit_global_upload")
    def test_commit_view_success(self, mock_commit):
        mock_commit.return_value = {
            "status": "success",
            "action": "new_client",
            "client_id": 99,
            "product_assignment_id": 100,
            "voided_product_assignment_id": None,
            "parse_job_uuid": SAMPLE_JOB_ID,
            "message": "PDF applied.",
            "downloads": [],
        }
        url = reverse("clearing:parse_pdf_global_commit")
        resp = self.http.post(
            url,
            data=json.dumps(self._commit_body(action="new_client")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "new_client")

    @override_settings(FEATURE_PARSER_PATH_A=False)
    def test_endpoints_disabled_without_feature_flag(self):
        preview_url = reverse("clearing:parse_pdf_global_preview")
        commit_url = reverse("clearing:parse_pdf_global_commit")
        self.assertEqual(self.http.post(preview_url).status_code, 403)
        self.assertEqual(
            self.http.post(
                commit_url,
                data=json.dumps(self._commit_body(action="cancel")),
                content_type="application/json",
            ).status_code,
            403,
        )
