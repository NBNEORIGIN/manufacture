from django.contrib import admin
from .models import ProductionOrder, ProductionStage


class ProductionStageInline(admin.TabularInline):
    model = ProductionStage
    extra = 0
    fields = ('stage', 'completed', 'completed_at', 'completed_by')
    readonly_fields = ('completed_at', 'completed_by')


@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'machine', 'priority', 'current_stage', 'created_at', 'completed_at')
    list_filter = ('machine', 'product__blank')
    search_fields = ('product__m_number', 'product__description')
    inlines = [ProductionStageInline]
