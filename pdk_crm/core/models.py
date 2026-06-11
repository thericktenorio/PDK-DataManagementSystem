from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.conf import settings
from django.apps import apps
from django.utils import timezone
from decimal import Decimal
import datetime



# Validation Functions
def validate_TIN(value):
    value = str(value)
    if not value.isdigit() or len(value) != 9:
        raise ValidationError("TIN must be 9 digits.")

def validate_phone(value):
    if not value.isdigit() or len(value) !=10:
        raise ValidationError("Phone number must be 10 digits.")

def validate_tax_year(value):
    current_year = datetime.datetime.now().year
    current_tax_year = current_year - 1
    seven_yrs_before_current_tax_year = current_tax_year - 7
    if value < seven_yrs_before_current_tax_year  or value > current_tax_year:
        raise ValidationError("Invalid year.")


# Note: QBO connection is established per Organization
class Organization(models.Model):
    is_active = models.BooleanField(default = True)
    is_archived = models.BooleanField(default = False)
    
    name = models.CharField(max_length = 255, unique = True)
    created_at = models.DateTimeField(auto_now_add = True)

    def __str__(self):
        return self.name
    

# TaxSeason : (Ex. Tax Season 2024 occurs in calendar year 2025 and allows 2024 - 2022 taxes to be electronically filed)
    # this is a means to assign all data to a specific tax filing period.
    #  used for data retension, analysis and in depth user functionality.
class TaxSeason(models.Model):
    year = models.PositiveIntegerField(unique = True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default = True, help_text = 'When True season is UI visible. When False season is hidden from UI.')
    is_locked = models.BooleanField(default = False, help_text = 'When True data cannot be edited. When False data is mutable.')
    notes = models.TextField(blank = True)

    is_archived = models.BooleanField(default = False)  # NOTE: once archived data becomes frozen

    class Meta:
        ordering = ['-year']
    
    def __str__(self):
        return f"Tax Season {self.year} ({self.start_date:%b %d} - {self.end_date:%b %d})"


# Concrete Subject "Client"
class Client(models.Model):
    # Tuple for Client's filing type
    FILING_TYPE_DEFAULT = ''
    FILING_TYPE_SIMPLE = 'Simple'
    FILING_TYPE_CREDITS = 'Credits'
    FILING_TYPE_ITEMIZING = 'Itemizing'
    FILING_TYPE_SOLE_PROP = 'Sole Proprietor'
    FILING_TYPE_CORPORATION = 'Corporation' 
    FILING_TYPE_CHOICES = [
        (FILING_TYPE_DEFAULT, ''),
        (FILING_TYPE_SIMPLE, 'Simple'),
        (FILING_TYPE_CREDITS, 'Credits'),
        (FILING_TYPE_ITEMIZING, 'Itemizing'),
        (FILING_TYPE_SOLE_PROP, 'Sole Proprietor'),
        (FILING_TYPE_CORPORATION, 'Corporation'),
    ]

    # Tuple for Client's last known filing type
    PRIOR_FILING_TYPE_DEFAULT = ''
    PRIOR_FILING_TYPE_SIMPLE = 'Simple'
    PRIOR_FILING_TYPE_CREDITS = 'Credits'
    PRIOR_FILING_TYPE_ITEMIZING = 'Itemizing'
    PRIOR_FILING_TYPE_SOLE_PROP = 'Sole Proprietor'
    PRIOR_FILING_TYPE_CORPORATION = 'Corporation'
    PRIOR_FILING_TYPE_CHOICES = [
        (PRIOR_FILING_TYPE_DEFAULT, ''),
        (PRIOR_FILING_TYPE_SIMPLE, 'Simple'),
        (PRIOR_FILING_TYPE_CREDITS, 'Credits'),
        (PRIOR_FILING_TYPE_ITEMIZING, 'Itemizing'),
        (PRIOR_FILING_TYPE_SOLE_PROP, 'Sole Proprietor'),
        (PRIOR_FILING_TYPE_CORPORATION, 'Corporation'),
    ]
    
    # Tuple for Client's appointment types
    APPOINTMENT_TYPE_DEFAULT = ''
    APPOINTMENT_TYPE_DROP_OFF = 'DROP OFF'
    APPOINTMENT_TYPE_OFFICE = 'OFFICE'
    APPOINTMENT_TYPE_ONLINE = 'ONLINE'
    APPOINTMENT_TYPE_TBD = 'TBD'
    APPOINTMENT_TYPE_CHOICES = [
        (APPOINTMENT_TYPE_DEFAULT, ''),
        (APPOINTMENT_TYPE_DROP_OFF, 'DROP OFF'),
        (APPOINTMENT_TYPE_OFFICE, 'OFFICE'),
        (APPOINTMENT_TYPE_ONLINE, 'ONLINE'),
        (APPOINTMENT_TYPE_TBD, 'TBD'),
    ]

    # Client Attributes
    TIN = models.CharField(max_length = 9, validators = [validate_TIN], unique = True, null = True, blank = True)
    name = models.CharField(max_length = 50, default = "", null = True, blank = True)
    email = models.EmailField(max_length = 150, null = True, blank = True)
    phone = models.CharField(max_length = 10, validators = [validate_phone], default = "", null = True, blank = True)

    filing_type = models.CharField(max_length = 100, choices = FILING_TYPE_CHOICES, default = FILING_TYPE_DEFAULT, null = True, blank = True)
    prior_filing_type = models.CharField(max_length = 100, choices = PRIOR_FILING_TYPE_CHOICES, default = PRIOR_FILING_TYPE_DEFAULT, null = True, blank = True)
    appointment_type = models.CharField(max_length = 10, choices = APPOINTMENT_TYPE_CHOICES, default = APPOINTMENT_TYPE_DEFAULT, null = True, blank = True)
    created_at = models.DateTimeField(auto_now_add = True, null = True)

    def __str__(self):
        return f"{self.name} (TIN: {self.TIN})"
    

