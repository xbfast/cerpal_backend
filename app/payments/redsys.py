"""Utilidades Redsys/SIS para generar pagos y validar notificaciones."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from Crypto.Cipher import DES3
from fastapi import HTTPException, status

SIGNATURE_VERSION = "HMAC_SHA256_V1"
_TEST_URL = "https://sis-t.redsys.es:25443/sis/realizarPago"
_PROD_URL = "https://sis.redsys.es/sis/realizarPago"


@dataclass(frozen=True)
class RedsysConfig:
    env: str
    merchant_code: str
    terminal: str
    secret_key: str
    notification_url: str
    url_ok: str
    url_ko: str

    @property
    def endpoint_url(self) -> str:
        return _PROD_URL if self.env == "prod" else _TEST_URL


def redsys_config() -> RedsysConfig:
    env = os.getenv("REDSYS_ENV", "test").strip().lower()
    cfg = RedsysConfig(
        env="prod" if env in ("prod", "production") else "test",
        merchant_code=os.getenv("REDSYS_MERCHANT_CODE", "").strip(),
        terminal=os.getenv("REDSYS_TERMINAL", "001").strip() or "001",
        secret_key=os.getenv("REDSYS_SECRET_KEY", "").strip(),
        notification_url=os.getenv("REDSYS_NOTIFICATION_URL", "").strip(),
        url_ok=os.getenv("REDSYS_URL_OK", "").strip(),
        url_ko=os.getenv("REDSYS_URL_KO", "").strip(),
    )
    missing = [
        name
        for name, value in (
            ("REDSYS_MERCHANT_CODE", cfg.merchant_code),
            ("REDSYS_SECRET_KEY", cfg.secret_key),
            ("REDSYS_NOTIFICATION_URL", cfg.notification_url),
            ("REDSYS_URL_OK", cfg.url_ok),
            ("REDSYS_URL_KO", cfg.url_ko),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redsys no está configurado ({', '.join(missing)}).",
        )
    return cfg


def amount_to_redsys_cents(amount: Decimal) -> str:
    cents = (Decimal(amount) * Decimal("100")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return str(int(cents))


def _b64_encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64_decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.b64decode(padded.replace("-", "+").replace("_", "/"))


def _merchant_parameters_b64(params: dict[str, Any]) -> str:
    payload = json.dumps(params, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _b64_encode(payload)


def decode_merchant_parameters(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(_b64_decode(raw).decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parámetros Redsys inválidos.",
        ) from e
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parámetros Redsys inválidos.",
        )
    return data


def _derive_order_key(secret_key: str, order: str) -> bytes:
    key = DES3.adjust_key_parity(_b64_decode(secret_key))
    cipher = DES3.new(key, DES3.MODE_CBC, iv=b"\0" * 8)
    block = order.encode("utf-8")
    block += b"\0" * (-len(block) % 8)
    return cipher.encrypt(block)


def sign_merchant_parameters(secret_key: str, order: str, merchant_parameters: str) -> str:
    order_key = _derive_order_key(secret_key, order)
    digest = hmac.new(
        order_key,
        merchant_parameters.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64_encode(digest)


def _signature_bytes(raw: str) -> bytes:
    return _b64_decode(raw.strip().replace(" ", "+"))


def signature_matches(expected: str, received: str) -> bool:
    try:
        return hmac.compare_digest(
            _signature_bytes(expected),
            _signature_bytes(received),
        )
    except Exception:
        return hmac.compare_digest(expected, received)


def build_payment_form(
    *,
    order: str,
    amount: Decimal,
    description: str,
    pedido_id: str,
) -> dict[str, str]:
    cfg = redsys_config()
    params = {
        "DS_MERCHANT_AMOUNT": amount_to_redsys_cents(amount),
        "DS_MERCHANT_ORDER": order,
        "DS_MERCHANT_MERCHANTCODE": cfg.merchant_code,
        "DS_MERCHANT_CURRENCY": "978",
        "DS_MERCHANT_TRANSACTIONTYPE": "0",
        "DS_MERCHANT_TERMINAL": cfg.terminal,
        "DS_MERCHANT_MERCHANTURL": cfg.notification_url,
        "DS_MERCHANT_URLOK": f"{cfg.url_ok}?pedido={pedido_id}",
        "DS_MERCHANT_URLKO": f"{cfg.url_ko}?pedido={pedido_id}",
        "DS_MERCHANT_PRODUCTDESCRIPTION": description[:125],
    }
    merchant_parameters = _merchant_parameters_b64(params)
    return {
        "action": cfg.endpoint_url,
        "Ds_SignatureVersion": SIGNATURE_VERSION,
        "Ds_MerchantParameters": merchant_parameters,
        "Ds_Signature": sign_merchant_parameters(
            cfg.secret_key,
            order,
            merchant_parameters,
        ),
    }


def validate_notification_signature(
    *,
    merchant_parameters: str,
    signature: str,
) -> dict[str, Any]:
    cfg = redsys_config()
    params = decode_merchant_parameters(merchant_parameters)
    order = str(
        params.get("Ds_Order")
        or params.get("DS_ORDER")
        or params.get("Ds_Merchant_Order")
        or params.get("DS_MERCHANT_ORDER")
        or ""
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notificación Redsys sin pedido.",
        )
    expected = sign_merchant_parameters(cfg.secret_key, order, merchant_parameters)
    if not signature_matches(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firma Redsys inválida.",
        )
    return params


def response_is_paid(params: dict[str, Any]) -> bool:
    raw = str(params.get("Ds_Response") or params.get("DS_RESPONSE") or "").strip()
    try:
        code = int(raw)
    except ValueError:
        return False
    return 0 <= code <= 99
