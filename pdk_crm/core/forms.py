from django import forms
from .models import Client


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