# TaxYear Model : Used to specify which tax year a product belongs to (ie. Filing Amendment for tax year 20XX)
class TaxYear(models.Model):
    client = models.ForeignKey(Client, related_name = "tax_years", on_delete = models.CASCADE)
    year = models.SmallIntegerField(validators = [validate_tax_year])
    balance = models.DecimalField(max_digits = 10, decimal_places = 2, default = 0.0)

    class Meta:
        unique_together = ('client', 'year')

    def __str__(self):
        return f"{self.year} - Client: {self.client.name} - Balance: (${self.balance})"


# Product Model
class Product(models.Model):
    # Tuple of product types
    PRODUCT_TYPE_DEFAULT = 'TBD'
    PRODUCT_TYPE_PERSONAL_TAXES = 'Personal Taxes'
    PRODUCT_TYPE_CORPORATE_TAXES = 'Corporate Taxes'
    PRODUCT_TYPE_FREE_EXTENSION = 'Free Extension'
    PRODUCT_TYPE_PAID_EXTENSION = 'Paid Extension'
    PRODUCT_TYPE_AMENDMENT_ONE = 'Amendment 1'
    PRODUCT_TYPE_AMENDMENT_TWO = 'Amendment 2'
    PRODUCT_TYPE_AMENDMENT_THREE = 'Amendment 3'
    PRODUCT_TYPE_WITHHOLDINGS_ADJUSTMENT = 'Withholdings Adjustment'
    PRODUCT_TYPE_ADVISORY = 'Advisory'
    PRODUCT_TYPE_REJECT_CORRECTION = 'Reject Correction'
    PRODUCT_TYPE_PAPER_FILING = 'Paper Filing'
    PRODUCT_TYPE_CHOICES = [
        (PRODUCT_TYPE_DEFAULT, 'TBD'),
        (PRODUCT_TYPE_PERSONAL_TAXES, 'Personal Taxes'),
        (PRODUCT_TYPE_CORPORATE_TAXES, 'Corporate Taxes'),
        (PRODUCT_TYPE_FREE_EXTENSION, 'Free Extension'),
        (PRODUCT_TYPE_PAID_EXTENSION, 'Paid Extension'),
        (PRODUCT_TYPE_AMENDMENT_ONE, 'Amendment 1'),
        (PRODUCT_TYPE_AMENDMENT_TWO, 'Amendment 2'),
        (PRODUCT_TYPE_AMENDMENT_THREE, 'Amendment 3'),
        (PRODUCT_TYPE_WITHHOLDINGS_ADJUSTMENT, 'Withholdings Adjustment'),
        (PRODUCT_TYPE_ADVISORY, 'Advisory'),
        (PRODUCT_TYPE_REJECT_CORRECTION, 'Reject Correction'),
        (PRODUCT_TYPE_PAPER_FILING, 'Paper Filing'),
    ]

    

    # Product Attributes
    tax_year = models.ForeignKey(TaxYear, related_name = "products", on_delete = models.CASCADE)
    product_type = models.CharField(max_length = 100, choices = PRODUCT_TYPE_CHOICES, default = PRODUCT_TYPE_DEFAULT, null = True, blank = True)
    is_product_active = models.BooleanField(default = False)
    default_price = models.DecimalField(max_digits = 10, decimal_places = 2, default = 0.0, validators = [MinValueValidator(0)])
    
    #vv Likely to remove the following section below vv
    #discount = models.DecimalField(max_digits = 10, decimal_places = 2, default = 0.0)
    #fee = models.DecimalField(max_digits = 10, decimal_places = 2, default = 0.0)

    # Function to autocalculate fee when a product object is saved
    #def save(self, *args, **kwargs):
    #    self.fee = self.default_price - self.discount
    #    super().save(*args, **kwargs)
    #^^ Likely to remove the following section above ^^


    class Meta:
        unique_together = ('tax_year', 'product_type')
        

    def __str__(self):
        return f"{self.product_type} ({self.tax_year.year})"

