from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q

from core.models import TaxSeason, Client, Intake, DailyClearing, TaxYear, ProductAssignment, Product, FilingType, Appointment
from core.forms import ClientForm
from core.utils import get_valid_tax_years, get_or_create_intake, get_or_create_product_assignment, get_or_create_appointment, enforce_pa_not_frozen_for_action

from accounts.models import InternalUser
from intake.views import add_client_to_intake

import json

# To Clearing Page
@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def clearing(request):
    # filter through active clearings
    active_clearings = DailyClearing.objects.filter(is_active = True).select_related('client', 'tax_season')

    # reference tax year = current tax year
    current_tax_year = timezone.now().year -1
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
    for clearing in active_clearings:
        client = clearing.client

        # use prefetching if needed in large datasets
        product_assignments = client.product_assignments.select_related('product', 'tax_year', 'filing_type').filter(intake__tax_season = clearing.tax_season, is_active = True)

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
                pa.save()
            
            if pa.product is None:
                pa.product = Product.objects.create(tax_year = pa.tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT)
                # TODO: maybe get product fee and save this along with the product_assignment
                pa.save()
            
            pa.valid_products = reference_valid_products

            pa.appointment = get_or_create_appointment(pa)

            # TODO: get or create preparer

            # TODO: get completion status

        # attach product assignments to each client (product assignments for expandable rows)
        client.product_assignments_list = product_assignments   # attach all for rendering
        client.first_product_assignment = product_assignments.first() if product_assignments.exists() else None     # still needed for backward compatibility

        # add client to the client list []
        clients.append(client)

    valid_tax_years = get_valid_tax_years()
    PRODUCT_TYPE_CHOICES = Product.PRODUCT_TYPE_CHOICES
    PAYMENT_METHOD_CHOICES = ProductAssignment.PAYMENT_METHOD_CHOICES
    APPOINTMENT_TYPE_CHOICES = Appointment.APPOINTMENT_TYPE_CHOICES
    PREPARER_OPTIONS = InternalUser.objects.filter(is_active = True).values('id', 'first_name', 'last_name', 'email')

    return render(request, 'clearing/clearing.html', {
        'clearing_clients': clients,
        'valid_tax_years': valid_tax_years,
        'filing_type_options': list(FilingType.objects.values('id', 'filing_type')),
        'product_type_options': PRODUCT_TYPE_CHOICES,
        'reference_valid_products': reference_valid_products,
        'payment_method_options': PAYMENT_METHOD_CHOICES,
        'appointment_type_options': APPOINTMENT_TYPE_CHOICES,
        'preparer_options': PREPARER_OPTIONS,

    })


# Search for clients in intake that will be added to the clearing
@login_required
def search_clients(request):
    query = request.GET.get('q', '').strip()

    try:
        clients = Client.objects.filter(Q(name__icontains = query) | Q(TIN__icontains = query)).values('id', 'name', 'TIN')

        intake_clients = set(Intake.objects.filter(is_active = True).values_list('client_id', flat = True))
        daily_clearing_clients = set(DailyClearing.objects.filter(is_active = True).values_list('client_id', flat = True))

        results = []
        for client in clients:
            client_id = client['id']
            results.append({
                'id': client['id'],
                'name': client['name'],
                'TIN': client ['TIN'],
                'in_intake': client['id'] in intake_clients,
                'in_daily_clearing': client_id in daily_clearing_clients,
            })
        return JsonResponse(results, safe = False)
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)

# Add client to clearing table if not already present
@require_POST
@login_required
def add_client_to_clearing(request, client_id):
    client = get_object_or_404(Client, id = client_id)
    current_tax_season = TaxSeason.objects.filter(is_active = True).order_by('-year').first()

    if not current_tax_season:
        return JsonResponse({'status': 'error', 'message': 'No active tax season'}, status = 400)

    intake = get_or_create_intake(client)
    
    product_assignment = get_or_create_product_assignment(client, intake)

    # get the intake info IF intake exists; create intake if not already created
    #intake, intake_created = Intake.objects.get_or_create(client = client, tax_season = current_tax_season, defaults = {'is_active': True})

    # use method from Intake module to properly add client to the intake table if NOT already present
    #if not intake.is_active:
    #    add_client_to_intake(client)
        
    clearing, clearing_created = DailyClearing.objects.get_or_create(client = client, tax_season = current_tax_season, defaults = {'is_active': True})

    if not clearing.is_active:
        clearing.is_active = True
        clearing.save()
    
    # generate filtered product options - one per product_type
    seen_types = set()
    filtered_products = []
    products_for_year = Product.objects.filter(tax_year = product_assignment.tax_year)

    for p in products_for_year:
        if p.product_type not in seen_types:
            filtered_products.append({'id': p.id, 'product_type': p.product_type})
            seen_types.add(p.product_type)
    
    return JsonResponse({
        'status': 'success',
        'message': f'{client.name} added to clearing',
        'client': {
            'id': client.id,
            'TIN': client.TIN,
            'name': client.name,
        },
        'product_assignment': {
            'id': product_assignment.id,
            'tax_year': product_assignment.tax_year.year,
            'product_id': product_assignment.product.id,
            'product_type': product_assignment.product.product_type,
            'filing_type': {
                'id': product_assignment.filing_type.id,
                'label': product_assignment.filing_type.filing_type
            }
        },
        'filing_type_options': list(FilingType.objects.values('id', 'filing_type')),
        'product_options': filtered_products,
        'valid_tax_years': get_valid_tax_years(),
        
        })

