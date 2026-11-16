import base64
import unittest
from uuid import uuid4

from tickets.services.qr_signing import (
    MalformedToken,
    fingerprint,
    parse_token,
    render_qr_png,
    sign_ticket,
    verify_signature,
)


class QRSigningTests(unittest.TestCase):
    def setUp(self):
        self.ticket_id = uuid4()
        self.event_id = uuid4()
        self.user_id = 42
        self.token = sign_ticket(self.ticket_id, self.event_id, self.user_id)

    def test_round_trip(self):
        parsed = parse_token(self.token)

        self.assertEqual(parsed.ticket_id, self.ticket_id)
        self.assertEqual(parsed.event_id, self.event_id)
        self.assertEqual(parsed.user_id, self.user_id)
        self.assertTrue(verify_signature(parsed))

    def test_altering_each_signed_field_invalidates_signature(self):
        segments = self.token.split('.')
        for index in range(1, 5):
            altered = list(segments)
            decoded = bytearray(
                base64.urlsafe_b64decode(altered[index] + '=' * (-len(altered[index]) % 4))
            )
            decoded[-1] ^= 1
            altered[index] = base64.urlsafe_b64encode(decoded).decode().rstrip('=')

            parsed = parse_token('.'.join(altered))
            self.assertFalse(verify_signature(parsed))

    def test_malformed_tokens_raise(self):
        malformed_tokens = (
            '',
            'v2.a.b.c.d',
            self.token + '.extra',
            '.'.join(self.token.split('.')[:-1]),
            'v1.!!!!.valid.valid.valid',
        )
        for token in malformed_tokens:
            with self.subTest(token=token):
                with self.assertRaises(MalformedToken):
                    parse_token(token)

    def test_png_signature(self):
        self.assertTrue(render_qr_png(self.token).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_token_length_is_compact(self):
        self.assertLessEqual(len(self.token), 100)

    def test_fingerprint_is_sha256_hex(self):
        self.assertEqual(len(fingerprint(self.token)), 64)
