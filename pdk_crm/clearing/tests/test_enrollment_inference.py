"""CRM enrollment inference mapping tests."""
from __future__ import annotations

import datetime
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Client, FilingType, Product, ProductAssignment, TaxSeason, TaxYear
from core.utils import seed_products_for_tax_year

from clearing.services.enrollment_inference import (
    build_suggested_enrollment,
    infer_filing_type_string,
    infer_payment_method,
    infer_product_type_string,
    is_auto_commit_eligible,
    match_preparer_id,
    resolve_catalog_ids,
)

User = get_user_model()


class EnrollmentInferenceMappingTests(TestCase):
    def setUp(self):
        from core.models import Organization

        self.organization = Organization.objects.create(name=f"Org {uuid.uuid4().hex[:8]}")
        self.preparer = User.objects.create_user(
            email=f"ricardo-{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            organization=self.organization,
            role="tax_preparer",
            first_name="RICARDO",
            last_name="TENORIO",
        )
        self.client_obj = Client.objects.create(TIN="123456789", name="Test Client")
        self.tax_year = TaxYear.objects.create(client=self.client_obj, year=2024)
        seed_products_for_tax_year(self.tax_year)

        for ft_value in FilingType.FILING_TYPE_CHOICES:
            FilingType.objects.get_or_create(filing_type=ft_value[0])

        self.tax_season = TaxSeason.objects.create(
            year=2025,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 10, 15),
            is_active=True,
        )

    def test_infer_corporation_filing_type(self):
        ft = infer_filing_type_string({"is_corporation": True})
        self.assertEqual(ft, FilingType.FILING_TYPE_CORPORATION)

    def test_infer_sole_prop_schedule_beats_itemizing(self):
        ft = infer_filing_type_string(
            {
                "has_sole_prop_schedule": True,
                "comparison_itemized_deductions": 55_000,
                "comparison_standard_deduction": 29_200,
            }
        )
        self.assertEqual(ft, FilingType.FILING_TYPE_SOLE_PROP)

    def test_infer_itemizing(self):
        ft = infer_filing_type_string(
            {
                "comparison_itemized_deductions": 55_000,
                "comparison_standard_deduction": 29_200,
            }
        )
        self.assertEqual(ft, FilingType.FILING_TYPE_ITEMIZING)

    def test_infer_credits_from_dependents(self):
        ft = infer_filing_type_string({"comparison_num_dependents": 1})
        self.assertEqual(ft, FilingType.FILING_TYPE_CREDITS)

    def test_infer_simple_fallback(self):
        ft = infer_filing_type_string({"has_tpg_pages": False})
        self.assertEqual(ft, FilingType.FILING_TYPE_SIMPLE)

    def test_infer_extension_product(self):
        product = infer_product_type_string(
            {"has_extension": True},
            filing_type=FilingType.FILING_TYPE_SIMPLE,
        )
        self.assertEqual(product, Product.PRODUCT_TYPE_FREE_EXTENSION)

    def test_infer_amendment_product_count(self):
        for count, expected in (
            (1, Product.PRODUCT_TYPE_AMENDMENT_ONE),
            (2, Product.PRODUCT_TYPE_AMENDMENT_TWO),
            (4, Product.PRODUCT_TYPE_AMENDMENT_THREE),
        ):
            product = infer_product_type_string(
                {"amendment_count": count},
                filing_type=FilingType.FILING_TYPE_SIMPLE,
            )
            self.assertEqual(product, expected)

    def test_infer_corporate_taxes_product(self):
        product = infer_product_type_string(
            {"is_corporation": True},
            filing_type=FilingType.FILING_TYPE_CORPORATION,
        )
        self.assertEqual(product, Product.PRODUCT_TYPE_CORPORATE_TAXES)

    def test_infer_personal_taxes_default(self):
        product = infer_product_type_string({}, filing_type=FilingType.FILING_TYPE_SIMPLE)
        self.assertEqual(product, Product.PRODUCT_TYPE_PERSONAL_TAXES)

    def test_payment_method_tpg_vs_qbo(self):
        self.assertEqual(
            infer_payment_method({"has_tpg_pages": True}),
            ProductAssignment.PAYMENT_METHOD_TPG,
        )
        self.assertEqual(
            infer_payment_method({"has_tpg_pages": False}),
            ProductAssignment.PAYMENT_METHOD_QBO,
        )

    def test_match_preparer_by_name(self):
        preparer_id = match_preparer_id({"preparer_name": "RICARDO TENORIO"})
        self.assertEqual(preparer_id, self.preparer.id)

    def test_resolve_catalog_ids_for_client(self):
        ft_id, prod_id = resolve_catalog_ids(
            client=self.client_obj,
            tax_year_value=2024,
            filing_type_str=FilingType.FILING_TYPE_SOLE_PROP,
            product_type_str=Product.PRODUCT_TYPE_PERSONAL_TAXES,
        )
        self.assertIsNotNone(ft_id)
        self.assertIsNotNone(prod_id)

    def test_build_suggested_enrollment_scorp_shape(self):
        detail = {
            "fields": {
                "tax_year": "2024",
                "has_tpg_pages": False,
                "enrollment_signals": {
                    "is_corporation": True,
                    "amendment_count": 0,
                    "has_extension": False,
                    "preparer_name": "RICARDO TENORIO",
                },
            }
        }
        suggested = build_suggested_enrollment(detail, client=self.client_obj)
        self.assertEqual(suggested["filing_type"], FilingType.FILING_TYPE_CORPORATION)
        self.assertEqual(suggested["product_type"], Product.PRODUCT_TYPE_CORPORATE_TAXES)
        self.assertEqual(suggested["payment_method"], ProductAssignment.PAYMENT_METHOD_QBO)
        self.assertEqual(suggested["preparer_id"], self.preparer.id)
        self.assertTrue(suggested["filing_type_id"])
        self.assertTrue(suggested["product_id"])
        self.assertTrue(is_auto_commit_eligible(suggested))

    def test_manual_only_product_not_auto_commit(self):
        suggested = {
            "filing_type_id": 1,
            "product_id": 2,
            "product_type": Product.PRODUCT_TYPE_ADVISORY,
            "auto_commit_eligible": False,
        }
        self.assertFalse(is_auto_commit_eligible(suggested))
