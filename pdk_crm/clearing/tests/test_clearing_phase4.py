import datetime
import uuid
from decimal import Decimal
from io import BytesIO
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
    TaxSeason,
    TaxYear,
)
from core.workflows.lifecycle import cmd_enter_clearing

from clearing.services.parser_schema import (
    SCHEMA_VERSION,
    build_parse_result_snapshot,
    build_parser_output_refs,
    build_quality,
    suggest_pa_field_updates,
    sync_client_name_from_parse_fields,
)
from clearing.services.parse_upload import (
    ParseUploadError,
    apply_parser_from_job,
    apply_parser_pdf,
)

User = get_user_model()


SAMPLE_JOB_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SAMPLE_DETAIL = {
    "job_id": SAMPLE_JOB_ID,
    "status": "done",
    "fields": {
        "taxpayer_first_name": "Jane",
        "tax_year": "2024",
        "tax_prep_fee": 275.0,
        "has_tpg_pages": True,
        "federal_amount": 1200.0,
        "message_ready": True,
    },
    "message": "Hi Jane,\n\nYour return is ready.",
    "pages": [{"tags": ["CLIENT_LETTER"], "outlines": ["Client Letter"], "section_key": "CLIENT_LETTER"}],
    "output_pdf_path": "/data/outputs/main.pdf",
    "signature_pdf_path": "/data/outputs/sig.pdf",
    "payment_voucher_pdf_path": None,
}


class ParserSchemaTests(TestCase):
    def test_build_parse_result_snapshot(self):
        snapshot = build_parse_result_snapshot(job_id=SAMPLE_JOB_ID, detail=SAMPLE_DETAIL)
        self.assertEqual(snapshot["schema_version"], SCHEMA_VERSION)
        self.assertEqual(snapshot["job_id"], SAMPLE_JOB_ID)
        self.assertEqual(snapshot["fields"]["taxpayer_first_name"], "Jane")
        self.assertEqual(snapshot["quality"]["message_ready"], True)
        self.assertNotIn("message_ready", snapshot["fields"])
        self.assertEqual(snapshot["message"], SAMPLE_DETAIL["message"])
        self.assertEqual(snapshot["outputs"]["main_packet"], "/data/outputs/main.pdf")

    def test_build_quality_from_fields(self):
        quality = build_quality({"message_ready": False, "message_ready_reason": "missing_tax_year"})
        self.assertFalse(quality["message_ready"])
        self.assertEqual(quality["message_ready_reason"], "missing_tax_year")

    @override_settings(PDF_MANAGER_BASE_URL="http://parser.test:8001")
    def test_build_parser_output_refs(self):
        refs = build_parser_output_refs(
            job_id=SAMPLE_JOB_ID,
            detail=SAMPLE_DETAIL,
        )
        kinds = {ref["kind"] for ref in refs}
        self.assertIn("main_packet", kinds)
        self.assertIn("all_outputs", kinds)
        self.assertEqual(refs[0]["job_id"], SAMPLE_JOB_ID)
        self.assertNotIn("download_url", refs[0])

    def test_build_parse_result_snapshot_includes_ack_hints(self):
        detail = {
            **SAMPLE_DETAIL,
            "fields": {
                **SAMPLE_DETAIL["fields"],
                "expected_ack_count": 2,
                "expected_transmissions": [
                    {"jurisdiction": "federal", "form_type": "1040", "source": "client_letter"},
                    {"jurisdiction": "state", "form_type": "CA540", "source": "client_letter"},
                ],
            },
        }
        snapshot = build_parse_result_snapshot(job_id=SAMPLE_JOB_ID, detail=detail)
        self.assertEqual(snapshot["fields"]["expected_ack_count"], 2)
        self.assertEqual(len(snapshot["fields"]["expected_transmissions"]), 2)

    def test_suggest_pa_field_updates_tpg(self):
        updates = suggest_pa_field_updates(SAMPLE_DETAIL["fields"])
        self.assertEqual(updates["fee"], "275.0")
        self.assertEqual(updates["payment_method"], ProductAssignment.PAYMENT_METHOD_TPG)

    def test_suggest_pa_field_updates_qbo_when_not_tpg(self):
        fields = {**SAMPLE_DETAIL["fields"], "has_tpg_pages": False}
        updates = suggest_pa_field_updates(fields)
        self.assertEqual(updates["payment_method"], ProductAssignment.PAYMENT_METHOD_QBO)


class ApplyParserPdfTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.user = User.objects.create_user(
            email=f"preparer-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.org,
            role="tax_preparer",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Parser Client")
        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.intake = Intake.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=True,
        )
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2024)
        self.filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
            default_price="150.00",
        )
        self.pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=self.pa.id, actor=self.user)
        DailyClearing.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=True,
        )

    def test_apply_parser_pdf_skips_message_when_not_ready(self):
        mock_client = MagicMock()
        mock_client.upload_and_fetch_detail.return_value = {
            **SAMPLE_DETAIL,
            "fields": {"tax_year": "2024", "message_ready": False, "message_ready_reason": "missing_taxpayer_first_name"},
            "message": "Hi ,\n\nShould not apply.",
        }
        self.pa.closing_message_text = "Existing draft"
        self.pa.save(update_fields=["closing_message_text"])

        apply_parser_from_job(self.pa, SAMPLE_JOB_ID, client=mock_client, detail={
            **SAMPLE_DETAIL,
            "fields": {"tax_year": "2024", "message_ready": False, "message_ready_reason": "missing_taxpayer_first_name"},
            "message": "Hi ,\n\nShould not apply.",
        })

        self.pa.refresh_from_db()
        self.assertEqual(self.pa.closing_message_text, "Existing draft")
        self.assertFalse(self.pa.parse_result_json["quality"]["message_ready"])

    def test_apply_parser_pdf_stores_snapshot_on_pa(self):
        mock_client = MagicMock()
        mock_client.get_job.return_value = SAMPLE_DETAIL

        result = apply_parser_from_job(self.pa, SAMPLE_JOB_ID, client=mock_client, detail=SAMPLE_DETAIL)

        self.pa.refresh_from_db()
        self.assertEqual(str(self.pa.parse_job_uuid), SAMPLE_JOB_ID)
        self.assertIsNotNone(self.pa.parse_result_json)
        self.assertEqual(self.pa.parse_result_json["schema_version"], SCHEMA_VERSION)
        self.assertEqual(self.pa.parser_status, ParserStatus.DONE)
        self.assertEqual(self.pa.closing_message_text, SAMPLE_DETAIL["message"])
        self.assertEqual(self.pa.fee, Decimal("275.0"))
        self.assertEqual(self.pa.payment_method, ProductAssignment.PAYMENT_METHOD_TPG)
        self.assertIsNotNone(self.pa.parsed_at)
        self.assertTrue(self.pa.parser_output_refs)
        self.assertEqual(result["parse_job_uuid"], SAMPLE_JOB_ID)

    def test_apply_parser_pdf_rejects_locked_row(self):
        self.pa.lifecycle_state = LifecycleState.CLEARING_COMPLETE
        self.pa.save(update_fields=["lifecycle_state"])

        with self.assertRaises(ParseUploadError):
            apply_parser_pdf(self.pa, BytesIO(b"%PDF-1.4 fake"), client=MagicMock())

    def test_apply_parser_pdf_syncs_entity_client_name(self):
        self.client_obj.name = "Formatted UI"
        self.client_obj.save(update_fields=["name"])

        mock_client = MagicMock()
        mock_client.upload_and_fetch_detail.return_value = {
            **SAMPLE_DETAIL,
            "fields": {
                **SAMPLE_DETAIL["fields"],
                "taxpayer_full_name": "Test S Corp",
                "taxpayer_first_name": "Test S Corp",
                "taxpayer_tin": "123456789",
            },
            "message": "Hi Test S Corp,\n\nYour return is ready.",
        }

        result = apply_parser_from_job(
            self.pa,
            SAMPLE_JOB_ID,
            client=mock_client,
            detail=mock_client.upload_and_fetch_detail.return_value,
        )

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.name, "Test S Corp")
        self.assertEqual(result["client_name"], "Test S Corp")

    def test_apply_parser_pdf_requires_conflict_flow_on_board(self):
        with self.assertRaises(ParseUploadError) as ctx:
            apply_parser_pdf(self.pa, BytesIO(b"%PDF-1.4 fake"), client=MagicMock())
        self.assertIn("already on clearing", str(ctx.exception))

    def test_sync_client_name_skips_individual_returns(self):
        updated = sync_client_name_from_parse_fields(
            self.client_obj,
            {"taxpayer_full_name": "John & Jane Doe", "taxpayer_first_name": "John"},
        )
        self.assertFalse(updated)
        self.assertEqual(self.client_obj.name, "Parser Client")

    def test_apply_parser_from_job_rejects_tin_mismatch(self):
        detail = {
            **SAMPLE_DETAIL,
            "fields": {
                **SAMPLE_DETAIL["fields"],
                "taxpayer_tin": "999999999",
            },
        }

        with self.assertRaises(ParseUploadError) as ctx:
            apply_parser_from_job(
                self.pa,
                SAMPLE_JOB_ID,
                client=MagicMock(),
                detail=detail,
            )
        self.assertIn("does not match", str(ctx.exception))


