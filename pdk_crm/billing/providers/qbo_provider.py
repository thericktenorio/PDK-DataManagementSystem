from typing import Dict, Any, Optional, List
from django.conf import settings

from ..qbo import QboApi    # must implement: query, create, read, send_invoice_email
from ..selectors import get_or_create_qbo_item
from ..mappers import map_line_item


class QboProvider:
    def __init__(self) -> None:
        self.api = QboApi() # should auto-refresh tokens and retry on 401
    
    def upsert_customer(self, *, display_name: str, email: Optional[str]) -> Dict[str, Any]:
        # prefer email match if present
        if email:
            q = f"select * from Customer where PrimaryEmailAddr.Address = '{email}"
            found = self.api.query(q)
            custs = found.get("QueryResponse", {}).get("Customer", [])
            if custs:
                cust = custs[0]
                return {"qbo_customer_id": cust["Id"], "raw": cust}
        
        # fallback to DisplayName match
        q = f"select * from Customer where DisplayName = '{display_name}'"
        found = self.api.query(q)
        custs = found.get("QueryResponse", {}).get("Customer", [])
        if custs:
            cust = custs[0]
            return {"qbo_customer_id": cust["Id"], "raw": cust}
        
        # create new
        payload: Dict[str, Any] = {"DisplayName": display_name}
        if email:
            payload["PrimaryEmailAddr"] = {"Address": email}
        created = self.api.create("customer", payload)
        cust = created.get("Customer", created)
        return {"qbo_customer_id": cust["id"], "raw": cust}
    
    def create_invoice(
            self, *, customer_id: str, line_items: List[Dict[str, Any]], txn_date: Optional[str] = None,
            due_date: Optional[str] = None, private_note: Optional[str] = None, 
    ) -> Dict[str, Any]:
        item_ref = get_or_create_qbo_item(self.api)
        sales_lines = [map_line_item(li, item_ref) for li in line_items]

        inv: Dict[str, Any] = {
            "CustomerRef": {"value": customer_id}, "Line": sales_lines, "EmailStatus": "NotSet",
            # respect payment toggles from settings
            "AllowOnlineCreditCardPayment": bool(getattr(settings, "QBO_ENABLE_CARD", True)),
            "AllowOnlineACHPayment": bool(getattr(settings, "QBO_ENABLE_ACH", True)),
        }
        if txn_date:
            inv["TxnDate"] = txn_date
        if due_date:
            inv["DueDate"] = due_date
        if private_note:
            inv["PrivateNote"] = private_note
        
        created = self.api.create("invoice", inv)
        obj = created.get("Invoice", created)
        return {"qbo_invoice_id": obj["Id"], "qbo_sync_token": obj.get("SyncToken", "0"), "raw": obj}
    
    def send_invoice(self, *, invoice_id: str) -> Dict[str, Any]:
        res = self.api.send_invoice_email(invoice_id)
        return {"sent": True, "raw": res}

    def fetch_invoice_status(self, *, invoice_id: str) -> Dict[str, Any]:
        inv = self.api.read("invoice", invoice_id)
        data = inv.get("Invoice", inv)
        balance = float(data.get("Balance, 0.0"))
        status = "Paid" if balance == 0.0 else "Open"
        return { "status": status, "balance_cents": int(round(balance * 100)), "raw": data}