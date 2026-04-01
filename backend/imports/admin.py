from django.contrib import admin
from .models import ImportLog


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ('import_type', 'filename', 'rows_processed', 'rows_created', 'rows_updated', 'rows_skipped', 'created_at')
    list_filter = ('import_type',)
    readonly_fields = ('errors',)
