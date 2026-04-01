from django.contrib import admin
from .models import Shipment, ShipmentItem


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0
    fields = ('product', 'sku', 'quantity', 'quantity_shipped', 'box_number', 'stock_at_ship')
    readonly_fields = ('stock_at_ship',)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'country', 'status', 'shipment_date', 'total_units', 'box_count')
    list_filter = ('country', 'status')
    inlines = [ShipmentItemInline]
