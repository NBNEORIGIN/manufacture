from django.contrib import admin
from .models import Shipment, ShipmentItem


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'country', 'shipment_date', 'created_at')
    list_filter = ('country',)
    inlines = [ShipmentItemInline]
