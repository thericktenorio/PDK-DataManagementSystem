from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods
from django.db.models import ProtectedError
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from core.models import Client
import json, datetime
import pandas as pd


@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def client_portfolio(request):
    clients = Client.objects.all()
    print(f"Number of clients retrieved: {clients.count()}")
    return render(request, "client_portfolio/client_portfolio.html", {'clients': clients})


# Create and save new Client
@require_http_methods(["POST"])
def create_and_save_new_client(request):
    try:
        data = json.loads(request.body)
        client_id = data.get('client_id')

        # Shared field processing
        allowed_fields = [
            'TIN',
            'name',
            'email',
            'phone',
            'filing_type',
            'prior_filing_type',
        ]
        cleaned_data = {field: data.get(field, "").strip() for field in allowed_fields}

        # ========== UPDATE EXISTING CLIENT ==========
        if client_id:
            try:
                client = Client.objects.get(id=client_id)
            except Client.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': f'Client {client_id} not found.'}, status=400)
            for field, value in cleaned_data.items():
                setattr(client, field, value)
            client.full_clean()
            client.save()
            return JsonResponse({'status': 'success', 'message': 'Client updated successfully.'})

        # ========== CREATE NEW CLIENT ==========
        else:
            client = Client(**cleaned_data)
            client.full_clean()
            client.save()
            return JsonResponse({
                'status': 'success',
                'message': 'Client created successfully.',
                'client_id': client.id
            })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload.'}, status=400)
    except ValidationError as e:
        errors = {field: messages for field, messages in e.message_dict.items()}
        return JsonResponse({'status': 'error', 'message': errors}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# Delete client from database
@login_required
@require_http_methods(["DELETE"])
def delete_client(request, client_id):
    try:
        client = get_object_or_404(Client, id=client_id)
        client.delete()
        return JsonResponse({"status": "success", "message": "Client successfully deleted."})
    except ProtectedError:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "This client cannot be deleted because billing records reference them. "
                    "Remove from clearing/intake first or void related invoices."
                ),
            },
            status=409,
        )
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)


# Import clients from excel to client_portfolio
def import_clients(request):
    if request.method == 'POST':
        print(f"request.FILES: {request.FILES}")
        file = request.FILES.get('client_file')

        if not file:
            print("No file received by request.FILES or invalid request format.")
            return JsonResponse({'status': 'error', 'message': 'No file selected or invalid request format.'}, status = 400)
        
        print(f"Received file: {file.name}, Content-Type: {file.content_type}")

        if file.content_type not in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/csv']:
            return JsonResponse({'status': 'error', 'message': 'Invalid file type.'}, status = 400)
        
        try:
            # Check file type
            if file.name.endswith(('.xls', '.xlsx', '.xlsm')):
                print("\nAttempting to read Excel file...")
                client_data = pd.read_excel(file)
                print(client_data.head())
            elif file.name.endswith('.csv'):
                print("\nAttempting to read CSV file...")
                client_data = pd.read_csv(file)
                print(client_data.head())
            else:
                messages.error(request, "File type must be one of the following: .xls, .xlsx, .xlsm, .csv")
                return JsonResponse({'status': 'error', 'message': 'Invalid file extension.'}, status = 400)
            
            print("\nInitial data types")
            print(client_data.dtypes)

            # Clean DataFrame
            print("\nCleaning data...")
            client_data = client_data.fillna("")    # converts all NaN values to ""
            client_data = client_data.astype(str)   # converts all data to strings
            client_data["phone"] = client_data["phone"].apply(lambda x: x.split(".")[0] if "." in x else x)
            print(client_data.head())
            print(client_data.dtypes)

            # Check required columns
            required_columns = {"TIN", "name", "email", "phone", "prior_filing_type"}
            if not required_columns.issubset(client_data.columns):
                missing_columns = required_columns - set(client_data.columns)
                return JsonResponse({'status': 'error', 'message': f'Missing columns: {", ".join(missing_columns)}'}, status = 400)
            
            print(f"Required columns are present")

            # Create or update clients
            clients_to_create = []
            max_name_length = 50
            existing_tins = set(Client.objects.values_list('TIN', flat = True))
            valid_prior_filing_types = {choice for choice in Client.PRIOR_FILING_TYPE_CHOICES.values() if choice}

            # Process each row
            for index, row in client_data.iterrows():
                try:
                    tin = str(row["TIN"]).strip() if pd.notnull(row["TIN"]) else ""
                    name = str(row["name"]).strip() if pd.notnull(row["name"]) else ""
                    email = str(row["email"]).strip() if pd.notnull(row["email"]) else ""
                    phone = str(row["phone"]).strip() if pd.notnull(row["phone"]) else ""
                    prior_filing_type = str(row["prior_filing_type"]).strip() if pd.notnull(row["prior_filing_type"]) else ""

                    # Validate length of TIN
                    if len(tin) > 9:
                        print(f"{name} (TIN: {tin}) has a TIN that is greater than 9 digits. Correct TIN and manually add client to portfolio.")
                        continue
                    elif len(tin) < 9:
                        print(f"{name} has a TIN that is less than 9 digits. Leading zeros are assumed.")
                        tin = tin.zfill(9)
                    
                    # Validate length of name
                    if len(name) > max_name_length:
                        print(f"{name} has been shortened to 50 characters inorder to fit the name field.")
                        name = name[ : max_name_length] # Truncate to name to max length
                    
                    # Validate phone number length of 10 digits
                    if phone and (not phone.isdigit() or len(phone) != 10):
                        print(f"Invalid phone number for {name} (TIN: {tin}). Number must be 10 digits with no additional formatting or special characters.")
                        phone = ""
                    
                    # Validate prior filing type
                    if prior_filing_type not in valid_prior_filing_types:
                        print(f"{name} (TIN:{tin}) does not have a valid prior filing type.")
                        prior_filing_type = ""
                    
                    if tin in existing_tins:
                        Client.objects.filter(TIN = tin).update(name = name, email = email, phone = phone)
                    else:
                        clients_to_create.append(Client(TIN = tin, name = name, email = email, phone = phone))
                except Exception as e:
                    print(f"Error processing row {index +1}: {e}")
                    continue

            print(f"\nProcessed client data")
            print(client_data.head())

            # Bulk create new clients
            if clients_to_create:
                Client.objects.bulk_create(clients_to_create)
            return JsonResponse({'status': 'success', 'message': 'Import successful.'}, status = 200)
        
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status = 500)
    # Handle invalid request methods
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status = 405)