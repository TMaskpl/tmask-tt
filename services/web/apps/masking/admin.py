from django.contrib import admin
from .models import MaskingRule


@admin.register(MaskingRule)
class MaskingRuleAdmin(admin.ModelAdmin):
    list_display = ('connection', 'table_name', 'column_name', 'faker_provider', 'created_by', 'created_at')
    list_filter = ('faker_provider', 'connection')