'''
# Relational class assigns a product for a specific client/tax_year to a preparer
# Likely that this will be used to calculate tax preparer compensation and other stats
class TaxPreparerAssignment(models.Model):
    product = models.ForeignKey(Product, related_name = 'assignments', on_delete = models.CASCADE)
    tax_preparer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name = 'product_assignments', on_delete = models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add = True)
    notes = models.TextField(null = True, blank = True)

    class Meta:
        indexes = [
            models.Index(fields = ['tax_preparer', 'product'])
        ]

    def __str__(self):
        return f"{self.product.tax_year} {self.product} : {self.tax_preparer.username}"
''' 

# Relational class to show which clients are on Intake
class Intake(models.Model):
    
    # Intake Attributes
    client = models.ForeignKey(Client, on_delete = models.CASCADE, related_name = 'intakes')
    tax_season = models.ForeignKey(TaxSeason, on_delete = models.PROTECT, related_name = 'intakes')
    added_at = models.DateTimeField(auto_now_add = True)
    is_active = models.BooleanField(default = False)        # This boolean tracks if client is in intake

    is_archived = models.BooleanField(default = False)  # NOTE: once archived data becomes frozen

    class Meta:
        unique_together = ('client', 'tax_season') # enforce one intake per client per tax season
        # Used to help make django admin panel more readable
        verbose_name = 'Intake'
        verbose_name_plural = 'Intakes'
        # Performance boost for indexing by tax season
        indexes = [
            models.Index(fields = ['client', 'tax_season'])
        ]

    def __str__(self):
        return f"{self.client.name} - Intake {self.tax_season.year}"
    

# Relational class to show acknowledgments for each clients
class Acknowledgment(models.Model):
    STATUS_DEFAULT = 'TBD'
    STATUS_ACCEPTED = 'A'
    STATUS_REJECTED = 'R'
    STATUS_PAPER_FILED = 'PAPER FILED'
    STATUS_CHOICES = [
        (STATUS_DEFAULT, 'TBD'),
        (STATUS_ACCEPTED, 'A'),
        (STATUS_REJECTED, 'R'),
        (STATUS_PAPER_FILED, 'PAPER FILED'),
    ]
    
    # General Acknowledgement Attributes
    created_at = models.DateTimeField(auto_now_add = True) # Timestamp to differentiate between rejects and acceptances
    is_archived = models.BooleanField(default = False, help_text = "True if this acknowledgment is beyond the active IRS e-file window and part of an archived season.")
    tax_season = models.ForeignKey(TaxSeason, on_delete = models.PROTECT, related_name = 'acknowledgments')
    description = models.TextField(null = True, blank = True) # raw or parsed text from the acknowledgment report
    
    # Attributes associated with Drake E-acknowledgments
    year = models.PositiveSmallIntegerField(null = True, blank = True,validators = [validate_tax_year], help_text = "Year to which the Acknowledment is for")
    client_tin = models.CharField(max_length = 9, null = True, blank = True, validators = [validate_TIN], help_text = "TIN as reported in the ACK file (IDNumber).")
    client_name = models.CharField(max_length = 50, null = True, blank = True, help_text = "Name of client to which acknowledgment belongs")
    type = models.CharField(max_length = 15, null = True, blank = True, help_text = "Form being acknowledged")
    date = models.DateField(null = True, blank = True, help_text = "Official date of acknowledgment from government")
    status = models.CharField(max_length = 15, choices = STATUS_CHOICES, default = STATUS_DEFAULT, null = True, blank = True) # Shows status of acknowledgment (recall that every acknowledgment object will have its own ID as well)
    submission_id = models.CharField(max_length = 64, null = True, blank = True, help_text = "Drake MEF SubmissionId for this transmission.")
    reject_code = models.CharField(max_length = 32, null = True, blank = True, help_text = "Drake reject code from the data row or Error Detail block.")
    reject_reason = models.TextField(null = True, blank = True, help_text = "Reject message from the Drake Error Detail block.")
    product_assignment = models.ForeignKey("ProductAssignment", on_delete = models.PROTECT, related_name = "acknowledgments", null = True, blank = True)

    # TODO: deprecate the Acknowledgment.product attribute when Acknowledgment.ProductAssignment is stable during Ack : PA matching
    product = models.ForeignKey(Product, on_delete = models.CASCADE, related_name = 'acknowledgments')
    
    # NOTE: May need to include a fee attribute. Consider allowing the Owner role to set fees from appropriate module

    class Meta:
        indexes = [
            models.Index(fields = ['tax_season', 'year', 'date']),
            models.Index(fields = ['client_tin']),
        ]
    
    @property
    def tax_year(self):
        return self.year
    
    def __str__(self):
        return f"{self.status} | {self.year} {self.type} | {self.client_name} ({self.client_tin})"
    

