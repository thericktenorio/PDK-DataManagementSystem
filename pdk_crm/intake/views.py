from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.db import transaction
from core.models import Client, Intake, DailyClearing, TaxYear, Product, ProductAssignment, TaxSeason, FilingType
from core.forms import ClientForm
from core.utils import get_valid_tax_years, enforce_pa_not_frozen_for_action
from collections import defaultdict
import datetime

import json


# To Intake Page
@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def intake(request):
    active_intakes = Intake.objects.filter(is_active = True).select_related("client", "tax_season")

    default_filing_type, _ = FilingType.objects.get_or_create(filing_type = FilingType.FILING_TYPE_DEFAULT)
    current_tax_year_value = timezone.now().year - 1
    clients = []

    def _ensure_products_seeded_for_tax_year(tax_year_obj):
        for pt, _label in Product.PRODUCT_TYPE_CHOICES:
            Product.objects.get_or_create(tax_year = tax_year_obj, product_type = pt, defaults = {"is_product_active": False})
    
    def _build_valid_products_for_tax_year(tax_year_obj):
        seen = set()
        valid = []
        qs = (Product.objects.filter(tax_year = tax_year_obj).order_by("product_type", "id"))
        for p in qs:
            if p.product_type in seen:
                continue
            valid.append({"id": p.id, "product_type": p.product_type})
            seen.add(p.product_type)
        return valid
    
    for intake in active_intakes:
        client = intake.client

        product_assignments = (client.product_assignments.select_related("product", "tax_year", "filing_type").filter(intake = intake, is_active = True))

        for pa in product_assignments:
            with transaction.atomic():
                updated_fields = []

                if pa.filing_type_id is None:
                    pa.filing_type = default_filing_type
                    updated_fields.append("filing_type")
                
                if pa.tax_year_id is None:
                    tax_year_obj, _ = TaxYear.objects.get_or_create(client = client, year = current_tax_year_value)
                    pa.tax_year = tax_year_obj
                    updated_fields.append("tax_year")
                else:
                    tax_year_obj = pa.tax_year
                
                _ensure_products_seeded_for_tax_year(tax_year_obj)

                if pa.product_id is None:
                    default_product, _ = Product.objects.get_or_create(tax_year = tax_year_obj, product_type = Product.PRODUCT_TYPE_DEFAULT, defaults = {"is_product_active": False})
                    pa.product = default_product
                    updated_fields.append("product")
                
                if updated_fields:
                    pa.save(update_fields = updated_fields)
                
            pa.valid_products = _build_valid_products_for_tax_year(tax_year_obj)

        client.product_assignments_list = product_assignments
        client.first_product_assignment = (product_assignments.first() if product_assignments.exists() else None)

        clients.append(client)

    return render(
        request,
        "intake/intake.html",
        {
            "intake_clients": clients,
            "valid_tax_years": get_valid_tax_years(),
            "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
            "product_type_options": Product.PRODUCT_TYPE_CHOICES,
        },
    )
    
    '''
    active_intakes = Intake.objects.filter(is_active = True).select_related('client', 'tax_season')
    
    # reference tax year = current tax year
    current_tax_year = timezone.now().year - 1
    reference_tax_year = current_tax_year

    # reference products
    reference_products = Product.objects.filter(tax_year__year = reference_tax_year)

    # use the reference tax year to get a set of product types from the current tax year
    seen_types = set()
    reference_valid_products = []

    for p in reference_products:
        if p.product_type not in seen_types:
            reference_valid_products.append({'id':p.id, 'product_type': p.product_type})
            seen_types.add(p.product_type)

    # extract just the client objects
    clients = []
    for intake in active_intakes:
        client = intake.client

        # use prefetching if needed in large datasets
        product_assignments = client.product_assignments.select_related('product', 'tax_year', 'filing_type').filter(intake = intake, is_active = True)
        
        #
        # ensure each product_assignment is fully populated with required FK objects
        for pa in product_assignments:
            if pa.filing_type is None:
                default_filing_type, _ = FilingType.objects.get_or_create(filing_type = FilingType.FILING_TYPE_DEFAULT)
                pa.filing_type = default_filing_type
                pa.save()
            
            if pa.tax_year is None:
                current_year = timezone.now().year - 1
                tax_year, _ = TaxYear.objects.get_or_create(client = client, year = current_year)
                pa.tax_year = tax_year
                pa.save(update_fields = ["tax_year"])
            
            if pa.product is None:
                pa.product = Product.objects.create( tax_year = pa.tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT)
                pa.save()
            
            # attach all valid product for particular tax year
            #if pa.tax_year:
            #    pa.valid_products = Product.objects.filter(tax_year = pa.tax_year).values("id", "product_type")
            #else:
            #    pa.valid_products = Product.objects.none()
            
            pa.valid_products = reference_valid_products

        # attach product assignments to each client (product assignemts for expandable rows)
        client.product_assignments_list = product_assignments # attach all for rendering
        client.first_product_assignment = product_assignments.first() if product_assignments.exists() else None # still needed for backward compatibility

        # add client to the clist []
        clients.append(client)

    valid_tax_years = get_valid_tax_years()
    PRODUCT_TYPE_CHOICES = Product.PRODUCT_TYPE_CHOICES

    return render(request, 'intake/intake.html', {
        'intake_clients': clients, 
        'valid_tax_years': valid_tax_years, 
        'filing_type_options': list(FilingType.objects.values('id', 'filing_type')), 
        'product_type_options': PRODUCT_TYPE_CHOICES,
        'reference_valid_products': reference_valid_products,
        })
    '''


