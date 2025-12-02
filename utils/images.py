from __future__ import annotations

from io import BytesIO
from typing import Any, Union

from PIL import Image, ImageOps


ImageInput = Union[Image.Image, BytesIO, bytes, bytearray, Any]

# Image optimization defaults for survey photos
MAX_IMAGE_DIM = 1600  # max pixels on longest side
JPEG_QUALITY = 75     # balance between size and clarity


def normalize_image_orientation(file_or_image: ImageInput) -> Image.Image:
    """
    Open an image (UploadedFile, bytes/BytesIO, or PIL.Image) and normalize its
    orientation using EXIF data.

    - If an EXIF Orientation tag is present, apply the corresponding rotation/
      flip so the returned image pixels are upright.
    - The EXIF orientation flag is cleared/normalized so downstream consumers
      don't need to re-interpret it.
    - If no EXIF is present or any step fails, the image is returned as-is.
    """
    # 1) Obtain a PIL.Image.Image
    if isinstance(file_or_image, Image.Image):
        img = file_or_image
    else:
        # Support raw bytes / bytearray
        if isinstance(file_or_image, (bytes, bytearray)):
            stream = BytesIO(file_or_image)
        else:
            # Assume file-like (has read/seek) such as Streamlit's UploadedFile
            stream = file_or_image  # type: ignore[assignment]
        img = Image.open(stream)

    # 2) Normalize using Pillow's EXIF-aware transpose helper.
    #    This both applies the orientation transform and resets the flag.
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        # If anything goes wrong (no EXIF, corrupted tag, etc.), just return
        # the original image object.
        pass

    return img


def process_survey_image(file_or_image: ImageInput) -> bytes:
    """
    Full survey image processing pipeline:

    1) Normalize orientation via EXIF (see normalize_image_orientation).
    2) Downscale if either side exceeds MAX_IMAGE_DIM, preserving aspect ratio.
    3) Re-encode as JPEG with JPEG_QUALITY, stripping metadata/EXIF.

    Returns JPEG bytes suitable for storage in Streamlit session_state and
    direct embedding into the PDF builder.
    """
    img = normalize_image_orientation(file_or_image)

    # Ensure a mode compatible with JPEG
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        # For consistency across devices, prefer RGB output
        img = img.convert("RGB")

    # Resize if necessary, preserving aspect ratio
    try:
        width, height = img.size
        longest = max(width, height)
        if longest > MAX_IMAGE_DIM:
            scale = MAX_IMAGE_DIM / float(longest)
            new_size = (int(width * scale), int(height * scale))
            if new_size[0] <= 0 or new_size[1] <= 0:
                # Defensive: if calculation goes odd, skip resize
                new_size = (max(1, width), max(1, height))
            img = img.resize(new_size, Image.LANCZOS)
    except Exception:
        # If anything goes wrong while resizing, fall back to original size
        pass

    # Encode as compressed JPEG into memory.
    # Not passing any EXIF data strips metadata (GPS, camera info, etc.).
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()
