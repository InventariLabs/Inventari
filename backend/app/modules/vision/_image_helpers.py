"""Image processing helpers for Vision AI.

Extracted from ``service.py`` — pure functions with no LLM/DB dependencies.

What used to sit beside ``compress_image`` was ``get_storage_context``, which
turned a storage type into a sentence about frozen meat or dairy and defaulted
to a pantry. A shelf\'s temperature is one vertical\'s furniture; the scan\'s
intent travels as the label\'s ``context_tag`` now, and the sentence is gone.
"""

import io

from PIL import Image, ImageOps


def compress_image(
    image_bytes: bytes,
    max_size: tuple[int, int] = (1600, 1600),
    quality: int = 85,
) -> bytes:
    """Compress and resize an image, returning JPEG bytes."""
    img: Image.Image = Image.open(io.BytesIO(image_bytes))

    # A phone stores a portrait photograph sideways and says so in EXIF; the
    # JPEG written below carries no EXIF, so the turn is applied here or the
    # model is handed the label on its side.
    img = ImageOps.exif_transpose(img)

    # JPEG holds colour or grey and nothing else: transparency, a palette,
    # CMYK, 16-bit grey (a PNG from a scanner) all become RGB first, or the
    # save below refuses them.
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    # Resize if larger than max_size
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    return buffer.getvalue()
