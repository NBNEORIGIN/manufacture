from django.contrib import admin

from .models import (
    SalesVelocityHistory,
    UnmatchedSKU,
    ManualSale,
    SalesVelocityAPICall,
    OAuthCredential,
    DriftAlert,
)


@admin.register(SalesVelocityHistory)
class SalesVelocityHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'channel', 'snapshot_date', 'units_sold_30d')
    list_filter = ('channel', 'snapshot_date')
    search_fields = ('product__m_number', 'product__description')
    date_hierarchy = 'snapshot_date'


@admin.register(UnmatchedSKU)
class UnmatchedSKUAdmin(admin.ModelAdmin):
    list_display = (
        'channel', 'external_sku', 'units_sold_30d',
        'first_seen', 'last_seen', 'ignored', 'resolved_to',
    )
    list_filter = ('channel', 'ignored')
    search_fields = ('external_sku', 'title')
    raw_id_fields = ('resolved_to',)


@admin.register(ManualSale)
class ManualSaleAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity', 'sale_date', 'channel', 'entered_by')
    list_filter = ('channel', 'sale_date')
    search_fields = ('product__m_number', 'notes')
    raw_id_fields = ('product', 'entered_by')
    date_hierarchy = 'sale_date'


@admin.register(SalesVelocityAPICall)
class SalesVelocityAPICallAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'channel', 'endpoint',
        'response_status', 'duration_ms',
    )
    list_filter = ('channel', 'response_status')
    search_fields = ('endpoint', 'error_message')
    readonly_fields = (
        'channel', 'endpoint', 'request_params',
        'response_status', 'response_body', 'duration_ms',
        'error_message', 'created_at', 'updated_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        # Audit log is append-only via adapters, not via admin UI
        return False


@admin.register(OAuthCredential)
class OAuthCredentialAdmin(admin.ModelAdmin):
    list_display = (
        'provider', 'access_token_expires_at',
        'last_refreshed_at', 'scope_preview',
    )
    readonly_fields = (
        'access_token', 'access_token_expires_at', 'last_refreshed_at',
    )
    # refresh_token is editable so an admin can paste a rotated token if
    # something goes wrong with the consent flow.

    def scope_preview(self, obj):
        return (obj.scope[:60] + '…') if len(obj.scope or '') > 60 else obj.scope
    scope_preview.short_description = 'scope'


@admin.register(DriftAlert)
class DriftAlertAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'variance_pct', 'current_velocity',
        'rolling_avg_velocity', 'detected_at', 'acknowledged',
    )
    list_filter = ('acknowledged',)
    search_fields = ('product__m_number',)
    readonly_fields = (
        'product', 'detected_at', 'current_velocity',
        'rolling_avg_velocity', 'variance_pct',
    )
    actions = ['mark_acknowledged']
    date_hierarchy = 'detected_at'

    def has_add_permission(self, request):
        # Alerts are raised by the weekly sanity check, not by hand
        return False

    @admin.action(description='Mark selected alerts as acknowledged')
    def mark_acknowledged(self, request, queryset):
        from django.utils import timezone
        queryset.update(
            acknowledged=True,
            acknowledged_by=request.user,
            acknowledged_at=timezone.now(),
        )
