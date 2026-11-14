import os
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_PILLOW_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_FILE_SIZE_MB = 2


def validate_event_image(file):
    """
    Valida tamaño, extensión y estructura binaria real de la imagen.
    Bloquea archivos SVG y poliglotas para prevenir Stored XSS y DoS.
    """
    # Si no hay archivo o ya fue validado y guardado previamente en el storage (ej. Cloudinary public_id sin extensión)
    if not file or getattr(file, '_committed', False):
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

def sanitize_and_optimize_image(image_field):
    """
    Re-codifica la imagen con Pillow para eliminar metadatos EXIF (GPS, dispositivo),
    neutralizar cargas ocultas (polyglots) y optimizar su tamaño a formato WEBP/JPEG.
    """
    if not image_field:
        return image_field

    image_field.file.seek(0)
    with Image.open(image_field.file) as img:
        # Convertir a RGB si viene en modo RGBA/P para evitar errores de canal alfa
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        # Limitar resolución máxima a 1600x1600 px manteniendo proporción
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

        output = BytesIO()
        # Guardar como WEBP (o JPEG) nuevo descarta toda la tabla EXIF original
        img.save(output, format='WEBP', quality=85)
        output.seek(0)

        base_name = os.path.splitext(os.path.basename(image_field.name))[0]
        clean_name = f"{base_name}.webp"

        return InMemoryUploadedFile(
            file=output,
            field_name='ImageField',
            name=clean_name,
            content_type='image/webp',
            size=output.getbuffer().nbytes,
            charset=None,
        )