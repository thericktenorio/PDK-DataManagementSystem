from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


class InternalUserManager(BaseUserManager):
    def create_user(self, email, password=None, organization=None, organization_id=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")

        email = self.normalize_email(email)

        # If createsuperuser passed organization as an id string (e.g. "1"), normalize it
        if organization is not None and not hasattr(organization, "_meta"):
            # Treat organization as an ID
            organization_id = organization
            organization = None
            
        if organization is not None and organization_id is not None:
            raise ValueError("Pass organization OR organization_id, not both.")

        if organization is None and organization_id is None:
            raise ValueError("Organization is required to create a user.")
        
        if organization is not None:
            extra_fields["organization"] = organization
        else:
            # Ensure int-like; docker env / prompts often give strings
            extra_fields["organization_id"] = int(organization_id)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, organization=None, organization_id=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", "developer")

        return self.create_user(
            email=email,
            password=password,
            organization=organization,
            organization_id=organization_id,
            **extra_fields,
        )


# TODO: possibly deprecate if the above works
'''
# Interface for Creating Users
class InternalUserManager(BaseUserManager):
    def create_user(self, email, password = None, organization = None, organization_id = None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        
        # resolve organization input (object or id)
        if organization is None and organization_id is not None:
            from core.models import Organization
            organization = Organization.objects.filter(pk = organization_id).first()
        if organization is None:
            raise ValueError("Organization is required to create a user.")
        

        email = self.normalize_email(email)
        user = self.model(email = email, organization = organization, **extra_fields)
        user.set_password(password)
        user.save(using = self._db)
        
        return user
    
    def create_superuser(self, email, password = None, organization = None, organization_id = None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Superuser must have is_staff = True.")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Superuser must have is_superuser = True.")
        
        return self.create_user(email, password, organization = organization, organization_id = organization_id, **extra_fields)
'''


# Main User Model
class InternalUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('office_admin', 'Office Admin'),
        ('data_entry_specialist', 'Data Entry Specialist'),
        ('i_t_technician', 'IT Technician'),
        ('tax_preparer', 'Tax Preparer'),
        ('billing', 'Billing Agent'),
        ('reviewer', 'Reviewer'),
        ('manager', 'Manager'),
        ('owner', 'Owner'),
        ('developer', 'Developer'),
    ]

    organization = models.ForeignKey("core.Organization", on_delete = models.PROTECT, null = False, blank = False, related_name = "users")    # Note: models.PROTECT prevents an org from being deleted when users are present

    email = models.EmailField(unique = True)
    role = models.CharField(max_length = 50, choices = ROLE_CHOICES)
    first_name = models.CharField(max_length = 30, blank = True)
    last_name = models.CharField(max_length = 30, blank = True)
    is_active = models.BooleanField(default = True)
    is_staff = models.BooleanField(default = False)
    rotate_background = models.BooleanField(
        default=False,
        help_text="When enabled, the app background rotates daily. When disabled, the classic beach photo is always used.",
    )
    # TODO: add date_joined attribute
    # TODO: add last_login attribute

    objects = InternalUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ["organization", "role"] # add 'role' if you'd like to enforce it when user is created

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
