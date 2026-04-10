"""
Admin for the FBA Shipments module.

The FBAAPICall list is the primary debugging interface — when a plan gets stuck
or errors out, the admin is where Ben/Toby look to find out exactly which SP-API
call broke and what Amazon said.
"""

import json

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    FBAAPICall,
    FBABox,
    FBABoxItem,
    FBAShipment,
    FBAShipmentPlan,
    FBAShipmentPlanItem,
)


# Colour map for the status pill in the plan list view.
STATUS_COLOURS = {
    'draft':                      '#9ca3af',  # grey
    'items_added':                '#9ca3af',
    'plan_creating':              '#60a5fa',  # blue shades = working
    'plan_created':               '#60a5fa',
    'packing_generating':         '#60a5fa',
    'packing_options_fetching':   '#60a5fa',
    'packing_options_ready':      '#fbbf24',  # amber = awaiting human
    'packing_info_setting':       '#60a5fa',
    'packing_info_set':           '#60a5fa',
    'packing_confirming':         '#60a5fa',
    'packing_confirmed':          '#60a5fa',
    'placement_generating':       '#60a5fa',
    'placement_options_fetching': '#60a5fa',
    'placement_options_ready':    '#fbbf24',
    'placement_confirming':       '#60a5fa',
    'placement_confirmed':        '#60a5fa',
    'transport_generating':       '#60a5fa',
    'transport_options_fetching': '#60a5fa',
    'transport_options_ready':    '#60a5fa',
    'delivery_window_generating': '#60a5fa',
    'delivery_window_fetching':   '#60a5fa',
    'delivery_window_ready':      '#60a5fa',
    'transport_confirming':       '#60a5fa',
    'transport_confirmed':        '#60a5fa',
    'labels_fetching':            '#60a5fa',
    'ready_to_ship':              '#10b981',  # green = done / good
    'dispatched':                 '#059669',
    'cancelled':                  '#6b7280',
    'error':                      '#ef4444',  # red
}


def _pretty_json(value) -> str:
    if value in (None, ''):
        return '—'
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


class FBAShipmentPlanItemInline(admin.TabularInline):
    model = FBAShipmentPlanItem
    extra = 0
    fields = ('sku', 'msku', 'fnsku', 'quantity', 'label_owner', 'prep_owner')
    readonly_fields = ('msku', 'fnsku')


class FBABoxInline(admin.TabularInline):
    model = FBABox
    extra = 0
    fields = ('box_number', 'length_cm', 'width_cm', 'height_cm', 'weight_kg', 'amazon_box_id')
    fk_name = 'plan'


class FBAShipmentInline(admin.TabularInline):
    model = FBAShipment
    extra = 0
    fields = ('shipment_id', 'shipment_confirmation_id', 'destination_fc', 'carrier_name', 'tracking_number', 'dispatched_at')
    readonly_fields = ('shipment_id', 'shipment_confirmation_id', 'destination_fc')


@admin.register(FBAShipmentPlan)
class FBAShipmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'marketplace',
        'status_pill',
        'item_count',
        'inbound_plan_id',
        'created_by',
        'created_at',
    )
    list_filter = ('status', 'marketplace', 'created_at')
    search_fields = ('name', 'inbound_plan_id')
    readonly_fields = (
        'created_at',
        'updated_at',
        'current_operation_started_at',
        'last_polled_at',
        'error_log_pretty',
        'packing_options_pretty',
        'placement_options_pretty',
        'transportation_options_pretty',
        'delivery_window_pretty',
    )
    fieldsets = (
        ('Plan', {
            'fields': ('name', 'marketplace', 'ship_from_address', 'created_by', 'status'),
        }),
        ('Amazon references', {
            'fields': (
                'inbound_plan_id',
                'selected_packing_option_id',
                'selected_placement_option_id',
                'selected_transportation_option_id',
                'selected_delivery_window_id',
            ),
        }),
        ('Async operation tracking', {
            'fields': (
                'current_operation_id',
                'current_operation_started_at',
                'last_polled_at',
            ),
        }),
        ('Debug / audit', {
            'classes': ('collapse',),
            'fields': (
                'error_log_pretty',
                'packing_options_pretty',
                'placement_options_pretty',
                'transportation_options_pretty',
                'delivery_window_pretty',
                'created_at',
                'updated_at',
            ),
        }),
    )
    inlines = [FBAShipmentPlanItemInline, FBABoxInline, FBAShipmentInline]

    @admin.display(description='Status', ordering='status')
    def status_pill(self, obj: FBAShipmentPlan) -> str:
        colour = STATUS_COLOURS.get(obj.status, '#9ca3af')
        label = obj.get_status_display()
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">{}</span>',
            colour,
            label,
        )

    @admin.display(description='Items')
    def item_count(self, obj: FBAShipmentPlan) -> int:
        return obj.items.count()

    @admin.display(description='Error log')
    def error_log_pretty(self, obj: FBAShipmentPlan) -> str:
        return mark_safe(f'<pre style="max-height:300px;overflow:auto;">{_pretty_json(obj.error_log)}</pre>')

    @admin.display(description='Packing options')
    def packing_options_pretty(self, obj: FBAShipmentPlan) -> str:
        return mark_safe(f'<pre style="max-height:300px;overflow:auto;">{_pretty_json(obj.packing_options_snapshot)}</pre>')

    @admin.display(description='Placement options')
    def placement_options_pretty(self, obj: FBAShipmentPlan) -> str:
        return mark_safe(f'<pre style="max-height:300px;overflow:auto;">{_pretty_json(obj.placement_options_snapshot)}</pre>')

    @admin.display(description='Transportation options')
    def transportation_options_pretty(self, obj: FBAShipmentPlan) -> str:
        return mark_safe(f'<pre style="max-height:300px;overflow:auto;">{_pretty_json(obj.transportation_options_snapshot)}</pre>')

    @admin.display(description='Delivery window snapshot')
    def delivery_window_pretty(self, obj: FBAShipmentPlan) -> str:
        return mark_safe(f'<pre style="max-height:300px;overflow:auto;">{_pretty_json(obj.delivery_window_snapshot)}</pre>')