# Relational class to show which clients are on Daily Clearing
class DailyClearing(models.Model):

    # Clearing Attributes
    client = models.ForeignKey(Client, on_delete = models.CASCADE, related_name = 'daily_clearings')
    tax_season = models.ForeignKey(TaxSeason, on_delete = models.PROTECT, related_name = 'daily_clearings')
    added_at = models.DateTimeField(auto_now_add = True)
    is_active = models.BooleanField(default = False)    # This boolean tracks if client is in daily clearing

    is_archived = models.BooleanField(default = False)  # NOTE: once archived data becomes frozen

    class Meta:
        unique_together = ('client', 'tax_season')
        indexes = [
            models.Index(fields = ['client', 'tax_season'])
        ]

    def __str__(self):
        return f"{self.client.name} - Daily Clearing {self.tax_season.year}"


# FilingType Model
class FilingType(models.Model):
    # Tuple for Client's filing type
    FILING_TYPE_DEFAULT = 'TBD'
    FILING_TYPE_SIMPLE = 'Simple'
    FILING_TYPE_CREDITS = 'Credits'
    FILING_TYPE_ITEMIZING = 'Itemizing'
    FILING_TYPE_SOLE_PROP = 'Sole Proprietor'
    FILING_TYPE_CORPORATION = 'Corporation' 
    FILING_TYPE_CHOICES = [
        (FILING_TYPE_DEFAULT, 'TBD'),
        (FILING_TYPE_SIMPLE, 'Simple'),
        (FILING_TYPE_CREDITS, 'Credits'),
        (FILING_TYPE_ITEMIZING, 'Itemizing'),
        (FILING_TYPE_SOLE_PROP, 'Sole Proprietor'),
        (FILING_TYPE_CORPORATION, 'Corporation'),
    ]

    filing_type = models.CharField(max_length = 100, choices = FILING_TYPE_CHOICES, default = FILING_TYPE_DEFAULT, null = True, blank = True)

    def __str__(self):
        return self.filing_type


# ========== PRODUCT ASSIGNMENT FACTORY ========== #
class ProductAssignmentManager(models.Manager):
    def create_product_assignment(self, *, client, intake, tax_year, filing_type, product = None, preparer = None, is_active = True, **overrides):
        # logic for product assignment factory
        if product is None:
            product, _ = Product.objects.get_or_create(
                tax_year = tax_year, 
                product_type = Product.PRODUCT_TYPE_DEFAULT, 
                defaults = {'is_product_active': False})
        
        create_defaults = {
            'is_active': is_active,
            'completion_state': CompletionState.OPEN,
            'parser_status': ParserStatus.NOT_STARTED,
            'is_complete': False,
            'is_archived': False,
            'payment_method': ProductAssignment.PAYMENT_METHOD_DEFAULT,
            'preparer': preparer,
        }
        if 'fee' not in overrides and product is not None:
            from decimal import Decimal
            create_defaults['fee'] = Decimal(str(product.default_price))
        create_defaults.update(overrides)

        product_assignment, created = self.get_or_create(
            client = client, 
            product = product, 
            filing_type = filing_type, 
            tax_year = tax_year, 
            intake = intake, 
            defaults = create_defaults,
        )

        # activate PA if using existing one
        if not created and is_active and not product_assignment.is_active:
            product_assignment.is_active = True
            product_assignment.save(update_fields = ['is_active'])
        
        return product_assignment, created
    

