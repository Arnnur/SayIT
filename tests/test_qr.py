import base64

from app.qr import make_qr_png, png_data_url

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_make_qr_png_returns_png():
    png = make_qr_png("https://example.com/s/abc123def0/")
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 200


def test_png_data_url():
    url = png_data_url(PNG_MAGIC + b"data")
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG_MAGIC + b"data"
