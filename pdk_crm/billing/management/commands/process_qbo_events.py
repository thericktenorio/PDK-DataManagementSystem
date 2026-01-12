from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import QboEntityEvent, EventStatus, QboConnection
from billing.qbo import QboApi
from billing.sync import sync_customer, sync_invoice


BATCH_SIZE = 50

class Command(BaseCommand):
    help = "Process queued QBO entity events (Customer, Invoice)."

    def handle(self, *args, **options):
        qs = (QboEntityEvent.objects.filter(status__in = [EventStatus.RECEIVED, EventStatus.QUEUED]).order_by("last_updated")[:BATCH_SIZE])
        
        processed = 0
        for evt in qs:
            try:
                conn = QboConnection.objects.get(realm_id = evt.realm_id, is_active = True)
            except QboConnection.DoesNotExist:
                self._fail(evt, "No active QboConnection for this realm")
                continue

            api = QboApi(conn)

            try:
                if evt.entity_name == "Customer":
                    doc = api.get_customer(evt.entity_id)
                    cust = doc.get("Customer")
                    if not cust:
                        self._skip(evt, f"Customer {evt.entity_id} not found in QBO")
                        continue
                    sync_customer(conn, cust)
                
                elif evt.entity_name == "Invoice":
                    doc = api.get_invoice(evt.entity_id)
                    inv_doc = doc.get("Invoice")
                    if not inv_doc:
                        self._skip(evt, f"Invoice {evt.entity_id} not found in QBO")
                        continue
                    sync_invoice(conn, inv_doc)
                
                else:
                    self._skip(evt, f"Unhandled entity type {evt.entity_name}")
                    continue

                evt.status = EventStatus.PROCESSED
                evt.processed_at = timezone.now()
                evt.error_message = ""
                evt.save(update_fields = ["status", "processed_at", "error_message"])
                processed += 1

            except Exception as e:
                self._fail(evt, f"{type(e).__name__}: {e}")
            
        self.stdout.write(self.style.SUCCESS(f"Processed {processed} event(s)."))
    
    def _fail(self, evt: QboEntityEvent, msg: str):
        evt.status = EventStatus.ERROR
        evt.error_message = msg
        evt.retries += 1
        evt.save(update_fields = ["status", "error_message", "retries"])
    
    def _skip(self, evt: QboEntityEvent, msg: str):
        # mark as processed but annotate why it was skipped
        evt.status = EventStatus.PROCESSED
        evt.processed_at = timezone.now()
        evt.error_message = msg
        evt.save(update_fields = ["status", "processed_at", "error_message"])