class LifecycleState(models.TextChoices):
    IN_CLEARING = "IN_CLEARING", "In Clearing"
    CLEARING_COMPLETE = "CLEARING_COMPLETE", "Clearing Complete"
    AWAITING_PAYMENT = "AWAITING_PAYMENT", "Awaiting Payment"
    READY_FOR_REVIEW = "READY_FOR_REVIEW", "Ready for Review"
    IN_REVIEW = "IN_REVIEW", "In Review"
    FILED = "FILED", "Filed"
    ACK_RECONCILING = "ACK_RECONCILING", "Ack Reconciling"
    CLOSED = "CLOSED", "Closed"
    PENDING_REJECT_CORRECTION = "PENDING_REJECT_CORRECTION", "Pending Reject Correction"


# PA Helper model
# When PA is marked as 'complete' by user, then completion workflow is initiated
# Completion workflow is essential to ensure that acknowledgments may be appropriately matched to a PA
# Deprecated: use LifecycleState + core/workflows/lifecycle.py for new work.
class CompletionState(models.TextChoices):
    OPEN = "OPEN", "Open"
    PENDING_PARSER = "PENDING_PARSER", "Pending Parser"
    PARSER_RUNNING = "PARSER_RUNNING", "Parser Running"
    PARSER_DONE = "PARSER_DONE", "Parser Done"
    PARSER_SKIPPED = "PARSER_SKIPPED", "Parser Skipped"
    PENDING_ACK_COUNT = "PENDING_ACK_COUNT", "Pending Ack Count"
    READY_TO_COMPLETE = "READY_TO_COMPLETE", "Ready to Complete"
    COMPLETED = "COMPLETED", "Completed"
    
# A parser may be leveraged during the completion workflow
class ParserStatus(models.TextChoices): 
    NOT_STARTED = "NOT_STARTED", "Not Started"
    SKIPPED = "SKIPPED", "Skipped"
    DONE = "DONE", "Done"
