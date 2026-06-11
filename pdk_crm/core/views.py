from django.db import IntegrityError, transaction
from django.shortcuts import render, get_object_or_404
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from decimal import Decimal

from .models import (
    Client, TaxYear, Product, Intake, 
    DailyClearing, ProductAssignment, FilingType, 
    Acknowledgment, Appointment, AckStaging, 
    CompletionState, ParserStatus,
)
from .workflows.completion import (
    FROZEN_FIELDS_ON_COMPLETION_START,
    transition_pa,
    cmd_start_completion,
    cmd_skip_parser,
    cmd_begin_ack_count,
    cmd_set_expected_ack_count,
    cmd_finalize_completion,
    cmd_cancel_completion,
    can_autosave_pa_field,
)

from .utils import (
    DUPLICATE_ACTIVE_PA_MESSAGE,
    active_product_assignment_conflict,
    get_or_create_intake,
    get_or_create_product_assignment_for_tax_year,
)
from accounts.models import InternalUser

import json
import re

@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def home_view(request): # order of dictionary determines order in which icon buttons appear on home page
    apps = [
        {"name": "Home", "icon": "icons/home.svg", "url": "core:home"},
        {"name": "Calendar", "icon": "icons/calendar.svg", "url": "pdk_calendar:pdk_calendar"},
        {"name": "Intake", "icon": "icons/intake.svg", "url": "intake:intake"},
        {"name": "Clearing", "icon": "icons/clearing.svg", "url": "clearing:clearing"},
        {"name": "Billing", "icon": "icons/billing.svg", "url": "billing:billing"},
        {"name": "Review", "icon": "icons/review.svg", "url": "review:review"},
        {"name": "Acknowledgments", "icon": "icons/acknowledgments.svg", "url": "acknowledgments:acknowledgments"},
        {"name": "Client Portfolio", "icon": "icons/client_portfolio.svg", "url": "client_portfolio:client_portfolio"},
    ]
    from analytics.permissions import user_can_access_analytics

    if user_can_access_analytics(request.user):
        apps.insert(
            -1,
            {"name": "Analytics", "icon": "icons/analytics.svg", "url": "analytics:analytics"},
        )
    return render(request, "core/home.html", {"apps": apps})


@login_required
@require_POST
def update_rotate_background(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)

    if "rotate_background" not in data:
        return JsonResponse({"status": "error", "message": "Missing rotate_background."}, status=400)

    rotate_background = bool(data["rotate_background"])
    user = request.user
    user.rotate_background = rotate_background
    user.save(update_fields=["rotate_background"])

    from core.backgrounds import (
        FIXED_BACKGROUND_KEY,
        SESSION_BACKGROUND_KEY,
        SESSION_DATE_KEY,
        get_background,
        sync_session_background,
    )

    if not rotate_background:
        request.session.pop(SESSION_DATE_KEY, None)
        request.session.pop(SESSION_BACKGROUND_KEY, None)

    key = sync_session_background(request)
    background = get_background(key)
    return JsonResponse(
        {
            "status": "success",
            "rotate_background": rotate_background,
            "app_background_key": background.key,
            "app_background_static": background.static_path,
            "fixed_background_key": FIXED_BACKGROUND_KEY,
        }
    )