# Search for clients in database that will be added to intake
@login_required
def search_clients(request):
    query = request.GET.get('q', '').strip()
    clients = Client.objects.filter(Q(name__icontains = query) | Q(TIN__icontains = query)).values('id', 'name', 'TIN')

    intake_clients = set(Intake.objects.filter(is_active = True).values_list('client_id', flat = True))
    daily_clearing_clients = set(DailyClearing.objects.filter(is_active = True).values_list('client_id', flat = True))

    results = []
    for client in clients:
        client_id = client['id']
        results.append({
            'id': client['id'],
            'name': client['name'],
            'TIN': client['TIN'],
            'in_intake': client['id'] in intake_clients,
            'in_daily_clearing': client_id in daily_clearing_clients,
        })
    return JsonResponse(results, safe = False)


# Add client to intake
@login_required
def add_client_to_intake(request, client_id):
    if request.method != "POST":
        return JsonResponse({
            'status': 'error', 
            'message': 'Invalid request method.'}, status = 405)
        
    client = get_object_or_404(Client, id = client_id)

    # step 1: determine current acitve tax season
    current_tax_season = TaxSeason.objects.filter(is_active = True).order_by('-year').first()
    if not current_tax_season:
        return JsonResponse ({'status': 'error', 'message': 'No active tax season found.'}, status = 400)

    # step 2: get or create Intake row
    intake, _ = Intake.objects.get_or_create(
        client = client,
        tax_season = current_tax_season,
        defaults = {'is_active': True}
    )

    if not intake.is_active:
        intake.is_active = True
        intake.save()
        
    # step 3: determine current year and use previous year as current tax year
    current_tax_year_value = timezone.now().year -1
    tax_year, _ = TaxYear.objects.get_or_create(client = client, year = current_tax_year_value)

    # step 4: get or create FilingType (default)
    filing_type, _ = FilingType.objects.get_or_create(filing_type = FilingType.FILING_TYPE_DEFAULT)

    # step 6: seed all default products for this tax year (if not already present)
    # NOTE: a new set of product type instances are created for each tax year of every client - this is integral to accurate billing and analytics
    for pt, _ in Product.PRODUCT_TYPE_CHOICES:
        Product.objects.get_or_create(tax_year = tax_year, product_type = pt)
    
    # step 6: assign default product to initial ProductAssignment
    product = Product.objects.get(tax_year = tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT)

    # step 7: get or create via the Product Assignment Factory
    product_assignment, _ = ProductAssignment.objects.create_product_assignment( client = client,
                                                                             intake = intake,
                                                                             tax_year = tax_year,
                                                                             product = product,
                                                                             filing_type = filing_type,
                                                                             is_active = True)
    
    # step 8: generate filtered product options - one per product_type
    seen_types = set()
    filtered_products = []
    products_for_year = Product.objects.filter(tax_year = tax_year)

    for p in products_for_year:
        if p.product_type not in seen_types:
            filtered_products.append({'id': p.id, 'product_type': p.product_type})
            seen_types.add(p.product_type)
    
    # step 9: return structured data to frontend
    return JsonResponse({
        'status': 'success',
        'message': f'{client.name} added to intake.',
        'client': {
            'id': client.id, 
            'TIN': client.TIN, 
            'name': client.name, 
        },
        'product_assignment': {
            'id': product_assignment.id, 
            'tax_year': tax_year.year, 
            'product_id': product.id, 
            'product_type': product.product_type,
            'filing_type': {
                'id': filing_type.id,
                'label': filing_type.filing_type,
            }
        },
        'filing_type_options': list(FilingType.objects.values('id', 'filing_type')),
        'product_options': filtered_products,
        'valid_tax_years': get_valid_tax_years(),
    })


