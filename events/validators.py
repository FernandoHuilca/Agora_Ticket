import os
from PIL import Image, UnidentifiedImageError
from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_PILLOW_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_FILE_SIZE_MB = 2


def validate_event_image(file):
    """
    Valida tamaño, extensión y estructura binaria real de la imagen.
    Bloquea archivos SVG y poliglotas para prevenir Stored XSS y DoS.
    """
    if not file:
        return

    # 1. Validar tamaño máximo (2 MB)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise ValidationError(
            f"La imagen no puede superar los {MAX_FILE_SIZE_MB} MB."
        )

    # 2. Validar extensión permitida (rechaza .svg explícitamente)
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Formato no permitido. Usa únicamente imágenes JPG, PNG o WEBP (no se admiten SVG)."
        )

    # 3. Validar contenido binario real con Pillow
    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()
            if img.format not in ALLOWED_PILLOW_FORMATS:
                raise ValidationError(
                    "El contenido del archivo no corresponde a una imagen válida (JPG, PNG, WEBP)."
                )
    except (UnidentifiedImageError, Exception) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("El archivo subido está corrupto o no es una imagen válida.")
    finally:
        file.seek(0)