# Auto Save : general autosave feature
@login_required
@require_POST
def auto_save(request):
    try:
        data = json.loads(request.body)
        model_name = data.get('model', 'client').lower()    # Defaults to Client
        object_id = data.get("id")
        field = data.get("field")
        value = data.get("value")

        # Validate inputs
        if not object_id or not field:
            return JsonResponse({'status': 'error', 'message': 'Missing required data.'}, status = 400)
        
        # Model Dispatch Pattern
        model_map = {
            'client': (Client, ['name', 'TIN', 'phone', 'email', 'filing_type', 'prior_filing_type', 'appointment_type']),  # 'tax_year' was removed from this line... may consider adding back if needed
            'tax_year': (TaxYear, ['year', 'balance']),
            'product': (Product, ['product_type', 'default_price']),
            'intake': (Intake, ['is_active']),
            'daily_clearing': (DailyClearing, ['is_active']),
            'appointment': (Appointment, ['appointment_type', 'preparer'])
        }

        # Ensure field is editable
        if model_name not in model_map:
            return JsonResponse({'status': 'error', 'message': 'Unsupported model.'}, status = 400)
        
        ModelClass, allowed_fields = model_map[model_name]
        instance = get_object_or_404(ModelClass, id = object_id)

        # Security guardrails: validate field
        if field not in allowed_fields:
            return JsonResponse({'status': 'error', 'message': f'Editing {field} is not allowed.'}, status = 403)
        
        # Handle type conversion if needed
        field_type = instance._meta.get_field(field).get_internal_type()
        
        # special handling of appointment fields
        if model_name == 'appointment':
            if field == 'preparer':
                try:
                    preparer = InternalUser.objects.get(id = int(value))
                    setattr(instance, field, preparer)
                except InternalUser.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Invalid preparer ID'}, status = 400)
            else:
                setattr(instance, field, value)
        
        # special handling all other fields
        else:
            if model_name == 'client' and field == 'tax_year':
                try:
                    value = TaxYear.objects.get(year = int(value))
                except TaxYear.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': f'TaxYear {value} not found.'}, status = 404)
            elif field_type in ['IntegerField', 'SmallIntegerField']:
                value = int(value)
            elif field_type in ['DecimalField', 'FloatField']:
                value = float(value)
            elif field_type == 'BooleanField':
                value = str(value).lower() in ['true', '1', 'yes']
            else:
                value = str(value)

            setattr(instance, field, value)
        
        # validate and save
        instance.full_clean() # Run validators
        instance.save()

        return JsonResponse({'status': 'success', 'message': f'{model_name}.{field} updated.'})
    
    except ModelClass.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': f'{model_name.capitalize()} not found.'}, status = 404)
    except ValidationError as ve:
        return JsonResponse({'status': 'error', 'message': ve.message_dict}, status = 400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)
    

# AUTO SAVE TAX YEAR
'''
def auto_save_tax_year(request):
    try:
        data = json.loads(request.body)
        product_id = data.get('id')
        year_value = data.get('value')

        # vaidate input
        if not product_id:
            return JsonResponse({'status': 'error', 'message': 'Missing product ID.'}, status = 400)
        
        # get product
        product = get_object_or_404(Product, id = product_id)

        # case: user cleared the field
        if year_value == "":
            product.tax_year = None
            product.full_clean()
            product.save()
            return JsonResponse({'status': 'success', 'message': 'TaxYear cleared.'})
        
        # try to parse year input
        try:
            year_int = int(year_value)
        except ValueError:
            return JsonResponse({'status': 'error', 'message': 'Invalid year format.'}, status = 400)
        
        # determine the associated client
        if product.tax_year:
            client = product.tax_year.client
        else: 
            try:
                client = product.intake.client
            except ObjectDoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Client could not be determined from product.'}, status = 400)
        
        # get or create TaxYear for that client
        tax_year_obj, created = TaxYear.objects.get_or_create(client = client, year = year_int)

        # asign new tax year to product
        product.tax_year = tax_year_obj
        product.full_clean()
        product.save()

        return JsonResponse({'status': 'success', 'message': 'TaxYear updated.'})
    
    except ValidationError as ve:
        return JsonResponse({'status': 'error', 'message': ve.message_dict}, status = 400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)
'''
        

