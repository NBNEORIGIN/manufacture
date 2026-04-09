from django.contrib import admin
from .models import ProductBarcode, PrintJob, FNSKUSyncLog


@admin.register(ProductBarcode)
class ProductBarcodeAdmin(admin.ModelAdmin):
    list_display = ['product', 'marketplace', 'barcode_type', 'barcode_value', 'condition', 'source', 'last_synced_at']
    search_fields = ['barcode_value', 'product__m_number', 'label_title']
    list_filter = ['marketplace', 'barcode_type', 'source']
    raw_id_fields = ['product']


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'barcode', 'quantity', 'status', 'command_language', 'agent_id', 'created_at']
    search_fields = ['barcode__barcode_value', 'barcode__product__m_number', 'agent_id']
    list_filter = ['status', 'command_language']
    readonly_fields = ['command_payload', 'claimed_at', 'printed_at', 'created_at', 'updated_at']


@admin.register(FNSKUSyncLog)
class FNSKUSyncLogAdmin(admin.ModelAdmin):
    list_display = ['marketplace', 'ran_at', 'created', 'updated', 'unmatched_count', 'error_message']
    list_filter = ['marketplace']
    readonly_fields = ['ran_at', 'created', 'updated', 'unmatched_count', 'error_message']