# Remove client from intake
@login_required
def remove_client_from_intake(request, client_id):
    if request.method == "POST":
        return JsonResponse({"status": "error", "message": "Invalid request method."}, status = 409)
    
    try:
        # Get intake record for client_id
        intake = get_object_or_404(Intake, client_id = client_id, is_active = True)

        # Deactivate associated products & product assignments
        product_assignments = ProductAssignment.objects.filter(client_id = client_id, intake = intake, is_active = True).select_related("product")    # find all assocaited product assignments

        product_ids = product_assignments.values_list('product_id', flat = True).distinct()    # find all products associated with each product assignment being tagged for removal
        
        # guardrail for PAs that have been marked as completed (or are 'frozen')
        for pa in product_assignments:
            enforce_pa_not_frozen_for_action(pa, action = "remove_client_from_intake")

        # only after it passes
        product_ids = product_assignments.values_list("product_id", flat = True).distinct()
        Product.objects.filter(id__in = product_ids).update(is_product_active = False)
        product_assignments.update(is_active = False)

        intake.is_active = False
        intake.save(update_fields = ["is_active"])

        return JsonResponse({"status": "success"}, status = 200)
    
    except ValidationError as ve:
        return JsonResponse({"status": "error", "code": "PA_FROZEN", "message": ve.message_dict}, status = 409)
    
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status = 400)
        
        
        #TODO: deprecate if remove client from intake functional 
        # Product.objects.filter(id__in = product_ids).update(is_product_active = False)    # deactivate products

        #ProductAssignment.objects.filter(id__in = product_assignments).update(is_active = False)    # deactivate product assignment(s)

        # Deactivate or intake record
        #intake.is_active = False
        #intake.save()
        #return JsonResponse({'status': 'success'}, status = 200)
    #except Exception as e:
        #return JsonResponse({'status': 'error', 'message': str(e)}, status = 400)
    #return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status = 405)


# NOTE: need to check if this function works after model updates
# Create new client and add to intake
@login_required
def create_new_client(request):
    if request.method == "POST":
        form = ClientForm(json.loads(request.body))

        if form.is_valid():
            client = form.save()
            return JsonResponse({'status': 'success','message':f'{client.name} created.', 'client_id': client.id})
        
        return JsonResponse({'status': 'error', 'errors': form.errors}, status = 400)


# Add product assignment to a client
@require_POST
@login_required
def add_product_assignment(request):
    try:
        data = json.loads(request.body)
        client_id = data.get('client_id')

        client = get_object_or_404(Client, id = client_id)
        intake = Intake.objects.filter(client = client, is_active = True).first()
        if not intake:
            return JsonResponse({ 'status': 'error', 'message': 'Active intake not found.'}, status = 404)
        
        # reference the current tax year
        reference_tax_year = timezone.now().year - 1

        # get or create default FKs
        tax_year, _ = TaxYear.objects.get_or_create(client = client, year = reference_tax_year)
        filing_type, _ = FilingType.objects.get_or_create(filing_type = FilingType.FILING_TYPE_DEFAULT)
        product, _ = Product.objects.get_or_create(tax_year = tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT, defaults = { 'is_product_active': False})

        product_assignment, _ = ProductAssignment.objects.create_product_assignment( client = client,
                                                                                 intake = intake,
                                                                                 tax_year = tax_year,
                                                                                 product = product,
                                                                                 filing_type = filing_type,
                                                                                 is_active = True)

        # create reference valid product options
        seen_types = set()
        reference_products = Product.objects.filter(tax_year__year = reference_tax_year)
        reference_valid_products = []

        for p in reference_products:
            if p.product_type not in seen_types:
                reference_valid_products.append({'id': p.id, 'product_type': p.product_type})
                seen_types.add(p.product_type)

        return JsonResponse({
            'status': 'success',
            'product_assignment': {
                'id': product_assignment.id,
                'tax_year': tax_year.year,
                'product_id': product.id,
                'product_type': product.product_type,
                'filing_type': {'id': filing_type.id, 'label': filing_type.filing_type}
            },
            'filing_type_options': list(FilingType.objects.values('id', 'filing_type')),
            'product_options': reference_valid_products,
            'valid_tax_years': get_valid_tax_years(),
        })
    
    except Exception as e:
        return JsonResponse({ 'status': 'error', 'message': str(e)}, status = 500)



# Remove product assignment from client subrow
@require_POST
@login_required
def remove_product_assignment(request):
    try:
        data = json.loads(request.body)
        product_assignment_id = data.get('product_assignment_id')

        if not product_assignment_id:
            return JsonResponse({'status': 'error', 'message': 'Missing product assignment ID'}, status = 400)
        
        product_assignment = get_object_or_404(ProductAssignment, id = product_assignment_id)
    
        # guardrail for PAs that have been marked as completed
        enforce_pa_not_frozen_for_action(product_assignment, action="remove_product_assignment")

        product = product_assignment.product

        # deativate product
        product.is_product_active = False
        product.save()

        # deactivate product assignment
        product_assignment.is_active = False
        product_assignment.save()

        return JsonResponse({'status': 'success'})
    
    except ValidationError as ve:
        return JsonResponse({"status": "error", "code": "PA_FROZEN", "message": ve.message_dict}, status = 409)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)