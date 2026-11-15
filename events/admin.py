from django.contrib import admin
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'organizer',
        'category',
        'start_date',
        'capacity',
        'available_tickets',
        'status',
    )
    list_filter = ('status', 'category', 'is_free', 'is_adult_only')
    search_fields = ('name', 'description', 'location', 'organizer__email')
    readonly_fields = ('id', 'created_at', 'updated_at')
