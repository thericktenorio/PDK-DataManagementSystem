from django.contrib.auth.forms import AuthenticationForm
from crispy_forms.helper import FormHelper


class PlaceholderLoginForm(AuthenticationForm):
    """Staff login: placeholders only, no field labels (login page layout)."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "Email",
                "autocomplete": "email",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Password",
                "autocomplete": "current-password",
            }
        )
        self.fields["username"].label = ""
        self.fields["password"].label = ""

        self.helper = FormHelper()
        self.helper.form_show_labels = False
        self.helper.form_tag = False