# Auto Save : Product Assignment
@require_POST
@login_required
def auto_save_product_assignment(request):
    try:
        data = json.loads(request.body)
        pa_id = data.get("id")      # product_assignment_id
        product_assignment_appointment_id = data.get("id")
        field = data.get("field")
        value = data.get("value")

        if not pa_id or not field:
            return JsonResponse({"status": "error", "message": "Missing id or field."}, status = 400)
        
         # helper function to remove duplicate code and make tax_year and product branches consistent
        def _activate_new_deactivate_old(*, old_product, new_product, pa_id: int):
            if new_product and not new_product.is_product_active:
                new_product.is_product_active = True
                new_product.save(update_fields = ["is_product_active"])
            
            if old_product and old_product != new_product:
                still_used = (ProductAssignment.objects.filter(product = old_product).exclude(id = pa_id).exists())
                if not still_used and old_product.is_product_active:
                    old_product.is_product_active = False
                    old_product.save(update_fields = ["is_product_active"])


        with transaction.atomic():
            #Step 1: lock row
            #pa = ProductAssignment.objects.select_for_update().get(id = pa_id)
            
            #Step 2: re-fetch with joins for business logic
            product_assignment = (ProductAssignment.objects.select_for_update().get(id = pa_id))    # NOTE: Previous line : product_assignment = (ProductAssignment.objects.select_for_update().select_related(None).get(id = pa_id))

            # gate
            decision = can_autosave_pa_field(product_assignment, field)
            if not decision.allowed:
                return JsonResponse({"status": "error", "code": "PA_FROZEN", "message": decision.reason}, status = 409)
            
            # NOTE: Temporary dev check
            print(f"Updating {field} to {value} for ProductionAssignment ID {pa_id}")


            # If updated field is tax year, update tax year
            if field == "tax_year":
                try:
                    year_int = int(value)
                except (TypeError, ValueError):
                    return JsonResponse({"status": "error", "message": "Invalid year format."}, status = 400)
                
                client = product_assignment.client
                old_product = product_assignment.product

                tax_year, _ = TaxYear.objects.get_or_create(client = client, year = year_int)
                product_assignment.tax_year = tax_year

                for pt, _label in Product.PRODUCT_TYPE_CHOICES:
                    Product.objects.get_or_create(tax_year = tax_year, product_type = pt, defaults = {"is_product_active": False})
            
                # choose product_type: prefer payload, fallback to current product's type
                product_type = (data.get("product_type") or "").strip()
                if not product_type:
                    product_type = (old_product.product_type if old_product else Product.PRODUCT_TYPE_DEFAULT)

                matching_product, _ = Product.objects.get_or_create(
                    tax_year = tax_year,
                    product_type = product_type,
                    defaults = {"is_product_active": False},
                )

                product_assignment.product = matching_product

                if active_product_assignment_conflict(
                    client=product_assignment.client,
                    intake=product_assignment.intake,
                    tax_year=tax_year,
                    product=matching_product,
                    exclude_pa_id=product_assignment.id,
                ):
                    return JsonResponse(
                        {
                            "status": "error",
                            "code": "DUPLICATE_PA",
                            "message": DUPLICATE_ACTIVE_PA_MESSAGE,
                        },
                        status=409,
                    )

                _activate_new_deactivate_old(
                    old_product = old_product,
                    new_product = matching_product,
                    pa_id = product_assignment.id,
                )
                
                product_assignment.full_clean()
                product_assignment.save()

                # IMPORTANT: return refreshed product options for this PA row
                valid_products_qs = Product.objects.filter(tax_year = tax_year).order_by("product_type")
                valid_products = [{"id": p.id, "product_type": p.product_type} for p in valid_products_qs]

                return JsonResponse({
                    "status": "success",
                    "message": "tax_year updated.",
                    "updated": {
                        "tax_year": tax_year.year,
                        "product_id": matching_product.id,
                        "product_type": matching_product.product_type,
                    },
                    "valid_products": valid_products,
                })
            
            # If the updated field is product, update product
            elif field == "product":
                tax_year = product_assignment.tax_year
                if not tax_year:
                    return JsonResponse({'status': 'error', 'message': 'No tax year assigned to this product assignment.'}, status = 400)
                
                old_product = product_assignment.product
                
                try:
                    if isinstance(value, str) and value.startswith("__") and value.endswith("__"):
                        # handle placeholder format e.g. "__Advisory__"
                        selected_product_type = value.strip("__").strip()
                        if not selected_product_type:
                            return JsonResponse({"status": "error", "message": "Invalid product placeholder."}, status = 400)
                    else:
                        # standard case: product ID
                        product_id = int(value)
                        product_obj = Product.objects.get(id = product_id)
                        
                        # critical integrity check: never accept a product from another tax year
                        if product_obj.tax_year_id != tax_year.id:
                            return JsonResponse({"status": "error", "message": "Selected product does not belong to this tax year."}, status = 409)
                        
                        selected_product_type = product_obj.product_type

                    # lookup or create product for the current tax year and selected type
                    new_product, _ = Product.objects.get_or_create(tax_year = tax_year, product_type = selected_product_type, defaults = {"is_product_active": False})

                    product_assignment.product = new_product

                    if active_product_assignment_conflict(
                        client=product_assignment.client,
                        intake=product_assignment.intake,
                        tax_year=tax_year,
                        product=new_product,
                        exclude_pa_id=product_assignment.id,
                    ):
                        return JsonResponse(
                            {
                                "status": "error",
                                "code": "DUPLICATE_PA",
                                "message": DUPLICATE_ACTIVE_PA_MESSAGE,
                            },
                            status=409,
                        )

                    _activate_new_deactivate_old(
                        old_product = old_product,
                        new_product = new_product,
                        pa_id = product_assignment.id,
                    )

                
                except (Product.DoesNotExist, ValueError, TypeError) as e:
                    return JsonResponse({"status": "error", "message": f"Invalid product value: {value}. Details: {e}"}, status = 400)

                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "product updated.",
                    "updated": {
                        "product_id": product_assignment.product_id,
                        "product_type": product_assignment.product.product_type if product_assignment.product else "",
                    }
                })

            # If updated field is filing type, update filing type
            elif field == "filing_type":
                try:
                    filing_type_id = int(value)
                except (TypeError, ValueError):
                    return JsonResponse({"status": "error", "message": f"Invalid filing type ID: {value}"}, status = 400)
                
                filing_type_obj = FilingType.objects.filter(id = filing_type_id).first()
                if not filing_type_obj:
                    return JsonResponse({"status": "error", "message": f"Invalid filing type ID: {value}"}, status = 400)
                
                product_assignment.filing_type = filing_type_obj
                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "filing_type updated.",
                    "updated": {"filing_type": filing_type_obj.filing_type}
                })
                
            # if updated field is fee, update fee
            elif field == "fee":
                try:
                    fee_value = Decimal(str(value))
                except (TypeError, ValueError, ArithmeticError):
                    return JsonResponse({"status": "error", "message": "Invalid fee value."}, status = 400)
            
                if fee_value < 0:
                    return JsonResponse({"status": "error", "message": "Fee cannot be negative."}, status = 400)
                
                product_assignment.fee = fee_value
                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "fe updated.",
                    "updated": {"fee": str(fee_value)}
                })
                
            # if updated field is payment method, update payment method type
            elif field == "payment_method":
                pm = (str(value) if value is not None else "").strip()
                valid = dict(ProductAssignment.PAYMENT_METHOD_CHOICES)

                if pm not in valid:
                    return JsonResponse({"status": "error", "message": f"Invalid payment method: {pm}"}, status = 400)

                product_assignment.payment_method = pm
                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "payment_method_updated.",
                    "updated": {"payment_method": pm}
                })

            elif field == "preparer":
                try:
                    preparer_id = int(value)
                    preparer = InternalUser.objects.get(id=preparer_id)
                except (TypeError, ValueError, InternalUser.DoesNotExist):
                    return JsonResponse({"status": "error", "message": "Invalid preparer ID."}, status=400)

                product_assignment.preparer = preparer
                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "preparer updated.",
                    "updated": {"preparer_id": preparer.id},
                })

            elif field == "closing_message_text":
                product_assignment.closing_message_text = str(value) if value is not None else ""
                product_assignment.full_clean()
                product_assignment.save()

                return JsonResponse({
                    "status": "success",
                    "message": "closing_message_text updated.",
                })
            
            
            else:
                return JsonResponse({'status': 'error', 'message': 'Unsupported field.'}, status = 400)
        
    
    except ProductAssignment.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'ProductAssignment not found'}, status = 404)
    except IntegrityError:
        return JsonResponse(
            {
                "status": "error",
                "code": "DUPLICATE_PA",
                "message": DUPLICATE_ACTIVE_PA_MESSAGE,
            },
            status=409,
        )
    except ValidationError as ve:
        return JsonResponse({'status': 'error', 'message': ve.message_dict}, status = 400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)


