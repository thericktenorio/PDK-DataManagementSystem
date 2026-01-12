from pathlib import Path
from uuid import uuid4

import pytest

from pdf_manager.apps.parser.exceptions import InputValidationError
from pdf_manager.apps.parser.facade import PDFParserFacade


def test_facade_instantiates_and_fails_on_missing_file(tmp_path: Path):
    facade = PDFParserFacade()
    with pytest.raises(InputValidationError):
        facade.parse(job_id=uuid4(), file_path=str(tmp_path / "missing.pdf"))
