"""Puente de importación limpia para `Data/2_modelo_ml_nasdaq.py` (cuyo nombre inicia con dígito)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parent / "2_modelo_ml_nasdaq.py"
_spec = importlib.util.spec_from_file_location("modelo_ml_nasdaq", _path)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)

estimar_probabilidad_regimen_nq = _mod.estimar_probabilidad_regimen_nq
ejecutar_suite_robustez = _mod.ejecutar_suite_robustez
