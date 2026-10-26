"""
Renderizado de tablas en texto plano para consola (sin jinja2 / df.style).

Uso:
    from core.tables import Table, banner, kv_block
    t = Table(["Strike", "GEX $M", "Nivel"], aligns="rrl", title="PERFIL GEX")
    t.add_row([25000, "+12.40", "CALL WALL"])
    print(t.render())
"""
from __future__ import annotations

import os
import sys
import unicodedata
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Consola UTF-8 robusta en Windows (evita UnicodeEncodeError con σ, Δ, etc.)
# --------------------------------------------------------------------------- #
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

if os.name == "nt":  # habilita secuencias ANSI en conhost clásico
    os.system("")

_COLOR_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
    "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m",
}


def set_color(enabled: bool) -> None:
    global _COLOR_ENABLED
    _COLOR_ENABLED = enabled


def c(text: str, color: str) -> str:
    """Colorea texto si la consola lo soporta."""
    if not _COLOR_ENABLED or color not in _ANSI:
        return str(text)
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def visible_len(text: str) -> int:
    """Longitud visible (ignora ANSI y caracteres combinantes)."""
    out, i, n = 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\033":
            j = text.find("m", i)
            i = n if j < 0 else j + 1
            continue
        if not unicodedata.combining(ch):
            out += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        i += 1
    return out


def _pad(text: str, width: int, align: str) -> str:
    gap = max(width - visible_len(text), 0)
    if align == "r":
        return " " * gap + text
    if align == "c":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def fmt_num(x, decimals: int = 2, sign: bool = False, thousands: bool = True, suffix: str = "") -> str:
    """Formatea números de forma segura (NaN/None -> '-')."""
    try:
        if x is None or x != x:  # NaN
            return "-"
        spec = f"{'+' if sign else ''}{',' if thousands else ''}.{decimals}f"
        return f"{format(float(x), spec)}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def fmt_usd(x, decimals: int = 0, sign: bool = False) -> str:
    try:
        if x is None or x != x:
            return "-"
        s = format(abs(float(x)), f",.{decimals}f")
        prefix = "-" if float(x) < 0 else ("+" if sign else "")
        return f"{prefix}${s}"
    except (TypeError, ValueError):
        return str(x)


class Table:
    """Tabla ASCII alineada con estética institucional."""

    def __init__(self, headers: Sequence[str], aligns: str | None = None,
                 title: str | None = None, footer: str | Iterable[str] | None = None,
                 min_width: int = 0):
        self.headers = [str(h) for h in headers]
        self.aligns = (aligns or "l" * len(headers)).ljust(len(headers), "l")
        self.title = title
        self.footer = [footer] if isinstance(footer, str) else list(footer or [])
        self.rows: list[list[str] | None] = []
        self.min_width = min_width

    def add_row(self, row: Sequence) -> "Table":
        self.rows.append([str(v) for v in row])
        return self

    def add_separator(self) -> "Table":
        self.rows.append(None)
        return self

    def render(self) -> str:
        ncol = len(self.headers)
        widths = [visible_len(h) for h in self.headers]
        for r in self.rows:
            if r is None:
                continue
            for i in range(ncol):
                cell = r[i] if i < len(r) else ""
                widths[i] = max(widths[i], visible_len(cell))

        def line(cells: Sequence[str], header: bool = False) -> str:
            parts = []
            for i in range(ncol):
                cell = cells[i] if i < len(cells) else ""
                al = "l" if header and self.aligns[i] != "r" else self.aligns[i]
                parts.append(_pad(cell, widths[i], "r" if header and self.aligns[i] == "r" else al))
            return " " + " | ".join(parts)

        body_w = sum(widths) + 3 * (ncol - 1) + 2
        if self.title:
            body_w = max(body_w, visible_len(self.title) + 2)
        total_w = max(body_w, self.min_width)

        out = []
        if self.title:
            out.append("=" * total_w)
            out.append(" " + c(self.title, "bold"))
        out.append("=" * total_w)
        out.append(c(line(self.headers, header=True), "cyan"))
        out.append("-" * total_w)
        for r in self.rows:
            out.append("-" * total_w if r is None else line(r))
        out.append("=" * total_w)
        for f in self.footer:
            out.append(" " + f)
        return "\n".join(out)

    def __str__(self) -> str:
        return self.render()


def banner(title: str, subtitle: str | None = None, width: int = 110, char: str = "=") -> str:
    lines = [char * width, " " + c(title, "bold")]
    if subtitle:
        lines.append(" " + c(subtitle, "dim"))
    lines.append(char * width)
    return "\n".join(lines)


def kv_block(pairs: Sequence[tuple[str, str]], key_width: int | None = None, indent: int = 1) -> str:
    """Bloque clave : valor alineado."""
    kw = key_width or max((visible_len(k) for k, _ in pairs), default=0)
    pad = " " * indent
    return "\n".join(f"{pad}{_pad(k, kw, 'l')} : {v}" for k, v in pairs)


def section(title: str, width: int = 110) -> str:
    t = f" {title} "
    side = max((width - visible_len(t)) // 2, 2)
    return c("-" * side + t + "-" * max(width - side - visible_len(t), 2), "yellow")
