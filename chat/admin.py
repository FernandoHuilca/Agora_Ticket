from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('event', 'kind', 'buyer', 'last_message_at')
    list_filter = ('kind',)
    search_fields = ('event__name', 'buyer__email')
    raw_id_fields = ('event', 'buyer')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender', 'created_at', 'body')
    search_fields = ('body', 'sender__email')
    raw_id_fields = ('conversation', 'sender')
    date_hierarchy = 'created_at'
