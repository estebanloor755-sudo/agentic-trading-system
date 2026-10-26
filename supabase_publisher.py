"""
==================================================================================
MÓDULO PUBLICADOR SUPABASE EN TIEMPO REAL (NQ / MNQ — MT5 US100-DEC26)
==================================================================================
Toma el estado cuantitativo unificado de `main_dashboard_nq.py` y lo publica vía
HTTP REST / PostgREST a la tabla `public.nq_snapshots` de Supabase.
Supabase automáticamente retransmite los cambios vía WebSockets (Realtime) a Vercel.
==================================================================================
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
import requests
from requests.adapters import HTTPAdapter

_HTTP_SESSION: requests.Session | None = None


def get_http_session() -> requests.Session:
    """Mantiene un pool persistente de conexiones HTTP/HTTPS Keep-Alive para latencia mínima."""
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
        _HTTP_SESSION.mount("https://", adapter)
        _HTTP_SESSION.mount("http://", adapter)
    return _HTTP_SESSION

CONFIG_FILE = Path(__file__).resolve().parent / "supabase_config.json"
ENV_FILE = Path(__file__).resolve().parent / ".env"


def _read_env_file() -> dict[str, str]:
    """Lee el archivo .env si existe y devuelve un diccionario de variables."""
    vars_dict: dict[str, str] = {}
    if ENV_FILE.exists():
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vars_dict[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    return vars_dict


def load_supabase_credentials() -> tuple[str, str]:
    """
    Carga SUPABASE_URL y SUPABASE_KEY desde:
      1. Variables de entorno del sistema (`os.environ`)
      2. Archivo `.env` en la raíz del proyecto
      3. Archivo `supabase_config.json`
    """
    env_vars = _read_env_file()
    url = os.environ.get("SUPABASE_URL", env_vars.get("SUPABASE_URL", "")).strip()
    key = os.environ.get(
        "SUPABASE_KEY",
        os.environ.get("SUPABASE_ANON_KEY", env_vars.get("SUPABASE_KEY", env_vars.get("SUPABASE_ANON_KEY", ""))),
    ).strip()

    if (not url or not key) and CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            url = url or cfg.get("supabase_url", "").strip()
            key = key or cfg.get("supabase_key", cfg.get("supabase_anon_key", "")).strip()
        except Exception:
            pass

    return url.rstrip("/"), key


def save_supabase_credentials(url: str, key: str) -> None:
    """Guarda las credenciales en `supabase_config.json` para persistencia local."""
    data = {"supabase_url": url.strip().rstrip("/"), "supabase_key": key.strip()}
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def serialize_state_for_supabase(state: Any) -> dict[str, Any]:
    """
    Serializa el estado del orquestador cuantitativo (`QuantSharedState`)
    en un payload limpio compatible con el esquema de Supabase.
    """
    start_ts_str = state.bars_15m.index[0].strftime("%Y-%m-%d %H:%M NY")
    end_ts_str = state.bars_15m.index[-1].strftime("%Y-%m-%d %H:%M NY")
    data_range_str = f"{state.bars_15m.index[0].strftime('%Y-%m-%d %H:%M')} → {state.bars_15m.index[-1].strftime('%Y-%m-%d %H:%M NY')}"

    # Extracción segura de telemetría GARCH y métricas de riesgo para el acordeón UI
    import math
    fit15 = getattr(state, "fit15", None)
    tail_dist = getattr(state, "tail_dist", None)
    horizons = tail_dist.get("horizons", {}) if isinstance(tail_dist, dict) else {}
    h1_tail = (
        horizons.get("1h (B#04 - 4 Barras)")
        or horizons.get("1h (B#04 - Disparo)")
        or next((v for k, v in horizons.items() if "1h" in k), {})
    )

    garch_params_str = ""
    if fit15 is not None:
        try:
            pers = float(getattr(fit15, "persistence", 0.0))
            denom = math.log(max(min(pers, 0.9999), 0.01))
            hl_15 = float(math.log(0.5) / denom) if denom != 0 else 0.0
            omega = float(getattr(fit15, "omega", 0.0))
            alpha = float(getattr(fit15, "alpha", 0.0))
            gamma = float(getattr(fit15, "gamma", 0.0))
            beta = float(getattr(fit15, "beta", 0.0))
            nu = float(getattr(fit15, "nu", 0.0))
            garch_params_str = (
                f"Persistencia={pers*100:.1f}% (HL={hl_15:.1f}b) | "
                f"ω={omega:.6f} | α={alpha:.4f} | γ={gamma:.4f} | β={beta:.4f} | ν={nu:.2f}"
            )
        except Exception:
            pass

    var99_1h_pts = float(h1_tail.get("var99_pts", 0.0))
    cvar99_1h_pts = float(h1_tail.get("cvar99_pts", 0.0))

    kpis = {
        "spot": float(state.spot),
        "symbol": "US100-DEC26",
        "vwap_5m": float(state.vwap_now),
        "z_vwap_5": float(state.z_vwap_5),
        "vwap_globex": float(getattr(state, "vwap_globex", state.vwap_now)),
        "z_vwap_globex": float(getattr(state, "z_vwap_globex", state.z_vwap_5)),
        "vwap_rth": float(getattr(state, "vwap_rth", state.vwap_now)),
        "z_vwap_rth": float(getattr(state, "z_vwap_rth", state.z_vwap_5)),
        "poc": float(getattr(state, "poc_price", 0.0)),
        "vah": float(getattr(state, "vah_price", 0.0)),
        "val": float(getattr(state, "val_price", 0.0)),
        "rvol_20d": float(getattr(state, "rvol_20d", 1.0)),
        "cvd_z": float(getattr(state, "cvd_z", 0.0)),
        "dist_call": round(float(state.call_wall - state.spot), 1),
        "dist_put": round(float(state.spot - state.put_wall), 1),
        "dist_zg": round(float(state.spot - state.zero_gamma), 1),
        "zero_gamma": float(state.zero_gamma),
        "call_wall": float(state.call_wall),
        "put_wall": float(state.put_wall),
        "p05_1h": float(state.q_mat[1, 3]),
        "p95_1h": float(state.q_mat[9, 3]),
        "log_ret_5m": float(state.df_log_anom["log_ret"].iloc[-1]),
        "risk_reversal_25d": round(float(getattr(state, "risk_reversal_25d", 3.20)), 2),
        "iv_25p": round(float(getattr(state, "iv_25p", 0.22)), 4),
        "iv_25c": round(float(getattr(state, "iv_25c", 0.19)), 4),
        "or_high": round(float(state.or_high), 2) if state.or_high is not None else None,
        "or_low": round(float(state.or_low), 2) if state.or_low is not None else None,
        "ib_high": round(float(state.ib_high), 2) if state.ib_high is not None else None,
        "ib_low": round(float(state.ib_low), 2) if state.ib_low is not None else None,
        "pdc": round(float(getattr(state, "pdc", state.spot)), 2),
        "gap_pts": round(float(getattr(state, "gap_pts", 0.0)), 2),
        "gap_pct": round(float(getattr(state, "gap_pct", 0.0)), 2),
        "spread_pts": round(float(getattr(state, "spread_pts", 0.50)), 2),
        "tick_speed": round(float(getattr(state, "tick_speed", 1.0)), 1),
        "regime_arbiter": str(getattr(state, "regime_arbiter", "")),
        "regime_color": str(getattr(state, "regime_color", "#38bdf8")),
        "garch_params_str": garch_params_str,
        "adf_stat": round(float(getattr(state, "adf_stat", -20.0)), 4),
        "adf_pvalue": round(float(getattr(state, "adf_pvalue", 0.0001)), 6),
        "adf_is_stationary": bool(getattr(state, "adf_is_stationary", True)),
        "adf_status_str": str(getattr(state, "adf_status_str", "Estacionaria (p<0.05)")),
        "adf_crit_5pct": round(float(getattr(state, "adf_crit_5pct", -2.86)), 3),
        "stationary_status": "ESTACIONARIO" if getattr(state, "adf_is_stationary", True) else "NO_ESTACIONARIO",
        "var99_1h_pts": var99_1h_pts,
        "cvar99_1h_pts": cvar99_1h_pts,
        "hawkes_call_label": str(getattr(state, "hawkes_call_label", "P(Breakout) = 50.0%")),
        "hawkes_put_label": str(getattr(state, "hawkes_put_label", "P(Rebote) = 50.0%")),
        "hawkes_call_p_breakout": float(getattr(state, "hawkes_call_p_breakout", 0.50)),
        "hawkes_put_p_breakout": float(getattr(state, "hawkes_put_p_breakout", 0.50)),
        "hawkes_lambda": float(getattr(state, "hawkes_lambda", 1.0)),
        "hawkes_branching": float(getattr(state, "hawkes_branching", 0.40)),
        "hmm_regime_label": str(getattr(state, "hmm_regime_label", "")),
        "hmm_current_state": int(getattr(state, "hmm_current_state", 0)),
        "hmm_state_name": str(getattr(state, "hmm_state_name", "Rango")),
        "hmm_state_prob": float(getattr(state, "hmm_state_prob", 0.885)),
        "hmm_state_probs": getattr(state, "hmm_state_probs", []),
        "risk_audit_is_valid": bool(getattr(state, "risk_audit_is_valid", True)),
        "risk_audit_status": str(getattr(state, "risk_audit_status", "✓ VaR 99% Validado")),
        "kupiec_pvalue": float(getattr(state, "kupiec_pvalue", 0.50)),
        "christoffersen_pvalue": float(getattr(state, "christoffersen_pvalue", 0.50)),
        "kupiec_stat": float(getattr(state, "kupiec_stat", 0.0)),
        "christoffersen_stat": float(getattr(state, "christoffersen_stat", 0.0)),
        "risk_audit_failures": int(getattr(state, "risk_audit_failures", 0)),
        "risk_audit_expected": float(getattr(state, "risk_audit_expected", 2.5)),
        "fred_rate_3m": float(getattr(state, "fred_rate_3m", 0.0406)),
        "fred_source": str(getattr(state, "fred_source", "FRED API: DTB3")),
        "cost_of_carry_pts": float(getattr(state, "cost_of_carry_pts", 0.0)),
        "fair_value_nq": float(getattr(state, "fair_value_nq", 0.0)),
        "strategies_table": getattr(state, "strategies_table_rows", []),
        "data_start": start_ts_str,
        "data_end": end_ts_str,
        "data_range": data_range_str,
        "bars_15m_count": len(state.bars_15m),
        "bars_5m_count": len(state.bars_5m),
    }



    decisions = {
        "page1": {
            "module": state.decision_page1.module_name,
            "signal": state.decision_page1.signal,
            "sub_label": state.decision_page1.sub_label,
            "color_hex": state.decision_page1.color_hex,
            "bg_hex": state.decision_page1.bg_hex,
            "confluence_pct": float(state.decision_page1.confluence_pct),
            "rr_ratio": float(state.decision_page1.rr_ratio),
            "action": state.decision_page1.action_text,
            "metrics": state.decision_page1.metrics_highlight,
            "trigger_card": getattr(state.decision_page1, "trigger_card", ""),
            "stop_card": getattr(state.decision_page1, "stop_card", ""),
            "target_card": getattr(state.decision_page1, "target_card", ""),
        },
        "page2": {
            "module": state.decision_page2.module_name,
            "signal": state.decision_page2.signal,
            "sub_label": state.decision_page2.sub_label,
            "color_hex": state.decision_page2.color_hex,
            "bg_hex": state.decision_page2.bg_hex,
            "confluence_pct": float(state.decision_page2.confluence_pct),
            "rr_ratio": float(state.decision_page2.rr_ratio),
            "action": state.decision_page2.action_text,
            "metrics": state.decision_page2.metrics_highlight,
            "trigger_card": getattr(state.decision_page2, "trigger_card", ""),
            "stop_card": getattr(state.decision_page2, "stop_card", ""),
            "target_card": getattr(state.decision_page2, "target_card", ""),
        },
        "page3": {
            "module": state.decision_page4_yield.module_name,
            "signal": state.decision_page4_yield.signal,
            "sub_label": state.decision_page4_yield.sub_label,
            "color_hex": state.decision_page4_yield.color_hex,
            "bg_hex": state.decision_page4_yield.bg_hex,
            "confluence_pct": float(state.decision_page4_yield.confluence_pct),
            "rr_ratio": float(state.decision_page4_yield.rr_ratio),
            "action": state.decision_page4_yield.action_text,
            "metrics": state.decision_page4_yield.metrics_highlight,
            "trigger_card": getattr(state.decision_page4_yield, "trigger_card", ""),
            "stop_card": getattr(state.decision_page4_yield, "stop_card", ""),
            "target_card": getattr(state.decision_page4_yield, "target_card", ""),
        },
        "master": {
            "module": state.decision_master.module_name,
            "signal": state.decision_master.signal,
            "sub_label": state.decision_master.sub_label,
            "color_hex": state.decision_master.color_hex,
            "bg_hex": state.decision_master.bg_hex,
            "confluence_pct": float(state.decision_master.confluence_pct),
            "rr_ratio": float(state.decision_master.rr_ratio),
            "action": state.decision_master.action_text,
            "metrics": state.decision_master.metrics_highlight,
            "trigger_card": getattr(state.decision_master, "trigger_card", ""),
            "stop_card": getattr(state.decision_master, "stop_card", ""),
            "target_card": getattr(state.decision_master, "target_card", ""),
        },
        "strategies_table": getattr(state, "strategies_table_rows", []),
    }


    # Series e imágenes para renderizado completo en Vercel
    import base64
    b64_1 = getattr(state, "b64_page1", "")
    b64_2 = getattr(state, "b64_page2", "")
    b64_3 = getattr(state, "b64_page3", "")
    chart_dir = Path(__file__).resolve().parent / "outputs" / "charts"
    if not b64_1:
        f1 = chart_dir / "dashboard_page1_macro_garch_mc.png"
        if f1.exists():
            try:
                b64_1 = base64.b64encode(f1.read_bytes()).decode("ascii")
            except Exception:
                pass
    if not b64_2:
        f2 = chart_dir / "dashboard_page2_liquidez_gex_crr.png"
        if f2.exists():
            try:
                b64_2 = base64.b64encode(f2.read_bytes()).decode("ascii")
            except Exception:
                pass
    if not b64_3:
        f3 = chart_dir / "dashboard_page3_microestructura_5m.png"
        if f3.exists():
            try:
                b64_3 = base64.b64encode(f3.read_bytes()).decode("ascii")
            except Exception:
                pass

    log_anom_tail = state.df_log_anom.tail(100).copy()
    chart_series = {
        "page1_b64": b64_1,
        "page2_b64": b64_2,
        "page3_b64": b64_3,
        "image_garch": b64_1,
        "image_gex": b64_2,
        "image_micro": b64_3,
        "log_ret_timestamps": [t.strftime("%H:%M") for t in log_anom_tail.index],
        "log_ret": [round(float(v), 5) for v in log_anom_tail["log_ret"]],
        "upper_threshold": [round(float(v), 5) for v in log_anom_tail["upper_threshold"]],
        "lower_threshold": [round(float(v), 5) for v in log_anom_tail["lower_threshold"]],
        "is_anomaly": [bool(v) for v in log_anom_tail["is_anomaly"]],
        "strategies_table": getattr(state, "strategies_table_rows", []),
    }


    payload = {
        "id": "latest",
        "spot": round(float(state.spot), 2),
        "symbol": "US100-DEC26",
        "timestamp_ny": state.timestamp_ny.strftime("%Y-%m-%d %H:%M %Z"),
        "session_status": state.session_status,
        "source_feed": state.source_15m,
        "elapsed_sec": round(float(state.elapsed_sec), 2),
        "kpis": kpis,
        "decisions": decisions,
        "cone_table": state.cone_table_rows,
        "tail_table": state.tail_table_rows,
        "gex_table": state.gex_table_rows,
        "gex_summary": state.gex_summary_rows,
        "log_anom_table": state.log_anom_rows,
        "micro_table": state.micro_table_rows,
        "exec_matrix": state.exec_levels_rows,
        "chart_series": chart_series,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    return payload


def publish_snapshot_to_supabase(
    state: Any,
    url: str | None = None,
    key: str | None = None,
    timeout: float = 15.0,
) -> tuple[bool, str]:
    """
    Publica el snapshot actual a Supabase mediante la API PostgREST usando HTTP Keep-Alive.
    Retorna (éxito: bool, mensaje: str).
    """
    sb_url, sb_key = (url, key) if (url and key) else load_supabase_credentials()
    if not sb_url or not sb_key:
        return False, "Faltan credenciales de Supabase (SUPABASE_URL o SUPABASE_KEY no configuradas)"

    endpoint = f"{sb_url}/rest/v1/nq_snapshots?on_conflict=id"
    payload = serialize_state_for_supabase(state)

    headers = {
        "Content-Type": "application/json",
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Prefer": "resolution=merge-duplicates",
    }

    try:
        session = get_http_session()
        resp = session.post(endpoint, headers=headers, json=payload, timeout=timeout)
        if resp.status_code in (200, 201, 204):
            return True, f"Snapshot publicado exitosamente a Supabase (HTTP {resp.status_code})"
        return False, f"Respuesta inesperada de Supabase: HTTP {resp.status_code} - {resp.text}"
    except Exception as exc:
        return False, f"Error conectando a Supabase: {exc}"


def publish_tick_stream_to_supabase(
    spot: float,
    timestamp_ny: str,
    kpis_update: dict,
    url: str | None = None,
    key: str | None = None,
    timeout: float = 6.0,
) -> tuple[bool, str]:
    """
    Publica un pulso ultraligero de tick en tiempo real a Supabase (Keep-Alive con latencia < 100ms).
    Permite a los clientes WebSocket actualizar el DOM instantáneamente sin recálculo pesado.
    """
    sb_url, sb_key = (url, key) if (url and key) else load_supabase_credentials()
    if not sb_url or not sb_key:
        return False, "Faltan credenciales"

    endpoint = f"{sb_url}/rest/v1/nq_snapshots?id=eq.latest"
    kpis_payload = dict(kpis_update) if kpis_update else {}
    kpis_payload["is_tick"] = True
    payload = {
        "spot": round(float(spot), 2),
        "timestamp_ny": str(timestamp_ny),
        "kpis": kpis_payload,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Prefer": "return=minimal",
    }

    try:
        session = get_http_session()
        resp = session.patch(endpoint, headers=headers, json=payload, timeout=timeout)
        if resp.status_code in (200, 204):
            return True, f"Tick publicado (HTTP {resp.status_code})"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


if __name__ == "__main__":
    url, key = load_supabase_credentials()
    print("Módulo Publicador Supabase NQ")
    print(f"URL: {url or 'No configurada'}")
    print(f"Key: {'Configurada (' + key[:8] + '...)' if key else 'No configurada'}")
    print(f"Archivo de configuración local: {CONFIG_FILE}")
