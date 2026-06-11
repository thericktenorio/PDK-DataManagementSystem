from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from crispy_forms.helper import FormHelper


class LoginCardFormMixin:
    """Shared placeholder styling for login-card pages."""

    def _apply_login_card_field(self, field_name: str, *, placeholder: str, autocomplete: str):
        self.fields[field_name].widget.attrs.update(
            {
                "placeholder": placeholder,
                "autocomplete": autocomplete,
            }
        )
        self.fields[field_name].label = ""

    def _apply_login_card_helper(self):
        self.helper = FormHelper()
        self.helper.form_show_labels = False
        self.helper.form_tag = False


class PlaceholderLoginForm(LoginCardFormMixin, AuthenticationForm):
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

        self._apply_login_card_helper()


class PasswordResetRequestForm(LoginCardFormMixin, forms.Form):
    email = forms.EmailField(max_length=254)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field("email", placeholder="Email", autocomplete="email")
        self._apply_login_card_helper()


class EmailCodeVerificationForm(LoginCardFormMixin, forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]{6}"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field("code", placeholder="6-digit email code", autocomplete="one-time-code")
        self._apply_login_card_helper()


class TotpVerificationForm(LoginCardFormMixin, forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]{6}"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field(
            "code",
            placeholder="Authenticator code",
            autocomplete="one-time-code",
        )
        self._apply_login_card_helper()


class AuthenticatorSetupForm(LoginCardFormMixin, forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field("email", placeholder="Email", autocomplete="email")
        self._apply_login_card_field("password", placeholder="Current password", autocomplete="current-password")
        self._apply_login_card_helper()

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip()
        password = cleaned.get("password") or ""
        if not email or not password:
            return cleaned

        user = authenticate(username=email, password=password)
        if user is None:
            raise forms.ValidationError("Invalid email or password.")
        cleaned["user"] = user
        return cleaned


class AuthenticatorConfirmForm(LoginCardFormMixin, forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]{6}"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field(
            "code",
            placeholder="Authenticator code",
            autocomplete="one-time-code",
        )
        self._apply_login_card_helper()


class PasswordResetConfirmForm(LoginCardFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_login_card_field("new_password1", placeholder="New password", autocomplete="new-password")
        self._apply_login_card_field("new_password2", placeholder="Confirm password", autocomplete="new-password")
        self._apply_login_card_helper()

    def clean_new_password1(self):
        password = self.cleaned_data.get("new_password1")
        if password:
            validate_password(password, self.user)
        return password