# NOTE: May depricate if auto_save_product_assignment fully hanldes auto_save_product logic
# Auto Save Product : autosave product instance
'''
def auto_save_product(request):
    try:
        data = json.loads(request.body)
        intake_id = data.get('id')
        product_id = data.get('value')

        if not intake_id or not product_id:
            return JsonResponse({'status': 'error', 'message': 'Missing required data.'}, status = 400)
        
        intake = get_object_or_404(Intake, id = intake_id)
        product = get_object_or_404(Product, id = int(product_id))

        intake.product = product
        intake.full_clean()
        intake.save()

        return JsonResponse({'status': 'success', 'message': 'Product updated.'})
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)
'''

# NOTE: ONLY USE WHEN ARCHIVING A TAX SEASON (& CONTENTS)
def archive_tax_season(season):
    season.is_archived = True
    season.save()

    # mark related seasonal data
    Intake.objects.filter(tax_season = season).update(is_archived = True, is_active = False)
    DailyClearing.objects.filter(tax_season = season).update(is_archived = True, is_active = False)
    ProductAssignment.objects.filter(intake__tax_season = season).update(is_archived = True)

    # archive old acknowledgments (based on current tax year logic)
    current_year = season.year
    archive_cutoff = current_year - 2   # keep acknowledgments for 3 yrs
    Acknowledgment.objects.filter(tax_season = season, product__tax_year__lt = archive_cutoff).update(is_archived = True)


