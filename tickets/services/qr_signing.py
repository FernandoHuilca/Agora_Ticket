"""Stateless signing and rendering of ticket QR tokens.

Ticket and event IDs use their 16-byte UUID representation. Current users use
integer primary keys, so user IDs are encoded as a tagged unsigned integer
(`i`) using only the bytes required by the value; UUID users use a tagged
16-byte payload (`u`). The tags make both forms unambiguous while keeping the
QR payload compact.
"""

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass
from io import BytesIO
from typing import Union
from uuid import UUID

import qrcode
from django.conf import settings


_VERSION = 'v1'
_UUID_SEGMENT_LENGTH = 22
_MAC_LENGTH = 16
_MAX_INTEGER_USER_ID_BYTES = 8
_USER_MIN_SEGMENT_LENGTH = 3
_USER_MAX_SEGMENT_LENGTH = 23


class MalformedToken(ValueError):
    """Raised when a QR token does not follow the expected wire format."""


@dataclass(frozen=True)
class ParsedToken:
    ticket_id: UUID
    event_id: UUID
    user_id: Union[int, UUID]
    mac: str
    raw_signed_part: str


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decode_base64url(segment: str, *, min_length: int, max_length: int) -> bytes:
    if not min_length <= len(segment) <= max_length:
        raise MalformedToken('Segment length is invalid.')
    if any(character not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
           for character in segment):
        raise MalformedToken('Segment contains invalid base64url characters.')
    if len(segment) % 4 == 1:
        raise MalformedToken('Segment has invalid base64url padding.')

    try:
        decoded = base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
    except (ValueError, binascii.Error) as exc:
        raise MalformedToken('Segment is not valid base64url.') from exc
    return decoded


def _encode_user_id(user_id: Union[int, UUID]) -> str:
    if isinstance(user_id, UUID):
        return _encode_base64url(b'u' + user_id.bytes)
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError('user_id must be an integer or UUID.')
    if user_id < 0:
        raise ValueError('user_id must be non-negative.')

    byte_length = max(1, (user_id.bit_length() + 7) // 8)
    if byte_length > _MAX_INTEGER_USER_ID_BYTES:
        raise ValueError('Integer user_id must fit in 64 bits.')
    return _encode_base64url(b'i' + user_id.to_bytes(byte_length, 'big'))


def _decode_user_id(segment: str) -> Union[int, UUID]:
    decoded = _decode_base64url(
        segment,
        min_length=_USER_MIN_SEGMENT_LENGTH,
        max_length=_USER_MAX_SEGMENT_LENGTH,
    )
    if not decoded:
        raise MalformedToken('User segment is empty.')

    kind, payload = decoded[0:1], decoded[1:]
    if kind == b'u' and len(payload) == 16:
        return UUID(bytes=payload)
    if kind == b'i' and 1 <= len(payload) <= _MAX_INTEGER_USER_ID_BYTES:
        return int.from_bytes(payload, 'big')
    raise MalformedToken('User segment payload is invalid.')


def _sign(raw_signed_part: str) -> str:
    key = settings.TICKET_QR_SECRET.encode('utf-8')
    digest = hmac.new(key, raw_signed_part.encode('ascii'), hashlib.sha256).digest()
    return _encode_base64url(digest[:_MAC_LENGTH])


def sign_ticket(ticket_id: UUID, event_id: UUID, user_id: Union[int, UUID]) -> str:
    """Create a compact, signed QR token without accessing the database."""
    if not isinstance(ticket_id, UUID) or not isinstance(event_id, UUID):
        raise TypeError('ticket_id and event_id must be UUID instances.')

    signed_part = '.'.join((
        _VERSION,
        _encode_base64url(ticket_id.bytes),
        _encode_base64url(event_id.bytes),
        _encode_user_id(user_id),
    ))
    return f'{signed_part}.{_sign(signed_part)}'


def parse_token(token: str) -> ParsedToken:
    """Parse and validate token structure, without verifying its signature."""
    if not isinstance(token, str) or not token:
        raise MalformedToken('Token is empty.')

    segments = token.split('.')
    if len(segments) != 5 or segments[0] != _VERSION:
        raise MalformedToken('Token version or segment count is invalid.')

    _, ticket_segment, event_segment, user_segment, mac = segments
    if len(ticket_segment) != _UUID_SEGMENT_LENGTH:
        raise MalformedToken('Ticket segment length is invalid.')
    if len(event_segment) != _UUID_SEGMENT_LENGTH:
        raise MalformedToken('Event segment length is invalid.')
    if len(mac) != _UUID_SEGMENT_LENGTH:
        raise MalformedToken('MAC segment length is invalid.')

    ticket_bytes = _decode_base64url(
        ticket_segment,
        min_length=_UUID_SEGMENT_LENGTH,
        max_length=_UUID_SEGMENT_LENGTH,
    )
    event_bytes = _decode_base64url(
        event_segment,
        min_length=_UUID_SEGMENT_LENGTH,
        max_length=_UUID_SEGMENT_LENGTH,
    )
    mac_bytes = _decode_base64url(
        mac,
        min_length=_UUID_SEGMENT_LENGTH,
        max_length=_UUID_SEGMENT_LENGTH,
    )
    if len(ticket_bytes) != 16 or len(event_bytes) != 16 or len(mac_bytes) != _MAC_LENGTH:
        raise MalformedToken('Token segment payload length is invalid.')

    _decode_base64url(
        user_segment,
        min_length=_USER_MIN_SEGMENT_LENGTH,
        max_length=_USER_MAX_SEGMENT_LENGTH,
    )
    user_id = _decode_user_id(user_segment)
    raw_signed_part = '.'.join(segments[:4])

    return ParsedToken(
        ticket_id=UUID(bytes=ticket_bytes),
        event_id=UUID(bytes=event_bytes),
        user_id=user_id,
        mac=mac,
        raw_signed_part=raw_signed_part,
    )


def verify_signature(parsed: ParsedToken) -> bool:
    """Verify the token MAC using constant-time comparison."""
    expected_mac = _sign(parsed.raw_signed_part)
    return hmac.compare_digest(expected_mac, parsed.mac)


def render_qr_png(token: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')

    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
