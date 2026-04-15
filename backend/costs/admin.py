from django.contrib import admin

from .models import BlankCost, CostConfig, MNumberCostOverride


@admin.register(BlankCost)
class BlankCostAdmin(admin.ModelAdmin):
    list_display = ('normalized_name', 'display_name', 'material_cost_gbp',
                    'labour_minutes', 'product_count', 'is_composite')
    search_fields = ('normalized_name', 'display_name', 'sample_raw_blank')
    list_filter = ('is_composite',)


@admin.register(MNumberCostOverride)
class MNumberCostOverrideAdmin(admin.ModelAdmin):
    list_display = ('product', 'cost_price_gbp')
    search_fields = ('product__m_number', 'product__description', 'notes')


@admin.register(CostConfig)
class CostConfigAdmin(admin.ModelAdmin):
    list_display = ('labour_rate_gbp_per_hour', 'overhead_per_unit_gbp',
                    'default_material_gbp', 'vat_rate_uk')
