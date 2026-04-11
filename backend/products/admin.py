from django.contrib import admin
from .models import Product, SKU, BlankType


class SKUInline(admin.TabularInline):
    model = SKU
    extra = 0
    fields = ('sku', 'channel', 'asin', 'fnsku', 'active')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('m_number', 'description', 'blank', 'material', 'active', 'do_not_restock')
    list_filter = ('blank', 'active', 'do_not_restock', 'is_personalised')
    search_fields = ('m_number', 'description')
    inlines = [SKUInline]


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'channel', 'asin', 'active')
    list_filter = ('channel', 'active')
    search_fields = ('sku', 'asin', 'product__m_number')


@admin.register(BlankType)
class BlankTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'length_cm', 'width_cm', 'height_cm', 'weight_g', 'product_count')
    search_fields = ('name',)
    ordering = ('name',)

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = '# linked'