class ProductAssignment(models.Model):

    # Tuple of payment methods
    PAYMENT_METHOD_DEFAULT = 'TBD'
    PAYMENT_METHOD_TPG = 'TPG'
    PAYMENT_METHOD_QBO = 'QBO'
    PAYMENT_METHOD_CASH = 'CASH'
    PAYMENT_METHOD_SQUARE = 'SQUARE'
    PAYMENT_METHOD_CHECK = 'CHECK'
    PAYMENT_METHOD_OTHER_APPLICATION = 'OTHER APPLICATION'
    PAYMENT_METHOD_NO_FEE_PRO_BONO = 'NO FEE - PRO BONO'
    PAYMENT_METHOD_NO_FEE_DEPENDENT = 'NO FEE - DEPENDENT'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_DEFAULT, ''),
        (PAYMENT_METHOD_TPG, 'TPG'),
        (PAYMENT_METHOD_QBO, 'QBO'),
        (PAYMENT_METHOD_CASH, 'CASH'),
        (PAYMENT_METHOD_SQUARE, 'SQUARE'),
        (PAYMENT_METHOD_CHECK, 'CHECK'),
        (PAYMENT_METHOD_OTHER_APPLICATION, 'OTHER APPLICATION'),
        (PAYMENT_METHOD_NO_FEE_PRO_BONO, 'NO FEE - PRO BONO'),
        (PAYMENT_METHOD_NO_FEE_DEPENDENT, 'NO FEE - DEPENDENT'),
    ]


    is_active = models.BooleanField(default = False)
    is_complete = models.BooleanField(
        default = False,
        help_text = "Legacy billing/clearing flag. Do not set from lifecycle commands; Phase 6 moves billing to lifecycle_state.",
    )
    is_archived = models.BooleanField(default = False, help_text = "True if assignment belongs to an archived tax season.")

    preparer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.SET_NULL, null = True, blank = True, limit_choices_to = {'role': 'tax_preparer'}, related_name = 'assigned_product_assignments' )
    client = models.ForeignKey(Client, on_delete = models.CASCADE, related_name = 'product_assignments')
    product = models.ForeignKey(Product, on_delete = models.CASCADE, related_name = 'product_assignments')
    filing_type = models.ForeignKey(FilingType, on_delete = models.PROTECT, related_name = 'product_assignments', null = True, blank = True)  # NOTE: remove null and blank fields after development, when you are SURE that every Product Assignment does in fact have a default filing type.
    tax_year = models.ForeignKey(TaxYear, on_delete = models.CASCADE, related_name = 'product_assignments')
    intake = models.ForeignKey(Intake, on_delete = models.CASCADE, related_name = 'product_assignments')
    payment_method = models.CharField(max_length = 20, choices = PAYMENT_METHOD_CHOICES, default = PAYMENT_METHOD_DEFAULT, null = True, blank = True)
    
    # NOTE: include the fee and discount attributes when ready to handle billing and payments
    fee = models.DecimalField(max_digits = 10, decimal_places = 2, null = True, blank = True, validators = [MinValueValidator(0)])
    discount = models.DecimalField(max_digits = 10, decimal_places = 2, null = True, blank = True, validators = [MinValueValidator(0)])
    
    lifecycle_state = models.CharField(
        max_length = 32,
        choices = LifecycleState.choices,
        null = True,
        blank = True,
        help_text = "Authoritative workflow state. Set to IN_CLEARING when client enters daily clearing.",
    )

    # Deprecated: legacy completion wizard (parser → ack count → COMPLETED).
    completion_state = models.CharField(max_length = 30, choices = CompletionState.choices, default = CompletionState.OPEN, null = True, blank = True)
    parser_status = models.CharField(max_length = 20, choices = ParserStatus.choices, default = ParserStatus.NOT_STARTED, null = True, blank = True)
    expected_ack_count = models.PositiveSmallIntegerField(
        null = True,
        blank = True,
        help_text = "Staff-set count of expected Drake acks (federal + state forms). Required before CLOSED.",
    )
    force_completed_at = models.DateTimeField(
        null = True,
        blank = True,
        help_text = "When set, PA was force-closed despite reject acks; counts as A for TP Comp Dt.",
    )
    completed_at = models.DateTimeField(null = True, blank = True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.SET_NULL, null = True, blank = True, related_name = "completed_product_assignments") # TODO: make sure this points to my InternalUser model in Accounts module
    closing_message_text = models.TextField(null = True, blank = True)

    # Parser linkage (CRM snapshots only; full jobs live in pdf_manager DB — Phase 4).
    parse_job_uuid = models.UUIDField(null = True, blank = True, db_index = True)
    parse_result_json = models.JSONField(null = True, blank = True)
    parsed_at = models.DateTimeField(null = True, blank = True)
    parser_output_refs = models.JSONField(
        null = True,
        blank = True,
        help_text='List of {"kind": "main_packet"|..., "path": "..."} references to parser output files.',
    )

    class VoidReason(models.TextChoices):
        PDF_REPLACED = "PDF_REPLACED", "PDF replaced via global upload"

    voided_at = models.DateTimeField(null = True, blank = True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
        related_name = "voided_product_assignments",
    )
    void_reason = models.CharField(
        max_length = 32,
        choices = VoidReason.choices,
        null = True,
        blank = True,
    )
    superseded_by = models.ForeignKey(
        "self",
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
        related_name = "supersedes",
    )

    # for product assignment manager
    objects = ProductAssignmentManager()

    # save PA after certain updates
    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields", None)

        # ==== auto calculate discount ==== #
        new_discount = None

            # determine if discount based on fee conditions
        if self.fee is not None:
            default_price = Decimal(str(self.product.default_price or 0))
            fee = Decimal(str(self.fee))
            new_discount = (default_price - fee) if fee < default_price else None

            # if discount changed, include in update_fields
        if new_discount != self.discount:
            self.discount = new_discount
            if update_fields is not None:
                # make a set and add set to list
                uf = set(update_fields)
                uf.add("discount")
                kwargs["update_fields"] = list(uf)
        
        super().save(*args, **kwargs)


    # calculate payment status
    @property
    def payment_status(self) -> str:
        """
        Returns: "", "TBD", "Pending", "Paid"
        """
        pm = (self.payment_method or "").strip()

        # default payment_status state
        if pm == "":
            return ""
        
        # payment_status = TBD
        if pm == self.PAYMENT_METHOD_DEFAULT:
            return "TBD"
        
        # payment_status = Paid
        always_paid = {
            self.PAYMENT_METHOD_CASH,
            self.PAYMENT_METHOD_CHECK,
            self.PAYMENT_METHOD_NO_FEE_DEPENDENT,
            self.PAYMENT_METHOD_NO_FEE_PRO_BONO,
            self.PAYMENT_METHOD_OTHER_APPLICATION,
            self.PAYMENT_METHOD_SQUARE,
            self.PAYMENT_METHOD_TPG,
        }
        if pm in always_paid:
            return "Paid"
        
        # invoice state determines PA payment_status
        if pm == self.PAYMENT_METHOD_QBO:
            # avoid importing billing models directly (prevents circular import headaches)
            AssignmentInvoiceLink = apps.get_model("billing", "AssignmentInvoiceLink")

            link = AssignmentInvoiceLink.objects.select_related("invoice").filter(product_assignment_id = self.id).first()
            if not link or not link.invoice:
                return "Pending"
            
            return "Paid" if link.invoice.is_paid else "Pending"
        
        return "TBD"    # this is a fallback (not expected to use this)

