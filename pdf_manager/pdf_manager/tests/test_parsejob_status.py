"""ParseJob disposition statuses for Path A global upload."""
from pdf_manager.apps.core.models import ParseJob


def test_parsejob_status_includes_cancelled_and_applied():
    values = {choice.value for choice in ParseJob.Status}
    assert values == {"PENDING", "SUCCESS", "FAILED", "CANCELLED", "APPLIED"}