@override_settings(FEATURE_PARSER_PATH_A=True)
class ParsePdfUploadViewTests(TestCase):
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

        self.client_obj = Client.objects.create(TIN="111222333", name="Upload Client")
        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )
        self.intake = Intake.objects.create(
            client=self.client_obj,
            tax_season=self.tax_season,
            is_active=True,
        )
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2024)
        self.filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )
        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
            default_price="150.00",
        )
        self.pa, _ = ProductAssignment.objects.create_product_assignment(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
        )
        cmd_enter_clearing(pa_id=self.pa.id, actor=self.user)

    def test_parse_pdf_upload_view_requires_conflict_flow_on_board(self):
        url = reverse("clearing:parse_pdf_upload", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(
            url,
            {"file": SimpleUploadedFile("return.pdf", b"%PDF-1.4 fake content", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already on clearing", resp.json()["message"])

    @patch("clearing.views.apply_parser_pdf")
    def test_parse_pdf_upload_view_success(self, mock_apply):
        mock_apply.return_value = {
            "parse_job_uuid": SAMPLE_JOB_ID,
            "parsed_at": "2025-06-01T12:00:00+00:00",
            "message_text": "Hi Jane,",
            "fee": "275.00",
            "payment_method": ProductAssignment.PAYMENT_METHOD_TPG,
            "parser_output_refs": [],
            "fields": SAMPLE_DETAIL["fields"],
        }

        url = reverse("clearing:parse_pdf_upload", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(
            url,
            {"file": SimpleUploadedFile("return.pdf", b"%PDF-1.4 fake content", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["parse_job_uuid"], SAMPLE_JOB_ID)
        mock_apply.assert_called_once()

    def test_parse_pdf_upload_view_requires_pdf(self):
        url = reverse("clearing:parse_pdf_upload", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(
            url,
            {"file": SimpleUploadedFile("notes.txt", b"not a pdf", content_type="text/plain")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PDF", resp.json()["message"])

    @override_settings(FEATURE_PARSER_PATH_A=False)
    def test_parse_pdf_upload_disabled_by_feature_flag(self):
        url = reverse("clearing:parse_pdf_upload", kwargs={"pa_id": self.pa.id})
        resp = self.http.post(url)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "PARSER_DISABLED")