# Remove client from clearing table is present
@require_POST
@login_required
def remove_client_from_clearing(request, client_id):
    clearing = DailyClearing.objects.filter(client_id = client_id, is_active = True).first()
    if clearing:
        clearing.is_active = False
        clearing.save()

    return JsonResponse({'status': 'success'})

# Add product assignment subrow
@require_POST
@login_required
def add_product_assignment(request):
    try:
        data = json.loads(request.body)
        
        client_id = data.get('client_id')
        if not client_id:
            return JsonResponse({'status': 'error', 'message': 'Client ID missing.'}, status = 400)
        client = get_object_or_404(Client, id = client_id)

        intake = Intake.objects.filter(client = client, is_active = True).first()
        if not intake:
            return JsonResponse({'status': 'error', 'message': 'Active intake not found.'}, status = 404)

        #reference the current tax year
        reference_tax_year = timezone.now().year - 1

        # get or create default FKs
        tax_year, _ = TaxYear.objects.get_or_create(client = client, year = reference_tax_year)
        filing_type, _ = FilingType.objects.get_or_create(filing_type = FilingType.FILING_TYPE_DEFAULT)
        product, _ = Product.objects.get_or_create(tax_year = tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT, defaults = {'is_product_active': False})

        product_assignment, _ = ProductAssignment.objects.create_product_assignment( client = client,
                                                                                    intake = intake,
                                                                                    tax_year = tax_year,
                                                                                    product = product,
                                                                                    filing_type = filing_type,
                                                                                    is_active = True)
        
        appointment = get_or_create_appointment(product_assignment)

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
                'filing_type': {'id': filing_type.id, 'label': filing_type.filing_type},
                'appointment_id': appointment.id, 
            },
            'filing_type_options': list(FilingType.objects.values('id', 'filing_type')),
            'product_options': reference_valid_products,
            'valid_tax_years': get_valid_tax_years(),
            'appointment_type_options': Appointment.APPOINTMENT_TYPE_CHOICES,
        })
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)


# Remove product assignment subrow
@require_POST
@login_required
def remove_product_assignment(request):
    try:
        data = json.loads(request.body)
        pa_id = data.get('product_assignment_id')

        if not pa_id:
            return JsonResponse({'status': 'error', 'message': 'Missing product assignment ID'}, status = 400)
        
        pa = get_object_or_404(ProductAssignment, id = pa_id)

        #guardrail for PAs that have been marked as completed (ergo PA is frozen)
        enforce_pa_not_frozen_for_action(pa, action = 'remove_product_assignment')

        product = pa.product

        # deactivate product
        product.is_product_active = False
        product.save()

        # deactivate PA
        pa.is_active = False
        pa.save()

        return JsonResponse({'status': 'success'})
    
    except ValidationError as ve:
        return JsonResponse({'status': 'error', 'code': 'PA_FROZEN', 'message': ve.message_dict}, status = 409)
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)

# TODO: deprecate if above works
"""
@require_POST
@login_required
def remove_product_assignment(request):
    try:
        data = json.loads(request.body)
        product_assignment_id = data.get('product_assignment_id')

        if not product_assignment_id:
            return JsonResponse({'status': 'error', 'message': 'Missing product assignment ID'}, status = 400)
        
        product_assignment = get_object_or_404(ProductAssignment, id = product_assignment_id)
        product = product_assignment.product

        # deactivate product
        product.is_product_active = False
        product.save()

        # deactiveate product assignment
        product_assignment.is_active = False
        product_assignment.save()

        return JsonResponse({'status': 'success'})
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)
"""
