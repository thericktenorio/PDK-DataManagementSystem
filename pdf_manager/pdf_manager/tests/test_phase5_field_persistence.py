"""Phase 5 ExtractedField persistence."""
from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import TestCase

from pdf_manager.apps.core.field_persistence import get_drake_template, persist_extracted_fields
from pdf_manager.apps.core.models import Document, ExtractedField, ParseJob


@pytest.mark.django_db
class ExtractedFieldPersistenceTests(TestCase):
    def test_persist_extracted_fields_with_lineage(self):
        doc = Document.objects.create(filename="test.pdf", checksum="abc123")
        job = ParseJob.objects.create(document=doc, job_uuid=uuid4())
        tpl = get_drake_template()
        assert tpl is not None
        assert tpl.name == "DRAKE"

        fields = {
            "taxpayer_first_name": "Jane",
            "tax_year": "2024",
            "message_ready": True,
            "_field_sources": {
                "taxpayer_first_name": {
                    "page_index": 12,
                    "method": "ocr",
                    "role": "extract_client_letter",
                },
            },
        }
        count = persist_extracted_fields(
            job=job,
            document=doc,
            template=tpl,
            fields=fields,
        )
        assert count == 2
        row = ExtractedField.objects.get(parse_job=job, key="taxpayer_first_name")
        assert row.value == "Jane"
        assert row.extraction_method == "ocr"
        assert row.source_page_index == 12
