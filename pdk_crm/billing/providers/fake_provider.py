import time, uuid
from typing import Dict, Any, Optional, List
from .base import BillingProvider


class FakeProvider(BillingProvider):
    def upsert_customer(self, *, display_name: str, email: Optional[str]) -> Dict[str, Any]:
        return {
            "qbo_customer_id": f"FAKECUST-{uuid.uuid4().hex[:8]}", 
            "raw": {"display_name": display_name, "email": email},
        }

    def create_invoice(
            self, *, customer_id: str, line_items: List[Dict[str, Any]], txn_date: Optional[str] = None,
            due_date: Optional[str] = None, private_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "qbo_invoice_id": f"FAKEINV-{uuid.uuid4().hex[:8]}", "qbo_sync_token": "0",
            "raw": {
                "customer_id": customer_id, "line_items": line_items, "txn_date": txn_date,
                "due_date": due_date, "private_note": private_note,
            },
        }
    
    def send_invoice(self, *, invoice_id: str) -> Dict[str, Any]:
        return {"sent": True, "raw": {"invoice_id": invoice_id, "sent_at": time.time()}}
    
    def fetch_invoice_status(self, *, invoice_id: str) -> Dict[str, Any]:
        return {"status": "Open", "balance_cents": 10000, "raw": {"invoice_id": invoice_id}}