# Create new client from an Acknowledgment
# NOTE: useful if an acknowledgment is found, 
#  but for some reason the client was not already added into the database
def _normalize_tin(raw: str) -> str:
    """
    Normalize to 9-diogit numeric string (zero-padded).
    """
    s = (raw or "").strip()
    s = re.sub(r"\D", "", s)    # keep digits only
    if not s:
        return ""
    if len(s) < 9:
        s = s.zfill(9)
    return s


@require_POST
@login_required
def create_client_from_ack(request):
    """
    Payload example:
    {
        "tin": "000000001",
        "name": "Client 1",
        "email": "",
        "phone": "",
        "filing_type": "<optional value>",
        "prior_filing_type": "<optional value>"
    }
    """
    try:
        data = json.loads(request.body or "{}")

        staging_id = data.get("staging_id")
        tin = _normalize_tin(data.get("tin"))
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        phone = (data.get("phone") or "").strip()
        filing_type = (data.get("filing_type") or "").strip()
        prior_filing_type = (data.get("prior_filing_type") or "").strip()

        if not staging_id:
            return JsonResponse({"status": "error", "message": "staging_id is required."}, status = 400)
        if not tin:
            return JsonResponse({"status": "error", "message": "TIN is required."}, status = 400)
        if len(tin) != 9:
            return JsonResponse({"status": "error", "message": "TIN must be 9 digits."}, status = 400)
        if not name:
            return JsonResponse({"status": "error", "message": "Client name is required."}, status = 400)
        
        
        with transaction.atomic():
            st = AckStaging.objects.select_for_update().filter(id = staging_id).first()
            if not st:
                return JsonResponse({"status": "error", "message": "AckStaging row not found."}, status = 404)
            
            
            if st.match_state == AckStaging.MATCH_MATCHED and st.resolved_product_assignment_id:
                return JsonResponse({
                    "status": "success",
                    "message": "Staging row already resolved.",
                    "action": "noop",
                    "product_assignment_id": st.resolved_product_assignment_id,
                })
            
            if st.match_state == AckStaging.MATCH_DECLINED:
                return JsonResponse({
                    "status": "error",
                    "message": "This staging row was declined and cannot be auto-resolved.",
                }, status = 409)


            #if st.match_state in (AckStaging.MATCH_MATCHED, AckStaging.MATCH_DECLINED):
            #    return JsonResponse({"status": "success", "message": "Staging row already resolved.", "action": "noop"})
            
            # create or fetch client (idempotent)
            client = Client.objects.filter(TIN = tin).first()
            action = "existing"
            if not client:
                client = Client(TIN = tin, name = name, email = email, phone = phone)

                # only set if your Client model expects raw strings here
                if filing_type:
                    client.filing_type = filing_type
                if prior_filing_type:
                    client.prior_filing_type = prior_filing_type
                
                client.full_clean()
                client.save()
                action = "created"

            # resolve this staging row now that client exists
            pa, ack_obj, ack_created = _resolve_single_ack_staging_row(st = st, client = client)

        return JsonResponse({
            "status": "success",
            "message": "Client created and acknowledgment resolved.",
            "action": action,
            "client": {"id": client.id, "TIN": client.TIN, "name": client.name},
            "product_assignment_id": pa.id,
            "ack_created": bool(ack_created),
        })
    
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status = 400)
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status = 500)

