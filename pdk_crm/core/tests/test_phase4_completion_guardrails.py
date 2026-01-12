import uuid
import json
import threading
import datetime

from django.test import TransactionTestCase, Client as HttpClient
from django.urls import reverse
from django.db import connection, close_old_connections, connections

from django.contrib.auth import get_user_model

from core.models import (
    Organization,
    Client as CoreClient,
    TaxSeason,
    TaxYear,
    Product,
    FilingType,
    Intake,
    ProductAssignment,
    CompletionState,
    ParserStatus,
    ProductAssignmentEvent,
)


class Phase4CompletionGuardrailsTests(TransactionTestCase):
    """
    Uses TransactionTestCase (not TestCase) so we can validate:
    - select_for_update() behavior
    - concurrent finalize behavior
    - DB unique constraints under concurrency

    IMPORTANT:
    Threads that touch Django ORM / test client must close DB connections,
    otherwise Postgres may refuse to DROP the test DB during teardown.
    """

    reset_sequences = False  # don't reset sequences in Postgres

    def setUp(self):
        # ---- org (required by InternalUserManager) ----
        self.org = Organization.objects.create(name=f"Test Org {uuid.uuid4().hex[:8]}")

        # ---- auth user ----
        User = get_user_model()
        self.user = User.objects.create_user(
            email="test@test.com",
            password="pw",
            organization=self.org,
        )

        # ---- main-thread HTTP client ----
        self.http = HttpClient()
        self.http.force_login(self.user)

        # ---- minimal domain objects ----
        self.client_obj = CoreClient.objects.create(TIN="000000001", name="Client 1")

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

        self.product = Product.objects.create(
            tax_year=self.tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            is_product_active=False,
            default_price="0.00",
        )

        self.filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )

        self.pa = ProductAssignment.objects.create(
            client=self.client_obj,
            intake=self.intake,
            tax_year=self.tax_year,
            product=self.product,
            filing_type=self.filing_type,
            is_active=True,
            completion_state=CompletionState.OPEN,
            parser_status=ParserStatus.NOT_STARTED,
        )

    def tearDown(self):
        """
        Defensive: ensure all connections are closed so the test DB can be dropped.
        This is especially important with TransactionTestCase + threading.
        """
        for conn in connections.all():
            conn.close()
        super().tearDown()

    def _force_ready_to_complete(self):
        """
        For guard-rail tests we only need PA in READY_TO_COMPLETE.
        We set it directly for test setup, not as a behavior test of earlier steps.
        """
        ProductAssignment.objects.filter(id=self.pa.id).update(
            completion_state=CompletionState.READY_TO_COMPLETE,
            parser_status=ParserStatus.SKIPPED,
            expected_ack_count=0,
        )
        self.pa.refresh_from_db()

    # ---------------------------------------------------------
    # Test 1: double finalize is idempotent (single event)
    # ---------------------------------------------------------
    def test_double_finalize_emits_one_event(self):
        self._force_ready_to_complete()

        url = reverse("core:finalize_completion", kwargs={"pa_id": self.pa.id})

        r1 = self.http.post(url)
        self.assertEqual(r1.status_code, 200, r1.content)

        r2 = self.http.post(url)
        self.assertEqual(r2.status_code, 200, r2.content)

        self.pa.refresh_from_db()
        self.assertEqual(self.pa.completion_state, CompletionState.COMPLETED)

        cnt = ProductAssignmentEvent.objects.filter(
            product_assignment_id=self.pa.id,
            event_type=ProductAssignmentEvent.EventType.PA_COMPLETED,
        ).count()
        self.assertEqual(cnt, 1)

    # ---------------------------------------------------------
    # Test 2: concurrent finalize is safe (single event)
    # ---------------------------------------------------------
    def test_concurrent_finalize_emits_one_event(self):
        self._force_ready_to_complete()
        url = reverse("core:finalize_completion", kwargs={"pa_id": self.pa.id})

        results = []
        errors = []
        lock = threading.Lock()

        def _do_finalize():
            """
            Thread worker:
            - start with close_old_connections() to avoid reusing stale connections
            - always close the connection at the end so Postgres can drop the test DB
            """
            try:
                close_old_connections()

                c = HttpClient()
                c.force_login(self.user)

                resp = c.post(url)

                with lock:
                    results.append(resp.status_code)

            except Exception as e:
                with lock:
                    errors.append(str(e))

            finally:
                # CRITICAL: release the thread's DB session
                connection.close()

        t1 = threading.Thread(target=_do_finalize)
        t2 = threading.Thread(target=_do_finalize)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertFalse(errors, f"Thread errors: {errors}")

        # Both should succeed (one may be noop)
        self.assertTrue(results, "No results captured from threads")
        self.assertTrue(all(code == 200 for code in results), results)

        self.pa.refresh_from_db()
        self.assertEqual(self.pa.completion_state, CompletionState.COMPLETED)

        cnt = ProductAssignmentEvent.objects.filter(
            product_assignment_id=self.pa.id,
            event_type=ProductAssignmentEvent.EventType.PA_COMPLETED,
        ).count()
        self.assertEqual(cnt, 1)

    # ---------------------------------------------------------
    # Test 3: autosave frozen field rejected after completion starts
    # ---------------------------------------------------------
    def test_autosave_rejects_frozen_field_after_start(self):
        # Move to a non-OPEN state
        ProductAssignment.objects.filter(id=self.pa.id).update(
            completion_state=CompletionState.PENDING_PARSER,
            parser_status=ParserStatus.NOT_STARTED,
        )

        url = reverse("core:auto_save_product_assignment")

        payload = {"id": self.pa.id, "field": "fee", "value": "123.45"}
        resp = self.http.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409, resp.content)

        body = resp.json()
        self.assertEqual(body.get("code"), "PA_FROZEN")

        self.pa.refresh_from_db()
        self.assertIsNone(self.pa.fee)
