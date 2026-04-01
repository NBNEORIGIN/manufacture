from django.contrib import admin
from .models import StockLevel


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ('product', 'current_stock', 'fba_stock', 'sixty_day_sales', 'optimal_stock_30d', 'stock_deficit')
    list_filter = ('product__blank',)
    search_fields = ('product__m_number', 'product__description')
    readonly_fields = ('stock_deficit',)
