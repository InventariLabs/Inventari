"""Image processing helpers for Vision AI.

Extracted from ``service.py`` — pure functions with no LLM/DB dependencies.

What used to sit beside ``compress_image`` was ``get_storage_context``, which
turned a storage type into a sentence about frozen meat or dairy and defaulted
to a pantry. A shelf\'s temperature is one vertical\'s furniture; the scan\'s
intent travels as the label\'s ``context_tag`` now, and the sentence is gone.
"""

import io

from PIL import Image


def compress_image(
    image_bytes: bytes,
    max_size: tuple[int, int] = (1600, 1600),
    quality: int = 85,
) -> bytes:
    """Compress and resize an image, returning JPEG bytes."""
    img: Image.Image = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB if necessary (e.g. RGBA or CMYK)
    if img.mode in ('RGBA', 'P', 'CMYK'):
        img = img.convert('RGB')

    # Resize if larger than max_size
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    return buffer.getvalue()
