from django.contrib import admin
from .models import Organization, Client, TaxYear, Product, ProductAssignment, Intake, Acknowledgment, DailyClearing, TaxSeason, FilingType, Appointment


admin.site.register(Organization)
admin.site.register(TaxSeason)
admin.site.register(Client)
admin.site.register(TaxYear)
admin.site.register(Product)
admin.site.register(ProductAssignment)
admin.site.register(Intake)
admin.site.register(Acknowledgment)
admin.site.register(DailyClearing)
admin.site.register(FilingType)
admin.site.register(Appointment)