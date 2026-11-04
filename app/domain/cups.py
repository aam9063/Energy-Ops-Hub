"""Validación de CUPS (docs/spec.md, sección 10).

Formato: ``ES`` + 16 dígitos + 2 letras de control + sufijo opcional de 2 caracteres
(un dígito y una letra). Las letras de control salen del resto de dividir los 16 dígitos
entre 529, que es 23 al cuadrado: la primera letra es el cociente y la segunda el resto.
"""

import re

_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
_RE = re.compile(r"^ES(\d{16})([A-Z]{2})(\d[A-Z])?$")


def normalizar_cups(cups: str) -> str:
    """Quita los espacios y pasa a mayúsculas; es lo que se compara y se guarda."""
    return re.sub(r"\s+", "", cups or "").upper()


def letras_control(digitos16: str) -> str:
    """Devuelve las dos letras de control de los 16 dígitos de un CUPS."""
    resto = int(digitos16) % 529
    return _LETRAS[resto // 23] + _LETRAS[resto % 23]


def cups_valido(cups: str) -> bool:
    """True si el CUPS tiene la forma correcta y las letras de control cuadran."""
    coincidencia = _RE.match(normalizar_cups(cups))
    if coincidencia is None:
        return False
    return letras_control(coincidencia.group(1)) == coincidencia.group(2)
