from django import forms
from .models import Client


def normalize_client_form_data(data: dict) -> dict:
    """Strip non-digits from TIN/phone before field max_length validation."""
    normalized = dict(data)
    for key in ("TIN", "phone"):
        raw = normalized.get(key)
        if raw is not None and str(raw).strip() != "":
            normalized[key] = "".join(c for c in str(raw) if c.isdigit())
    return normalized


# Client Form
class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            'TIN',
            'name',
            'email',
            'phone',
            'filing_type',
            'prior_filing_type',
        ]
        widgets = {
            'filing_type': forms.Select(),
            'prior_filing_type': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        if args and isinstance(args[0], dict):
            args = (normalize_client_form_data(args[0]),) + args[1:]
        elif isinstance(kwargs.get("data"), dict):
            kwargs["data"] = normalize_client_form_data(kwargs["data"])
        super().__init__(*args, **kwargs)