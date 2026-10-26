"""
Tema gráfico institucional oscuro (#0f172a) para matplotlib.

Compatible con:
  * ejecución directa por terminal (ventana interactiva o guardado PNG si el
    backend no es interactivo, p.ej. Agg en servidores/CI);
  * celdas `# %%` de VS Code / Jupyter (inline).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

from core.config import CHART_DIR, THEME

_NON_INTERACTIVE = {"agg", "pdf", "ps", "svg", "cairo", "template"}


def apply_dark() -> None:
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": THEME["bg"],
        "axes.facecolor": THEME["panel"],
        "savefig.facecolor": THEME["bg"],
        "axes.edgecolor": THEME["grid"],
        "axes.labelcolor": THEME["text"],
        "axes.titlecolor": THEME["text"],
        "axes.titleweight": "bold",
        "axes.titlesize": 10.5,
        "axes.grid": True,
        "grid.color": THEME["grid"],
        "grid.alpha": 0.45,
        "grid.linestyle": "-",
        "grid.linewidth": 0.6,
        "xtick.color": THEME["muted"],
        "ytick.color": THEME["muted"],
        "text.color": THEME["text"],
        "legend.facecolor": THEME["bg"],
        "legend.edgecolor": THEME["grid"],
        "legend.labelcolor": THEME["text"],
        "legend.fontsize": 8,
        "font.size": 9,
        "axes.prop_cycle": matplotlib.cycler(color=[THEME[k] for k in
                                                    ("blue", "red", "green", "amber", "violet", "pink")]),
    })


def finalize(fig, name: str, show: bool | None = None, save: bool = True) -> Path | None:
    """Guarda en outputs/charts/<name>.png y muestra si el backend es interactivo."""
    import matplotlib.pyplot as plt
    path = None
    try:
        fig.tight_layout()
    except Exception:
        pass
    if save:
        CHART_DIR.mkdir(parents=True, exist_ok=True)
        path = CHART_DIR / f"{name}.png"
        fig.savefig(path, dpi=130)
    backend = matplotlib.get_backend().lower()
    interactive = not any(b in backend for b in _NON_INTERACTIVE)
    if show is None:
        show = interactive
    if show and interactive:
        plt.show()
    else:
        plt.close(fig)
    return path


apply_dark()
