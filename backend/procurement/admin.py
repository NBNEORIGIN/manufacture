from django.contrib import admin
from .models import Material


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('material_id', 'name', 'category', 'current_stock', 'reorder_point', 'needs_reorder')
    list_filter = ('category',)
    search_fields = ('name', 'material_id')
