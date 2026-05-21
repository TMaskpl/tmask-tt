from django.contrib import admin
from .models import Connection

@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'host', 'port', 'protocol', 'owner', 'created_at']
    list_filter = ['protocol', 'compress', 'encrypt']
    search_fields = ['name', 'host', 'owner__username']
    readonly_fields = ['created_at']