'''
        # if client already exists, just return it (idempotent)
        existing = Client.objects.filter(TIN = tin).first()
        if existing:
            return JsonResponse({
                "status": "success",
                "action": "existing",
                "client": {"id": existing.id, "TIN": existing.TIN, "name": existing.name},
                })
        
        # create new client (minimal required fields + optional ones)
        client = Client(
            TIN = tin,
            name = name,
            email = email,
            phone = phone,
        )

        # only set these if your model allows blank/""; otherwise guard harder
        if filing_type:
            client.filing_type = filing_type
        if prior_filing_type:
            client.prior_filing_type = prior_filing_type
        
        client.full_clean()
        client.save()

        return JsonResponse({
            "status": "success",
            "action": "created",
            "client": {"id": client.id, "TIN": client.TIN, "name": client.name},
        })
    
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status = 400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status = 500)
'''
    

def _resolve_single_ack_staging_row(*, st: AckStaging, client: Client):
    """
    Resolve a single AckStaging row for a known Client:
    - Ensure Intake exists (active season)
    - Ensure TaxYear exists for st.year
    - Ensure Product exists for (TaxYear, suggested_product_type) if we have it; otherwise default TBD
    - Ensure ProductAssignment exists and is active
    - Ensure DailyClearing exists/active
    - Create/update Acknowledgment with REQUIRED fields
    - Mark staging MATCHED and link resolved_product_assignment
    Returns: (pa, ack_obj, ack_created)
    """
    # Ensure intake exists / active
    intake = get_or_create_intake(client)

    # Ensure tax year exists (your staging year is the tax-year being acknowledged)
    tax_year_value = st.year
    if not tax_year_value:
        raise ValidationError({"year": "Staging row missing year; cannot resolve."})

    tax_year_obj, _ = TaxYear.objects.get_or_create(client=client, year=tax_year_value)

    # Choose product_type
    product_type = (st.suggested_product_type or "").strip() or Product.PRODUCT_TYPE_DEFAULT

    # Ensure product exists for that tax year + product_type
    product_obj, _ = Product.objects.get_or_create(
        tax_year=tax_year_obj,
        product_type=product_type,
        defaults={"is_product_active": False},
    )

    # Ensure product assignment exists for (client, intake, tax_year, product)
    # Use your manager if you want, but keep it explicit for clarity.
    # IMPORTANT: your model constraint is uniq_active_client_intake_taxyear_product
    filing_type_default = FilingType.objects.filter(filing_type=FilingType.FILING_TYPE_DEFAULT).first()
    if filing_type_default is None:
        # If you don't have a FilingType row for TBD, create it once in migrations/seed instead.
        filing_type_default = FilingType.objects.create(filing_type=FilingType.FILING_TYPE_DEFAULT)

    pa, _created = ProductAssignment.objects.get_or_create(
        client=client,
        intake=intake,
        tax_year=tax_year_obj,
        product=product_obj,
        defaults={
            "is_active": True,
            "is_complete": False,
            "is_archived": False,
            "payment_method": ProductAssignment.PAYMENT_METHOD_DEFAULT,
            "filing_type": filing_type_default,
        },
    )

    # Ensure PA is active/not complete
    updates = []
    if not pa.is_active:
        pa.is_active = True
        updates.append("is_active")
    if pa.is_complete:
        pa.is_complete = False
        updates.append("is_complete")
    if updates:
        pa.save(update_fields=updates)

    # Ensure clearing exists / active
    clearing, _ = DailyClearing.objects.get_or_create(
        client=client,
        tax_season=intake.tax_season,
        defaults={"is_active": True},
    )
    if not clearing.is_active:
        clearing.is_active = True
        clearing.save(update_fields=["is_active"])

    from core.workflows.lifecycle import cmd_enter_clearing

    cmd_enter_clearing(pa_id=pa.id)

    # Create / update acknowledgment tied to PA
    ack_obj, ack_created = Acknowledgment.objects.update_or_create(
        product_assignment=pa,
        type=(st.type or "").strip(),
        date=st.date,
        defaults={
            "client_tin": (st.client_tin or "").strip(),
            "client_name": (st.client_name or "").strip(),
            "year": tax_year_value,
            "status": (st.status or "").strip() or Acknowledgment.STATUS_DEFAULT,
            "tax_season": intake.tax_season,
            # required by your Acknowledgment model today:
            "product": product_obj,
            # optional but helpful:
            "description": st.reason or "",
        },
    )

    # Mark staging matched + link
    st.resolved_product_assignment = pa
    st.match_state = AckStaging.MATCH_MATCHED
    st.reason = "Client created / linked and acknowledgment attached."
    st.save(update_fields=["resolved_product_assignment", "match_state", "reason"])

    return pa, ack_obj, ack_created