#   NOTE: Meta class to enforce a single product assignment per client/tax_year/product (constraint only applies to active product assignments)
    class Meta:
        constraints = [
            UniqueConstraint(
                fields = ['client', 'intake', 'tax_year', 'product'],
                condition = Q(is_active = True),
                name = 'uniq_active_client_intake_taxyear_product',
            ),
        ]
        

    def __str__(self):
        status = 'Complete' if self.is_complete else 'Pending'
        return f"{self.client.name} - Product Assignment : {self.intake.tax_season} {self.product.product_type} {self.tax_year.year} [{status}]"


class PaperFilingDetail(models.Model):
    """Manual paper-filing metadata per jurisdiction (W5)."""

    JURISDICTION_FEDERAL = "federal"
    JURISDICTION_STATE = "state"
    JURISDICTION_CHOICES = [
        (JURISDICTION_FEDERAL, "Federal"),
        (JURISDICTION_STATE, "State"),
    ]

    MAILED_BY_FIRM = "firm"
    MAILED_BY_CLIENT = "client"
    MAILED_BY_CHOICES = [
        (MAILED_BY_FIRM, "Firm"),
        (MAILED_BY_CLIENT, "Client"),
    ]

    product_assignment = models.ForeignKey(
        ProductAssignment,
        on_delete=models.CASCADE,
        related_name="paper_filing_details",
    )
    jurisdiction = models.CharField(max_length=16, choices=JURISDICTION_CHOICES)
    form_type = models.CharField(max_length=15, help_text="Form code (1040, CA540, …)")
    mailed_by = models.CharField(max_length=16, choices=MAILED_BY_CHOICES)
    sent_date = models.DateField()
    tracking = models.CharField(max_length=64, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paper_filing_details",
    )

    class Meta:
        ordering = ["sent_date", "id"]

    def __str__(self):
        return f"{self.form_type} paper filed {self.sent_date}"


class Appointment(models.Model):

    # Tuple for appointment types
    APPOINTMENT_TYPE_DEFAULT = ''
    APPOINTMENT_TYPE_DROP_OFF = 'Drop Off'
    APPOINTMENT_TYPE_OFFICE = 'Office'
    APPOINTMENT_TYPE_ONLINE = 'Online'
    APPOINTMENT_TYPE_TBD = 'TBD'
    APPOINTMENT_TYPE_CHOICES = [
        (APPOINTMENT_TYPE_DEFAULT, ''),
        (APPOINTMENT_TYPE_DROP_OFF, 'Drop Off'),
        (APPOINTMENT_TYPE_OFFICE, 'Office'),
        (APPOINTMENT_TYPE_ONLINE, 'Online'),
        (APPOINTMENT_TYPE_TBD, 'TBD'),
    ]

    STATUS_DEFAULT_TBD = 'TBD'
    STATUS_SCHEDULED = 'Scheduled'
    STATUS_COMPLETED = 'Completed'
    STATUS_CANCELLED = 'Cancelled'
    STATUS_CHOICES = [
        (STATUS_DEFAULT_TBD, 'TBD'),
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),

    ]
    is_active = models.BooleanField(default = False)

    product_assignment = models.OneToOneField(ProductAssignment, on_delete = models.CASCADE, related_name = 'appointment')
    appointment_type = models.CharField(max_length = 20, choices=APPOINTMENT_TYPE_CHOICES, default=APPOINTMENT_TYPE_DEFAULT)
    preparer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null = True, blank = True, related_name = 'appointments')
    scheduled_datetime = models.DateTimeField(null = True, blank = True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default = STATUS_DEFAULT_TBD)
    notes = models.TextField(blank = True)

    created_at = models.DateTimeField(auto_now_add = True)

    def __str__(self):
        return f"Appointment for {self.product_assignment.client.name} {self.product_assignment.tax_year.year} {self.product_assignment.product.product_type}"
    

