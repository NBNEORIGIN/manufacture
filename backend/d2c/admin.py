from django.contrib import admin
from .models import DispatchOrder


@admin.register(DispatchOrder)
class DispatchOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'sku', 'quantity', 'status', 'flags', 'channel', 'order_date', 'assigned_to')
    list_filter = ('status', 'channel')
    search_fields = ('order_id', 'sku', 'description', 'flags', 'customer_name', 'product__m_number')
