from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = 'chat'
    verbose_name = 'Chat'

    def ready(self):
        from . import signals  # noqa: F401