# ============== Acknowledgment Helper Models ============== #
# AckStaging used to map Acknowledgments to their respective ProductAssignments
class AckStaging(models.Model):
    MATCH_MATCHED = "MATCHED"
    MATCH_UNMATCHED = "UNMATCHED"
    MATCH_AMBIGUOUS = "AMBIGUOUS"
    MATCH_DECLINED = "DECLINED"
    MATCH_NEEDS_FILING_TYPE = "NEEDS_FILING_TYPE"
    MATCH_CLIENT_NOT_FOUND = "CLIENT_NOT_FOUND"
    MATCH_CHOICES = [
        (MATCH_MATCHED, "Matched"),
        (MATCH_UNMATCHED, "Unmatched"),
        (MATCH_AMBIGUOUS, "Ambiguous"),
        (MATCH_DECLINED, "Declined"),
        (MATCH_NEEDS_FILING_TYPE, "Needs Filing Type"),
        (MATCH_CLIENT_NOT_FOUND, "Client Not Found"),
    ]

    created_at = models.DateTimeField(auto_now_add = True)

    # raw parsed fields from Drake acknowledgment
    year = models.PositiveSmallIntegerField(null = True, blank = True, validators = [validate_tax_year])
    client_tin = models.CharField(max_length = 9, null = True, blank = True, validators = [validate_TIN])
    client_name = models.CharField(max_length = 50, null = True, blank = True)
    type = models.CharField(max_length = 15, null = True, blank = True)
    date = models.DateField(null = True, blank = True)
    status = models.CharField(max_length = 15, null = True, blank = True)
    submission_id = models.CharField(max_length = 64, null = True, blank = True)
    reject_code = models.CharField(max_length = 32, null = True, blank = True)
    reject_reason = models.TextField(null = True, blank = True)

    # matching / resolution
    match_state = models.CharField(max_length = 30, choices = MATCH_CHOICES, default = MATCH_UNMATCHED)
    reason = models.TextField(null = True, blank = True)
    expected_ack_count = models.PositiveSmallIntegerField(null = True, blank = True)

    suggested_product_type = models.CharField(max_length = 100, null = True, blank = True)
    suggested_tax_season_year = models.PositiveIntegerField(null = True, blank = True)

    resolved_product_assignment = models.ForeignKey(
        "ProductAssignment",
        on_delete = models.SET_NULL,
        null = True,
        blank = True,
        related_name = "resolved_ack_staging_rows",
    )

    class Meta:
        indexes = [
            models.Index(fields = ["match_state", "year", "date"]),
            models.Index(fields = ["client_tin"]),
        ]
    
    def __str__(self):
        return f"{self.match_state} | {self.year} {self.type} | {self.client_name} {self.client_tin}"


# Model used to ensure that PA finalization (invoicing etc etc) is idempotent
class LifecycleTransition(models.Model):
    """Append-only audit log for lifecycle_state changes (analytics / troubleshooting)."""

    product_assignment = models.ForeignKey(
        "ProductAssignment",
        on_delete = models.CASCADE,
        related_name = "lifecycle_transitions",
    )
    from_state = models.CharField(max_length = 32, blank = True, default = "")
    to_state = models.CharField(max_length = 32, choices = LifecycleState.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null = True,
        blank = True,
        on_delete = models.SET_NULL,
        related_name = "lifecycle_transitions",
    )
    created_at = models.DateTimeField(default = timezone.now, db_index = True)
    note = models.TextField(blank = True, default = "")
    payload = models.JSONField(null = True, blank = True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields = ["product_assignment", "created_at"], name = "core_lifecy_product_6e8f0d_idx"),
            models.Index(fields = ["to_state", "created_at"], name = "core_lifecy_to_stat_8a1b2c_idx"),
        ]

    def __str__(self):
        return f"PA {self.product_assignment_id}: {self.from_state or '(none)'} → {self.to_state}"


class ProductAssignmentEvent(models.Model):
    class EventType(models.TextChoices):
        PA_COMPLETED = "PA_COMPLETED", "PA_COMPLETED"
        CLEARING_COMPLETED = "CLEARING_COMPLETED", "CLEARING_COMPLETED"
        READY_FOR_REVIEW = "READY_FOR_REVIEW", "READY_FOR_REVIEW"
        FILED = "FILED", "FILED"
        CLOSED = "CLOSED", "CLOSED"
        PARSE_SUPERSEDED = "PARSE_SUPERSEDED", "PARSE_SUPERSEDED"

    product_assignment = models.ForeignKey(
        "ProductAssignment",
        on_delete=models.CASCADE,
        related_name = "events",
    )

    event_type = models.CharField(max_length = 64, choices = EventType.choices)
    created_at = models.DateTimeField(default = timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null = True,
        blank = True,
        on_delete = models.SET_NULL,
        related_name = "product_assignment_events",
    )
    payload = models.JSONField(null = True, blank = True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields = ["product_assignment", "event_type"],
                name = "uniq_pa_event_type",
            )
        ]