"""Generador de imagenes de producto en SVG.

Decision de diseno: en lugar de depender de URLs externas (que pueden caerse y
dejar la grilla con imagenes rotas), cada producto recibe un SVG generado
localmente. La forma del envase depende de la subcategoria y los colores se
derivan de un hash del nombre, de modo que cada producto tiene una imagen
distinta pero coherente con su categoria.

Los archivos se escriben en app/static/images/products/ y se sirven como
archivos estaticos comunes.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_DIR = BASE_DIR / "static" / "images" / "products"
CATEGORIES_DIR = BASE_DIR / "static" / "images" / "categories"

# Paletas por familia de producto (fondo suave, cuerpo, acento)
PALETTES = [
    ("#e6f4f1", "#0f9d8f", "#0b6b62"),
    ("#e8f0fe", "#2f6fed", "#1b46a8"),
    ("#fdeef2", "#e04f7a", "#a92e52"),
    ("#fff4e5", "#f59f28", "#b96f0c"),
    ("#eef1fb", "#6c63c7", "#443c96"),
    ("#eaf7ea", "#3faa54", "#26773a"),
    ("#fef2e8", "#e2703a", "#a94a20"),
    ("#eef7fb", "#2aa3c7", "#146e8b"),
    ("#f4eefb", "#8f56c9", "#5f3193"),
    ("#fdf0ec", "#d8543f", "#9c3524"),
]

# Palabras clave -> forma del envase
SHAPE_KEYWORDS = {
    "bottle": ("detergente", "lavandina", "suavizante", "jabon liquido", "limpiador", "limpiapiso",
               "desengrasante", "quitamancha", "jabon", "liquido", "cera", "shampoo"),
    "spray": ("aromatizante", "desinfectante", "limpiavidrio", "spray", "aerosol", "perfume",
              "antigrasa", "sanitizante"),
    "box": ("polvo", "jabon en polvo", "caja", "pastilla", "bolsa", "residuo", "detergente en polvo"),
    "roll": ("papel", "rollo", "servilleta", "toalla", "higienico"),
    "tool": ("escoba", "mopa", "secador", "cepillo", "balde", "palo", "plumero", "recogedor"),
    "soft": ("esponja", "guante", "trapo", "rejilla", "panio", "franela", "fibra", "microfibra"),
}


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "item"


def _normalize(text: str) -> str:
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}
    text = (text or "").lower()
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _hash(text: str) -> int:
    return int(hashlib.md5(_normalize(text).encode("utf-8")).hexdigest(), 16)


def pick_shape(product_name: str, subcategory: str | None = None) -> str:
    haystack = _normalize(f"{subcategory or ''} {product_name}")
    for shape, keywords in SHAPE_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return shape
    return "bottle"


def _label_lines(text: str, max_chars: int = 16, max_lines: int = 2) -> list[str]:
    words = (text or "").split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _body(shape: str, main: str, accent: str, light: str) -> str:
    """Devuelve el SVG del envase segun la forma."""
    if shape == "spray":
        return f"""
  <path d="M188 118h58v22h-58z" fill="{accent}"/>
  <path d="M170 96h44v26h-44z" fill="{accent}" opacity=".85"/>
  <rect x="176" y="132" width="88" height="24" rx="8" fill="{accent}"/>
  <rect x="164" y="150" width="112" height="180" rx="26" fill="{main}"/>
  <rect x="180" y="196" width="80" height="76" rx="10" fill="{light}" opacity=".92"/>
  <rect x="176" y="160" width="20" height="150" rx="10" fill="#ffffff" opacity=".22"/>"""
    if shape == "box":
        return f"""
  <path d="M132 150l88-32 88 32v168l-88 32-88-32z" fill="{main}"/>
  <path d="M220 118l88 32v168l-88 32z" fill="{accent}" opacity=".9"/>
  <path d="M132 150l88 32v168l-88-32z" fill="#000000" opacity=".08"/>
  <rect x="156" y="196" width="128" height="86" rx="10" fill="{light}" opacity=".95"/>"""
    if shape == "roll":
        return f"""
  <rect x="140" y="140" width="160" height="190" rx="18" fill="{main}"/>
  <ellipse cx="220" cy="140" rx="80" ry="26" fill="{light}"/>
  <ellipse cx="220" cy="140" rx="30" ry="10" fill="{accent}"/>
  <rect x="152" y="150" width="18" height="170" rx="9" fill="#ffffff" opacity=".22"/>
  <rect x="168" y="214" width="104" height="62" rx="10" fill="{light}" opacity=".92"/>"""
    if shape == "tool":
        return f"""
  <rect x="208" y="70" width="24" height="200" rx="12" fill="{accent}"/>
  <rect x="150" y="262" width="140" height="42" rx="12" fill="{main}"/>
  <path d="M154 304h132l-12 56h-108z" fill="{accent}" opacity=".9"/>
  <rect x="212" y="86" width="8" height="170" rx="4" fill="#ffffff" opacity=".28"/>"""
    if shape == "soft":
        return f"""
  <rect x="128" y="168" width="184" height="120" rx="26" fill="{main}"/>
  <rect x="128" y="168" width="184" height="46" rx="22" fill="{light}"/>
  <circle cx="176" cy="252" r="10" fill="#ffffff" opacity=".35"/>
  <circle cx="220" cy="262" r="8" fill="#ffffff" opacity=".3"/>
  <circle cx="262" cy="248" r="11" fill="#ffffff" opacity=".28"/>"""
    # bottle (por defecto)
    return f"""
  <rect x="196" y="92" width="48" height="34" rx="8" fill="{accent}"/>
  <path d="M198 126h44l26 34v10h-96v-10z" fill="{accent}" opacity=".85"/>
  <rect x="150" y="168" width="140" height="176" rx="30" fill="{main}"/>
  <rect x="172" y="212" width="96" height="82" rx="12" fill="{light}" opacity=".95"/>
  <rect x="163" y="186" width="22" height="140" rx="11" fill="#ffffff" opacity=".22"/>"""


def build_svg(name: str, brand: str = "", subcategory: str | None = None, seed: str | None = None) -> str:
    digest = _hash(seed or f"{brand}{name}")
    background, main, accent = PALETTES[digest % len(PALETTES)]
    light = "#ffffff"
    shape = pick_shape(name, subcategory)
    lines = _label_lines(name)

    text_block = ""
    y = 244 if len(lines) > 1 else 252
    for line in lines:
        text_block += (
            f'\n  <text x="220" y="{y}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="15" font-weight="700" fill="{accent}">{_escape(line)}</text>'
        )
        y += 20

    brand_text = ""
    if brand:
        brand_text = (
            f'\n  <text x="220" y="{y + 2}" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="11" letter-spacing="1.6" fill="{main}">{_escape(brand.upper()[:18])}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 440" width="440" height="440" role="img" aria-label="{_escape(name)}">
  <rect width="440" height="440" fill="{background}"/>
  <circle cx="352" cy="88" r="66" fill="{main}" opacity=".13"/>
  <circle cx="78" cy="368" r="52" fill="{accent}" opacity=".10"/>
  <ellipse cx="220" cy="374" rx="118" ry="16" fill="{accent}" opacity=".14"/>{_body(shape, main, accent, light)}{text_block}{brand_text}
</svg>
"""


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def generate_product_image(product, overwrite: bool = False) -> str:
    """Crea (si hace falta) el SVG del producto y devuelve su ruta relativa a /static."""
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(product.sku or product.name)}.svg"
    path = PRODUCTS_DIR / filename
    if overwrite or not path.exists():
        path.write_text(
            build_svg(product.name, product.brand or "", product.subcategory, seed=product.sku),
            encoding="utf-8",
        )
    return f"images/products/{filename}"


def generate_category_image(category, overwrite: bool = False) -> str:
    """Banner cuadrado para las tarjetas de categoria."""
    CATEGORIES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(category.slug or category.name)}.svg"
    path = CATEGORIES_DIR / filename
    if overwrite or not path.exists():
        digest = _hash(category.name)
        background, main, accent = PALETTES[digest % len(PALETTES)]
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300" role="img" aria-label="{_escape(category.name)}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{background}"/>
      <stop offset="100%" stop-color="{main}" stop-opacity=".35"/>
    </linearGradient>
  </defs>
  <rect width="400" height="300" fill="url(#g)"/>
  <circle cx="330" cy="66" r="70" fill="{main}" opacity=".18"/>
  <circle cx="64" cy="250" r="48" fill="{accent}" opacity=".14"/>
  <text x="200" y="168" text-anchor="middle" font-size="76">{_escape(category.icon or "")}</text>
</svg>
"""
        path.write_text(svg, encoding="utf-8")
    return f"images/categories/{filename}"
