import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

MAX_MESSAGE_LENGTH = 1000


class Conversation(models.Model):
    """Canal de chat ligado a un evento.

    GENERAL: sala del evento (organizador + todos los compradores con ticket).
    PRIVATE: conversación 1 a 1 entre un comprador y el organizador del evento.
    """

    class Kind(models.TextChoices):
        GENERAL = 'GENERAL', 'Sala general del evento'
        PRIVATE = 'PRIVATE', 'Privada comprador–organizador'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='conversations',
        verbose_name='Evento',
    )
    kind = models.CharField('Tipo', max_length=10, choices=Kind.choices)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='buyer_conversations',
        verbose_name='Comprador',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Desnormalizado para ordenar la bandeja sin agregar sobre los mensajes.
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        ordering = ['-last_message_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event'],
                condition=Q(kind='GENERAL'),
                name='uq_chat_general_per_event',
            ),
            models.UniqueConstraint(
                fields=['event', 'buyer'],
                condition=Q(kind='PRIVATE'),
                name='uq_chat_private_per_buyer',
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind='GENERAL', buyer__isnull=True)
                    | Q(kind='PRIVATE', buyer__isnull=False)
                ),
                name='chk_chat_kind_matches_buyer',
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.GENERAL:
            return f'Sala general · {self.event}'
        return f'Privada · {self.event} · {self.buyer}'

    @property
    def is_general(self):
        return self.kind == self.Kind.GENERAL


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='chat_messages',
    )
    body = models.TextField('Mensaje', max_length=MAX_MESSAGE_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        ordering = ['id']
        indexes = [
            # Historial paginado y conteo de no leídos por conversación.
            models.Index(
                fields=['conversation', 'created_at'],
                name='idx_chat_msg_conv_created',
            ),
        ]

    def __str__(self):
        return f'{self.sender_id} → {self.conversation_id}: {self.body[:40]}'


class ConversationRead(models.Model):
    """Hasta qué momento leyó cada usuario una conversación (para los no leídos)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='reads',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_reads',
    )
    last_read_at = models.DateTimeField()

    class Meta:
        verbose_name = 'Lectura de conversación'
        verbose_name_plural = 'Lecturas de conversación'
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'user'],
                name='uq_chat_read_conv_user',
            ),
        ]

    def __str__(self):
        return f'{self.user_id} leyó {self.conversation_id} hasta {self.last_read_at}'


class Presence(models.Model):
    """Una fila por conexión WebSocket abierta dentro de una conversación.

    Se guarda en la base de datos (y no en memoria) para que el indicador de
    conectados siga siendo correcto si la aplicación corre con varios procesos.
    `last_seen` se renueva con el latido del cliente; las filas vencidas se
    ignoran, de modo que un reinicio del servidor no deja "fantasmas".
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='presences',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_presences',
    )
    role = models.CharField(max_length=10)
    channel_name = models.CharField(max_length=255, unique=True)
    last_seen = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = 'Conexión activa'
        verbose_name_plural = 'Conexiones activas'

    def __str__(self):
        return f'{self.user_id} en {self.conversation_id}'
