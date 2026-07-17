"""Helpers to produce genuinely Stripe-signed webhook payloads.

These let tests exercise the REAL stripe.Webhook.construct_event HMAC verification
path (no SDK mocking, no network), so a regression in signature handling — or in
the grant/invoice handlers it gates — is actually caught.

Stripe's construct_event computes HMAC-SHA256 over f"{timestamp}.{raw_body}" keyed
by the webhook secret verbatim, and compares against the v1 scheme in the
Stripe-Signature header. We reproduce that exactly.
"""

import hashlib
import hmac
import json
import time


def event_dict(event_id: str, event_type: str, obj: dict) -> dict:
    """Build the canonical Stripe event envelope construct_event expects."""
    return {
        'id': event_id,
        'object': 'event',
        'api_version': '2026-03-25.dahlia',
        'created': int(time.time()),
        'type': event_type,
        'data': {'object': obj},
    }


def signed_event(event: dict, secret: str, timestamp: int | None = None) -> tuple[bytes, str]:
    """Return (body_bytes, stripe_signature_header) for a real construct_event.

    Pass a `timestamp` far in the past to exercise the replay/tolerance rejection.
    """
    body = json.dumps(event).encode()
    ts = int(time.time()) if timestamp is None else int(timestamp)
    signed_payload = f'{ts}.'.encode() + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    header = f't={ts},v1={signature}'
    return body, header
