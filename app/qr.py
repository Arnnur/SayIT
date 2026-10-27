"""QR code generation."""

from __future__ import annotations

import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def make_qr_png(url: str) -> bytes:
    """PNG bytes of a QR code that opens `url`."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#111827", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_data_url(png: bytes) -> str:
    """Embed PNG bytes into a `data:` URL usable directly in <img src>."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