"""
def _resolve_single_ack_staging_row(*, st, client):
    
    #Resolve a single AckStaging row for a known Client:
    #- Ensure Intake + PA + Clearing exist / active
    #- Create / update Acknowledgment
    #- Mark staging MATCHED and link resolved_product_assignment
    #Returns: (pa, ack_obj, ack_created)
    
    # ensure intake exists / active
    intake = get_or_create_intake(client)

    # ensure PA for that tax year exists
    pa = get_or_create_product_assignment_for_tax_year(client, intake, st.year)

    # ensure clearing exists / active
    clearing, _ = DailyClearing.objects.get_or_create(
        client = client,
        tax_season = intake.tax_season,
        defaults = {"is_active": True},
    )
    if not clearing.is_active:
        clearing.is_active = True
        clearing.save(update_fields = ["is_active"])
    
    # PA should NOT be completed automatically
    if pa.is_complete:
        pa.is_complete = False
        pa.save(update_fields = ["is_complete"])
    
    tin = (st.client_tin or "").strip()
    form_type = (st.type or "").strip()
    ack_date = st.date
    ack_status = (st.status or "").strip()
    client_name = (st.client_name or "").strip()

    # NOTE: you currently use Acknowledgment.date
    # if refactored to ack_date, swap field name accordingly
    ack_obj, ack_created = Acknowledgment.objects.update_or_create(
        product_assignment = pa,
        type = form_type,
        date = ack_date,
        defaults = {
            "client_tin": tin,
            "client_name": client_name,

        }
    )

    # mark staging matched
    st.resolved_product_assignment = pa
    st.match_state = AckStaging.MATCH_MATCHED
    st.reason = "Client created / linked and acknowledgment attached."
    st.save(update_fields=["resolved_product_assignment", "match_state", "reason"])

    return pa, ack_obj, ack_created
"""


# ======= PA Completion Workflow Methods ======= #
@require_POST
@login_required
def start_completion(request, pa_id):
    try:
        pa = cmd_start_completion(pa_id = pa_id)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)
    
@require_POST
@login_required
def skip_parser(request, pa_id):
    try:
        pa = cmd_skip_parser(pa_id = pa_id)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)

@require_POST
@login_required
def begin_ack_count(request, pa_id):
    try:
        pa = cmd_begin_ack_count(pa_id = pa_id)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)
    
@require_POST
@login_required
def set_expected_ack_count(request, pa_id):
    try:
        data = json.loads(request.body)
        count = data.get("expected_ack_count")    
        pa = cmd_set_expected_ack_count(pa_id = pa_id, expected_ack_count = count)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except (TypeError, ValueError):
        return JsonResponse({"status": "error", "message": "invalid ack count."}, status = 400)
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)

@require_POST
@login_required
def finalize_completion(request, pa_id):
    try:
        pa = cmd_finalize_completion(pa_id = pa_id, completed_by = request.user)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)

@require_POST
@login_required
def cancel_completion(request, pa_id):
    try:
        pa = cmd_cancel_completion(pa_id = pa_id)
        return JsonResponse({"status": "ok", "state": pa.completion_state})
    except ValidationError as ve:
        return JsonResponse({"status": "error", "message": ve.message_dict}, status = 409)


def health(request):
    return JsonResponse({"status": "ok"})