@admin.register(FBAShipmentPlanItem)
class FBAShipmentPlanItemAdmin(admin.ModelAdmin):
    list_display = ('plan', 'msku', 'fnsku', 'quantity', 'label_owner', 'prep_owner')
    list_filter = ('label_owner', 'prep_owner')
    search_fields = ('msku', 'fnsku', 'plan__name')


class FBABoxItemInline(admin.TabularInline):
    model = FBABoxItem
    extra = 0
    fields = ('plan_item', 'quantity')


@admin.register(FBABox)
class FBABoxAdmin(admin.ModelAdmin):
    list_display = (
        'plan',
        'box_number',
        'length_cm',
        'width_cm',
        'height_cm',
        'weight_kg',
        'amazon_box_id',
    )
    list_filter = ('plan__marketplace',)
    search_fields = ('plan__name', 'amazon_box_id')
    inlines = [FBABoxItemInline]


@admin.register(FBAShipment)
class FBAShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'shipment_id',
        'shipment_confirmation_id',
        'plan',
        'destination_fc',
        'carrier_name',
        'tracking_number',
        'dispatched_at',
    )
    list_filter = ('dispatched_at', 'destination_fc')
    search_fields = (
        'shipment_id',
        'shipment_confirmation_id',
        'plan__name',
        'tracking_number',
    )
    readonly_fields = ('labels_url', 'labels_fetched_at')


@admin.register(FBAAPICall)
class FBAAPICallAdmin(admin.ModelAdmin):
    """
    Primary debugging surface for stuck or errored plans. Filter by plan +
    operation_name to narrow a failing flow, then inspect request/response.
    """

    list_display = (
        'created_at',
        'plan',
        'operation_name',
        'response_status',
        'operation_id',
        'duration_ms',
        'short_error',
    )
    list_filter = ('operation_name', 'response_status', 'created_at')
    search_fields = ('operation_id', 'plan__name', 'plan__inbound_plan_id', 'error_message')
    readonly_fields = (
        'plan',
        'operation_name',
        'request_body_pretty',
        'response_status',
        'response_body_pretty',
        'operation_id',
        'duration_ms',
        'error_message',
        'created_at',
        'updated_at',
    )
    fields = (
        'plan',
        'operation_name',
        'operation_id',
        'response_status',
        'duration_ms',
        'error_message',
        'request_body_pretty',
        'response_body_pretty',
        'created_at',
    )
    date_hierarchy = 'created_at'

    @admin.display(description='Error')
    def short_error(self, obj: FBAAPICall) -> str:
        if not obj.error_message:
            return ''
        return (obj.error_message[:60] + '…') if len(obj.error_message) > 60 else obj.error_message

    @admin.display(description='Request body')
    def request_body_pretty(self, obj: FBAAPICall) -> str:
        return mark_safe(f'<pre style="max-height:400px;overflow:auto;">{_pretty_json(obj.request_body)}</pre>')

    @admin.display(description='Response body')
    def response_body_pretty(self, obj: FBAAPICall) -> str:
        return mark_safe(f'<pre style="max-height:400px;overflow:auto;">{_pretty_json(obj.response_body)}</pre>')

    def has_add_permission(self, request) -> bool:
        return False  # only created by the SP-API wrapper
