from typing import Optional, Dict, Any, Protocol, List

class BillingProvider(Protocol):
    def upsert_customer(self, *, display_name: str, email: Optional[str]) -> Dict[str, Any]:
        '''Return: {'qbo_customer_id': '123', 'raw': <provider-payload>}'''
    
    def create_invoice(
            self, *, customer_id: str, line_items: List[Dict[str, Any]], txn_date: Optional[str] = None, 
            due_date: Optional[str] = None, private_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        '''Return: {'qbo_invoice_id': '456', 'qbo_sync_token': '0', 'raw': <payload>}'''
    
    def send_invoice(self, *, invoice_id: str) -> Dict[str, Any]:
        '''Return: {'sent': True, 'raw': <payload>}'''
    
    def fetch_invoice_status(self, *, invoice_id: str) -> Dict[str, Any]:
        '''Return: {'status': 'Open|Paid|...', 'balance_cents': int, 'raw': <payload>}'''