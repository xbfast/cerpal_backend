import re

PLACEHOLDER_PRODUCT_IMAGE = (
    "/images/recursos/420a9dc8719477bf365bb50d5a293d338451c09e.jpg"
)


def slug_from_default_code(code: str | None) -> str:
    """Slug estable para URL a partir del código artículo (único en plantilla)."""
    raw = (code or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", raw)
    s = s.strip("-")
    return s or "producto"


def format_price_eur(value: float | None) -> str:
    """Misma forma que los mocks del frontend (`11.00€`)."""
    n = float(value or 0)
    return f"{n:.2f}€"


def color_label_to_swatch_key(label: str | None) -> str | None:
    """Mapea nombre de valor de color (BD) a claves de `catalogSwatches.js`."""
    if not label:
        return None
    n = label.lower()
    rules: list[tuple[tuple[str, ...], str]] = [
        (("blanc", "white", "9016", "9010"), "white"),
        (("negro", "black", "9005"), "black"),
        (("rojo", "red", "3020"), "red"),
        (("azul", "blue", "5005"), "blue"),
        (("verde", "green", "6018"), "green"),
        (("amarill", "yellow", "1023"), "yellow"),
        (("naranj", "orange", "2004"), "orange"),
        (("morad", "viole", "purple", "4005"), "purple"),
    ]
    for needles, key in rules:
        if any(x in n for x in needles):
            return key
    return None


def swatch_keys_from_color_names(names: list[str] | None) -> tuple[list[str], int]:
    """Devuelve (claves tailwind, extraColors) para la tarjeta de catálogo."""
    if not names:
        return [], 0
    seen: list[str] = []
    for nm in names:
        k = color_label_to_swatch_key(nm)
        if k and k not in seen:
            seen.append(k)
    max_visible = 4
    if len(seen) <= max_visible:
        return seen, 0
    return seen[:max_visible], len(seen) - max_visible


def truncate_text(text: str | None, max_len: int = 200) -> str:
    if not text:
        return ""
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"
