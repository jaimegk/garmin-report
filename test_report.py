#!/usr/bin/env python3
"""Comprobaciones exhaustivas de generate_report.py, render_html.py y demo_data.py.

Ejecutar: python test_report.py  (sin dependencias externas, solo asserts y stdlib)
O bien:   pytest
"""

import io
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import demo_data
import generate_report
import render_html
from generate_report import (
    SleepNight, bed_minutes, wake_minutes, sd_minutes, fmt_duration,
    fmt_trend, fmt_hms, iso_weeks_in_range, compute_flags,
    fmt_pace, fmt_zones, sync, build_report, summary_tiles, summary_rings,
    recovery_score, compute_sri, compute_social_jetlag, compute_hrv_stability,
    compute_acwr_ewma, compute_aerobic_decoupling, query_acwr,
    fmt_val, to_local, fmt_clock, sport_extras, _clock_minutes,
    last_week_range, parse_date, garmin_bin, inspect_schema,
    tz_offset_minutes, local_day, query_sleep, query_intensity,
    query_vo2max, query_race_predictions, regularity_over_period,
    query_stress, query_body_battery, query_activities, query_activity_detail,
    add_min_hr, query_laps, query_floors, query_records, query_steps,
    metric_stats, baseline_range, _sum_dur, _sum_num, _sum_steps, _sum_reg,
    _clamp100, _band, weekly_breakdown, title_range, build_summary,
    day_label, generate_md, main, NO_ACWR,
)
from render_html import (
    md_to_html, svg_sleep_timeline, svg_week_wheel, svg_line,
    svg_recovery_map, svg_battery_range, svg_spo2_resp, svg_intensity_bars,
    fitness_cards_html, build_charts, rings_html, tiles_html,
    _esc, _parse_ts, _median, _nice_bounds, _grid, _xlabels, _legend,
    _frame, _signal_class, _slug, _inline, _cell, _table,
    logo_svg, favicon_link, _navbar, render,
)


# ===========================================================================
# 1. Tests originales de generate_report.py
# ===========================================================================

def test_compute_sri():
    n1 = SleepNight("2026-06-02", "2026-06-01 23:00:00", "2026-06-02 07:00:00", 8*3600)
    n2 = SleepNight("2026-06-03", "2026-06-02 23:00:00", "2026-06-03 07:00:00", 8*3600)
    n3 = SleepNight("2026-06-04", "2026-06-03 23:00:00", "2026-06-04 07:00:00", 8*3600)
    assert compute_sri([n1, n2, n3]) == 100

    n_shifted = SleepNight("2026-06-03", "2026-06-03 01:00:00", "2026-06-03 09:00:00", 8*3600)
    sri_shifted = compute_sri([n1, n_shifted])
    assert 65 <= sri_shifted <= 88, f"SRI con desfase: {sri_shifted}"


def test_compute_social_jetlag():
    thu = SleepNight("2026-06-05", "2026-06-04 23:00:00", "2026-06-05 07:00:00", 8*3600)
    fri = SleepNight("2026-06-06", "2026-06-06 01:00:00", "2026-06-06 09:00:00", 8*3600)
    sat = SleepNight("2026-06-07", "2026-06-07 01:00:00", "2026-06-07 09:00:00", 8*3600)
    assert compute_social_jetlag([thu, fri, sat]) == 120


def test_compute_hrv_stability():
    cur = [60, 62, 59, 61, 60, 61, 60]
    base = [58, 60, 62, 59, 61] * 6
    res = compute_hrv_stability(cur, base)
    assert res["cv"] is not None and res["cv"] < 5.0
    assert res["status"] == "balanced"
    assert res["swc_low"] < 60.4 < res["swc_high"]

    cur_low = [42, 44, 43, 45, 41, 42, 43]
    res_low = compute_hrv_stability(cur_low, [60, 58, 62, 61, 59] * 5)
    assert res_low["status"] == "low"


def test_compute_acwr_ewma():
    loads = [100.0] * 28
    res = compute_acwr_ewma(loads)
    assert res["acwr"] == 1.0
    assert res["status"] == "optimal"

    spike_loads = [100.0] * 21 + [250.0] * 7
    res_spike = compute_acwr_ewma(spike_loads)
    assert res_spike["acwr"] > 1.35
    assert res_spike["status"] in ("overload", "danger")


def test_query_acwr_exige_historico_suficiente():
    # Rellenar con carga 0 los días anteriores a la primera sincronización
    # hundía la carga crónica y disparaba un falso "pico de carga agudo".
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE training_load (date TEXT, total_intensity_minutes REAL,"
                 " daily_training_load_acute REAL, daily_training_load_chronic REAL,"
                 " daily_acute_chronic_workload_ratio REAL)")
    end = date(2026, 6, 21)

    def add(days):
        conn.executemany(
            "INSERT INTO training_load (date, total_intensity_minutes) VALUES (?, ?)",
            [((end - timedelta(days=i)).isoformat(), 40.0) for i in days])

    add(range(14))                       # dos semanas: insuficiente
    assert query_acwr(conn, end)["acwr"] is None

    add(range(14, 40))                   # ya hay más de 4 semanas
    assert query_acwr(conn, end)["acwr"] == 1.0


def test_compute_aerobic_decoupling():
    laps = [
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 140.0},
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 140.0},
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 150.0},
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 150.0},
    ]
    ef, dec = compute_aerobic_decoupling(laps)
    assert ef is not None
    assert 6.0 <= dec <= 7.5


def test_bed_minutes_wraps_after_midnight():
    # 23:30 y 00:17 deben quedar contiguos (00:17 → 24h17)
    assert bed_minutes("2026-06-01 23:30:00") == 23 * 60 + 30
    assert bed_minutes("2026-06-02 00:17:00") == 24 * 60 + 17
    assert wake_minutes("2026-06-02 07:05:00") == 7 * 60 + 5
    assert bed_minutes(None) is None
    assert bed_minutes("basura") is None


def test_sd_minutes():
    assert sd_minutes([10, 20]) is None          # <3 valores
    assert sd_minutes([10, None, 20, 30]) == 10  # stdev muestral de 10,20,30
    assert sd_minutes([None, None]) is None


def test_formatters():
    assert fmt_duration(7 * 3600 + 34 * 60) == "7h34"
    assert fmt_duration(None) == "–"
    assert fmt_hms(3600 + 125) == "1:02:05"
    assert fmt_hms(125) == "2:05"
    assert fmt_trend(None, 5) == "–"
    assert fmt_trend(50, 47, " bpm") == "▲ 3 bpm"
    assert fmt_trend(47, 50, " bpm") == "▼ 3 bpm"
    assert fmt_trend(47.2, 47.0) == "■ ="
    assert fmt_trend(7 * 3600, 7.5 * 3600, as_duration=True) == "▼ 30 min"


def test_iso_weeks_in_range():
    # 2026-06-22 (lunes W26) a 2026-07-05 (domingo W27): dos semanas completas
    weeks = iso_weeks_in_range(date(2026, 6, 22), date(2026, 7, 5))
    assert [w[0] for w in weeks] == [26, 27]
    assert weeks[0][1] == date(2026, 6, 22) and weeks[0][2] == date(2026, 6, 28)
    # Rango que empieza a mitad de semana: la primera queda recortada
    weeks = iso_weeks_in_range(date(2026, 6, 25), date(2026, 6, 29))
    assert weeks[0][1] == date(2026, 6, 25) and weeks[0][2] == date(2026, 6, 28)
    assert weeks[1][1] == date(2026, 6, 29) and weeks[1][2] == date(2026, 6, 29)


def _night(rhr=48, sleep_s=8 * 3600, spo2=95):
    return SleepNight("2026-06-23", None, None, sleep_s, None, None, None, None,
                      85, 60, "BALANCED", rhr, spo2, spo2 - 3, 14)


def test_compute_flags():
    base = {"n_nights": 7, "rhr": 46, "hrv": 60, "stress": 30, "sleep_s": 8 * 3600,
            "score": 85, "steps": 9000, "spo2": 95, "intensity_week": 200,
            "bed_sd": 25, "wake_sd": 20, "vo2max": 48, "resp_avg": 13.5, "acwr": 1.0}
    cur = dict(base, sri=85, social_jetlag=15, hrv_cv=5.0, hrv_swc_low=52.0, hrv_swc_high=68.0)

    # FC reposo ≥ media+5 tres días seguidos → aviso
    rows = [_night(rhr=52)] * 3 + [_night()] * 4
    flags = compute_flags(rows, cur, base)
    assert any("FC reposo elevada 3 días" in f for f in flags), flags

    # Semana normal → sin avisos ⚠️
    flags = compute_flags([_night()] * 7, cur, base)
    assert not any(f.startswith("⚠️") for f in flags), flags

    # HRV 15% por debajo de la media → aviso
    low = dict(cur, hrv=51)
    flags = compute_flags([_night()] * 7, low, base)
    assert any("HRV nocturno" in f and f.startswith("⚠️") for f in flags), flags

    # Frecuencia respiratoria nocturna desviada ≥ +1.0 resp/min → aviso
    resp_drift = dict(cur, resp_avg=14.8)
    flags = compute_flags([_night()] * 7, resp_drift, base)
    assert any("Frecuencia respiratoria nocturna elevada" in f for f in flags), flags

    # ACWR pico agudo > 1.50 → aviso
    danger_acwr = dict(cur, acwr=1.58)
    flags = compute_flags([_night()] * 7, danger_acwr, base)
    assert any("Pico de carga agudo" in f for f in flags), flags

    # Desacoplamiento aeróbico elevado y asimetría biomecánica en sesiones
    acts = [
        {"activity_type_key": "running", "duration": 3600, "decoupling": 8.5, "day": "2026-06-20",
         "avg_ground_contact_balance": 52.0}
    ]
    flags = compute_flags([_night()] * 7, cur, base, act_detail=acts)
    assert any("Desacoplamiento aeróbico" in f for f in flags), flags
    assert any("Asimetría de apoyo" in f for f in flags), flags


def test_fmt_pace_por_deporte():
    # 3.33 m/s ≈ 5:00/km corriendo; en bici se muestra km/h; en pádel, nada
    assert fmt_pace(1000 / 300, "running") == "5:00/km"
    assert fmt_pace(1000 / 300, "indoor_cycling") == "12.0 km/h"
    assert fmt_pace(100 / 130, "lap_swimming") == "2:10/100m"
    # Variantes que Garmin inventa: no pueden caerse a '–' por no estar en una lista
    assert fmt_pace(1000 / 300, "road_biking") == "12.0 km/h"
    assert fmt_pace(1000 / 300, "trail_running") == "5:00/km"
    assert fmt_pace(1000 / 300, "paddelball") == "–"
    assert fmt_pace(None, "running") == "–"


def test_fmt_zones():
    assert fmt_zones([0, 300, 600, 100, 0]) == "0/30/60/10/0"
    assert fmt_zones([None] * 5) == "–"


def test_md_to_html():
    md = (
        "## Sueño\n\n"
        "| Día | Horas | Zonas 1-5 |\n"
        "|-----|------:|:---------:|\n"
        "| Lun | 7h30 | 10/20/30/40/0 |\n\n"
        "**Media:** 7h30\n\n"
        "- ⚠️ Una señal\n"
        "- ✅ Otra señal\n"
    )
    out = md_to_html(md, {"Sueño": "<svg id='grafica'></svg>"})

    assert '<section class="sec" id="sueno">' in out and "<h2>Sueño</h2>" in out
    # La gráfica se inyecta al abrir la sección, antes que su contenido
    assert out.index("<svg id='grafica'>") < out.index("<div class='tw'>")
    # La fila separadora no se convierte en datos y la alineación se traslada
    assert out.count("<tr>") == 2 and "<th>Día</th>" in out
    assert '<td style="text-align:right">7h30</td>' in out
    assert "<strong>Media:</strong>" in out
    # El reparto por zonas se dibuja: cinco porcentajes → cuatro segmentos de color
    assert '<i class="z4" style="width:40.0%"></i>' in out and '"z5"' not in out
    # Las viñetas consecutivas forman una sola lista, con su estado por señal.
    assert ('<ul class="signals"><li class="warn">⚠️ Una señal</li>'
            '<li class="good">✅ Otra señal</li></ul>') in out


def test_sleep_timeline_coloca_la_noche_en_su_hora():
    def noche(start_ts, end_ts):
        return SleepNight("2026-06-16", start_ts, end_ts, 7 * 3600, 3600, 4 * 3600,
                          2 * 3600, 0, 70, 60, "ok", 48, 95, 92, 14)

    # Acostarse a las 18:00 es el extremo izquierdo del eje; a las 00:00, un
    # tercio (6 h de las 18 que dura la ventana).
    svg = svg_sleep_timeline("t", ["a", "b"], [
        noche("2026-06-15 18:00:00", "2026-06-16 02:00:00"),
        noche("2026-06-16 00:00:00", "2026-06-16 07:00:00"),
    ], lambda s: "7h00")
    xs = [float(x) for x in re.findall(r'<rect x="([\d.]+)"', svg)]
    pad_l, plot_w = 52, 720 - 52 - 52
    assert min(xs) == pad_l
    assert any(abs(x - (pad_l + plot_w / 3)) < 0.5 for x in xs)
    # Una semana sin ninguna noche registrada no dibuja gráfica.
    assert svg_sleep_timeline("t", ["a"], [None], lambda s: "") == ""


def test_week_wheel_marca_el_objetivo():
    svg = svg_week_wheel("t", ["L", "M", "X"], [4000, None, 12000], goal=10000)
    # Un radio por día con dato (el None no dibuja) y solo el que supera el
    # objetivo se colorea.
    assert svg.count("<path") == 2 and svg.count('class="wedge good"') == 1
    assert svg_week_wheel("t", ["L"], [None], goal=10000) == ""


def test_sync_pasa_el_rango_a_extract():
    calls = []
    orig_run, orig_bin = generate_report.subprocess.run, generate_report.VENV_BIN
    generate_report.subprocess.run = lambda cmd, **kw: (calls.append(cmd), types.SimpleNamespace(returncode=0))[1]
    generate_report.VENV_BIN = type("P", (), {"exists": lambda self: True, "__str__": lambda self: "garmin"})()
    try:
        sync(date(2026, 4, 11), date(2026, 5, 5))
        sync(date(2026, 4, 11), date(2026, 4, 11))
        sync(date.today() - timedelta(days=1), date.today())
        sync()
    finally:
        generate_report.subprocess.run, generate_report.VENV_BIN = orig_run, orig_bin

    # --end-date es exclusivo y el sueño del 05-05 se guarda como 05-06 → +2 días
    assert calls[0][1:] == ["extract", "--start-date", "2026-04-11", "--end-date", "2026-05-07"]
    # Un solo día también necesita el día siguiente para su noche
    assert calls[1][1:] == ["extract", "--start-date", "2026-04-11", "--end-date", "2026-04-13"]
    # El futuro no tiene datos: el tope es mañana
    assert calls[2][-1] == (date.today() + timedelta(days=1)).isoformat()
    # Sin rango, sincronización incremental de siempre
    assert calls[3][1:] == ["extract"]


def test_demo_pipeline_end_to_end():
    """El pipeline entero sobre la BD de ejemplo: consultas SQL, agregados,
    señales, markdown y HTML. Es lo único que ejerce las funciones `query_*`."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.db"
        with patch("sys.stdout", new_callable=io.StringIO):
            start, end = demo_data.build(db)
            conn = sqlite3.connect(db)
            md, html = build_report(conn, start, end, demo_data.GENERATED_ON)
            conn.close()

    for section in ("## Resumen", "### Señales", "### Métricas", "## Sueño",
                    "## FC reposo + HRV nocturno", "## Respiración y SpO2 nocturnos",
                    "## Estrés y Body Battery", "## Actividad",
                    "### Detalle de sesiones", "### Vueltas", "## Forma física"):
        assert section in md, f"falta la sección {section!r}"

    # La fecha de generación es la del dataset, no la de hoy: si no, el ejemplo
    # publicado cambiaría en cada ejecución.
    assert f"_Generado el {demo_data.GENERATED_ON.isoformat()}" in md

    # Los datos de la última semana están hechos para disparar señales: si el
    # informe sale limpio, o los umbrales o el generador se han roto.
    assert md.count("⚠️") >= 3, md[:600]

    # La FC de cada vuelta tiene que ser coherente: mín ≤ media ≤ máx.
    for lo, mid, hi in re.findall(r"\| (\d+)/(\d+)/(\d+) \|", md):
        assert int(lo) <= int(mid) <= int(hi), f"FC incoherente: {lo}/{mid}/{hi}"

    # Y el HTML es autocontenido: sin recursos externos, se abre offline.
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert '<div class="tiles">' in html and "<svg" in html
    assert "http://" not in html and "https://" not in html
    # El logo va incrustado —SVG en línea, favicon en base64—, no enlazado: si
    # assets/ desaparece el informe se genera igual y nadie se entera.
    assert '<svg class="logo"' in html and 'href="data:image/png;base64,' in html


def test_title_range_no_repite_lo_que_no_cambia():
    tr = generate_report.title_range
    assert tr(date(2026, 6, 15), date(2026, 6, 21)) == "15–21 junio 2026"
    assert tr(date(2026, 5, 25), date(2026, 6, 21)) == "25 mayo – 21 junio 2026"
    assert tr(date(2025, 12, 29), date(2026, 1, 4)) == "29 diciembre 2025 – 4 enero 2026"


def test_summary_tiles_conocen_la_direccion_buena():
    # Subir es malo en FC en reposo y bueno en VO2máx: el color no puede salir
    # del signo de la tendencia.
    cur = {"rhr": 52, "vo2max": 49, "sleep_s": 7 * 3600, "score": 80,
           "hrv": 60, "stress": 30, "steps": 9000, "intensity_week": 200, "n_nights": 7,
           "acwr": 1.15, "sri": 85, "hrv_cv": 4.5}
    base = dict(cur, rhr=46, vo2max=47, n_nights=7)
    state = {label: st for label, _v, _t, st in summary_tiles(cur, base)}
    assert state["FC reposo"] == "bad"
    assert state["VO2máx"] == "good"
    assert state["Carga (ACWR)"] == "good"
    assert state["Regularidad (SRI)"] == "good"
    assert state["Estabilidad HRV"] == "good"
    assert state["Estrés medio"] == ""             # sin cambio, no se moja
    # Sueño y minutos de intensidad son el valor de un anillo: no se repiten
    # como tarjeta.
    assert "Sueño" not in state and "Min. intensidad/sem" not in state
    assert "Score sueño" in state

    # Sin histórico con el que comparar, las de comparación directa no se mojan
    sin_base = dict(base, n_nights=0)
    assert all(st == "" or label in ("Carga (ACWR)", "Regularidad (SRI)", "Estabilidad HRV")
               for label, _v, tr, st in summary_tiles(cur, sin_base))


def test_recovery_score_pondera_hrv_y_fc():
    base = {"hrv": 60, "rhr": 48, "n_nights": 7}
    # Semana idéntica a tu media: la nota es el centro de calibración.
    assert round(recovery_score(dict(base), base)) == generate_report.RECOVERY_CENTER
    # HRV abajo y FC arriba solo pueden bajarla; al revés, subirla.
    peor = recovery_score({"hrv": 48, "rhr": 55, "n_nights": 7}, base)
    mejor = recovery_score({"hrv": 70, "rhr": 44, "n_nights": 7}, base)
    assert 0 <= peor < generate_report.RECOVERY_CENTER < mejor <= 100
    # Sin histórico no se inventa una nota, y el anillo se queda sin estado.
    sin_base = dict(base, n_nights=0)
    assert recovery_score(dict(base), sin_base) is None
    label, frac, value, _detail, state = summary_rings(
        {"hrv": 60, "rhr": 48, "sleep_s": 7 * 3600, "score": 80, "steps": 9000,
         "intensity_week": 200, "n_nights": 7}, sin_base)[2]
    assert (label, frac, value, state) == ("Recuperación", None, "–", "")


def test_summary_rings_mide_contra_su_objetivo():
    cur = {"hrv": 60, "rhr": 48, "sleep_s": 5 * 3600, "score": 80, "steps": 9000,
            "intensity_week": 300, "n_nights": 7}
    base = dict(cur, n_nights=7)
    rings = {r[0]: r for r in summary_rings(cur, base)}
    # 300 min de intensidad = objetivo OMS cumplido: anillo lleno y en verde.
    assert rings["Actividad"][1] == 1.0 and rings["Actividad"][4] == "good"
    # 5 h de sueño: cinco octavos de anillo y en rojo.
    assert rings["Sueño"][1] == 0.625 and rings["Sueño"][4] == "bad"


# ===========================================================================
# 2. Nuevos tests de formato y utilidades en generate_report.py
# ===========================================================================

def test_fmt_val_cases():
    assert fmt_val(None) == "–"
    assert fmt_val(None, fallback="N/A") == "N/A"
    assert fmt_val(42.6, unit=" bpm") == "43 bpm"
    assert fmt_val(42.0, unit=" bpm") == "42 bpm"
    assert fmt_val(50) == "50"
    assert fmt_val("OK") == "OK"


def test_to_local_cases():
    assert to_local(None, 2) is None
    assert to_local("2026-06-01 22:00:00", None) == "2026-06-01 22:00:00"
    # Formato inválido retorna el timestamp crudo
    assert to_local("fecha-invalida", 2) == "fecha-invalida"
    # Conversión correcta con offset positivo
    assert to_local("2026-06-01 22:00:00", 2) == "2026-06-02 00:00:00"
    # Conversión con offset negativo
    assert to_local("2026-06-01 02:00:00", -4) == "2026-05-31 22:00:00"


def test_fmt_clock_cases():
    assert fmt_clock(None) == "–"
    assert fmt_clock("") == "–"
    assert fmt_clock("2026-06-01") == "–"  # < 16 caracteres
    assert fmt_clock("2026-06-15 23:12:00") == "23:12"


def test_fmt_hms_cases():
    assert fmt_hms(None) == "–"
    assert fmt_hms(0) == "0:00"
    assert fmt_hms(45) == "0:45"
    assert fmt_hms(125.4) == "2:05"
    assert fmt_hms(3665) == "1:01:05"


def test_sport_extras_all_cases():
    # Vacío devuelve "–"
    assert sport_extras({}) == "–"

    # Running con todas las métricas dinámicas
    run_act = {
        "avg_running_cadence": 172.4,
        "avg_stride_length": 115,  # 1.15m
        "avg_ground_contact_time": 240.2,
        "avg_vertical_ratio": 7.5,
        "avg_ground_contact_balance": 50.8,
        "decoupling": 4.2,
        "hrr_60": 35.0,
        "avg_power": 280.0,
        "elevation_gain": 120.0,
    }
    run_str = sport_extras(run_act)
    assert "cad 172 ppm" in run_str
    assert "zancada 1.15 m" in run_str
    assert "GCT 240 ms" in run_str
    assert "ratio vert. 7.5%" in run_str
    assert "apoyo 50.8% I" in run_str
    assert "deriva +4.2%" in run_str
    assert "HRR60 35 bpm" in run_str
    assert "pot. 280 W" in run_str
    assert "D+ 120 m" in run_str

    # Fallback de oscilación vertical cuando no hay vertical_ratio
    run_osc = {"avg_vertical_oscillation": 8.4}
    assert sport_extras(run_osc) == "osc. vert. 8.4 cm"

    # Métricas de natación
    swim_act = {
        "avg_swolf": 38.2,
        "active_lengths": 40,
        "pool_length": 2500,  # 25m
        "strokes": 600,
    }
    swim_str = sport_extras(swim_act)
    assert "SWOLF 38" in swim_str
    assert "40 largos de 25 m" in swim_str
    assert "600 brazadas" in swim_str

    # Ciclismo
    bike_act = {
        "avg_biking_cadence": 85.1,
        "cycling_power": 210,
    }
    bike_str = sport_extras(bike_act)
    assert "cad 85 rpm" in bike_str
    assert "pot. 210 W" in bike_str


def test_clock_minutes_cases():
    assert _clock_minutes(None, wrap_after_midnight=True) is None
    assert _clock_minutes("2026-06-01", wrap_after_midnight=True) is None
    assert _clock_minutes("2026-06-01 XX:YY:00", wrap_after_midnight=True) is None
    assert _clock_minutes("2026-06-01 02:15:00", wrap_after_midnight=True) == 26 * 60 + 15
    assert _clock_minutes("2026-06-01 02:15:00", wrap_after_midnight=False) == 2 * 60 + 15
    assert _clock_minutes("2026-06-01 14:00:00", wrap_after_midnight=True) == 14 * 60


def test_compute_sri_edge_cases():
    assert compute_sri([]) is None
    assert compute_sri([SleepNight("2026-06-02", None, None)]) is None

    # Noches con formato de fecha inválido o start >= end
    bad_n1 = SleepNight("2026-06-02", "invalido", "2026-06-02 07:00:00")
    bad_n2 = SleepNight("2026-06-03", "2026-06-03 08:00:00", "2026-06-03 07:00:00")
    assert compute_sri([bad_n1, bad_n2]) is None

    # Menos de 2 días de intervalo
    short1 = SleepNight("2026-06-02", "2026-06-02 01:00:00", "2026-06-02 07:00:00")
    short2 = SleepNight("2026-06-02", "2026-06-02 13:00:00", "2026-06-02 15:00:00")
    assert compute_sri([short1, short2]) is None

    # Noche que empieza antes de las 18:00 (primera_dt se ajusta hacia atrás)
    early_n1 = SleepNight("2026-06-01", "2026-06-01 16:00:00", "2026-06-02 00:00:00")
    early_n2 = SleepNight("2026-06-03", "2026-06-03 23:00:00", "2026-06-04 07:00:00")
    assert compute_sri([early_n1, early_n2]) is not None


def test_compute_social_jetlag_edge_cases():
    assert compute_social_jetlag([]) is None
    assert compute_social_jetlag([SleepNight("2026-06-02", None, None)] * 3) is None

    # Solo días laborables (domingo a jueves noche), sin noches de viernes o sábado
    work1 = SleepNight("2026-06-02", "2026-06-01 23:00:00", "2026-06-02 07:00:00")
    work2 = SleepNight("2026-06-03", "2026-06-02 23:00:00", "2026-06-03 07:00:00")
    work3 = SleepNight("2026-06-04", "2026-06-03 23:00:00", "2026-06-04 07:00:00")
    assert compute_social_jetlag([work1, work2, work3]) is None

    # Solo fines de semana
    fri = SleepNight("2026-06-06", "2026-06-06 01:00:00", "2026-06-06 09:00:00")
    sat = SleepNight("2026-06-07", "2026-06-07 01:00:00", "2026-06-07 09:00:00")
    assert compute_social_jetlag([fri, sat, fri]) is None


def test_compute_hrv_stability_branches():
    # Menos de 3 lecturas actuales -> CV es None
    res_few_cur = compute_hrv_stability([60, 62], [60] * 10)
    assert res_few_cur["cv"] is None

    # Menos de 5 lecturas de base -> swc es None, status 'unknown'
    res_few_base = compute_hrv_stability([60, 61, 62, 60], [60, 62])
    assert res_few_base["swc_low"] is None
    assert res_few_base["status"] == "unknown"

    # Media actual por encima de la banda SWC -> status 'high'
    cur_high = [85, 88, 86, 87, 85]
    res_high = compute_hrv_stability(cur_high, [60, 62, 59, 61, 60] * 5)
    assert res_high["status"] == "high"


def test_compute_acwr_ewma_branches():
    # Menos de 7 cargas -> dict(NO_ACWR)
    assert compute_acwr_ewma([]) == NO_ACWR
    assert compute_acwr_ewma([100.0] * 6) == NO_ACWR

    # Carga crónica cero / negativa
    assert compute_acwr_ewma([0.0] * 10)["acwr"] is None

    # Estado 'danger' (> 1.50)
    res_danger = compute_acwr_ewma([50.0] * 21 + [300.0] * 7)
    assert res_danger["status"] == "danger"

    # Estado 'undertraining' (< 0.80)
    res_under = compute_acwr_ewma([200.0] * 21 + [20.0] * 7)
    assert res_under["status"] == "undertraining"


def test_compute_aerobic_decoupling_branches():
    assert compute_aerobic_decoupling([]) == (None, None)
    assert compute_aerobic_decoupling([{"enhanced_avg_speed": 3.0}]) == (None, None)

    # Vueltas sin FC válida (<= 40)
    bad_hr_laps = [
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 30.0},
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 35.0},
    ]
    assert compute_aerobic_decoupling(bad_hr_laps) == (None, None)

    # Vueltas usando distancia y tiempo para calcular velocidad
    dist_laps = [
        {"total_distance": 1000.0, "total_timer_time": 300.0, "avg_heart_rate": 140.0},
        {"total_distance": 1000.0, "total_timer_time": 300.0, "avg_heart_rate": 140.0},
        {"total_distance": 1000.0, "total_timer_time": 300.0, "avg_heart_rate": 145.0},
        {"total_distance": 1000.0, "total_timer_time": 300.0, "avg_heart_rate": 145.0},
    ]
    ef, dec = compute_aerobic_decoupling(dist_laps)
    assert ef is not None and dec is not None

    # Vueltas usando potencia
    pwr_laps = [
        {"avg_power": 250.0, "total_timer_time": 300.0, "avg_heart_rate": 150.0},
        {"avg_power": 250.0, "total_timer_time": 300.0, "avg_heart_rate": 150.0},
        {"avg_power": 250.0, "total_timer_time": 300.0, "avg_heart_rate": 155.0},
        {"avg_power": 250.0, "total_timer_time": 300.0, "avg_heart_rate": 155.0},
    ]
    ef_pwr, dec_pwr = compute_aerobic_decoupling(pwr_laps)
    assert ef_pwr is not None and dec_pwr is not None


def test_last_week_range():
    start, end = last_week_range()
    assert start.weekday() == 0  # Lunes
    assert end.weekday() == 6    # Domingo
    assert (end - start).days == 6


def test_parse_date():
    assert parse_date("2026-06-15") == date(2026, 6, 15)
    with patch("sys.exit") as mock_exit, patch("sys.stderr", new_callable=io.StringIO):
        parse_date("invalida")
        mock_exit.assert_called_with(1)


def test_garmin_bin_and_sync_errors():
    with patch("generate_report.VENV_BIN", Path("/no/existe/garmin")), \
         patch("shutil.which", return_value=None), \
         patch("sys.stderr", new_callable=io.StringIO):
        assert garmin_bin() is None
        try:
            sync()
            assert False, "Debe lanzar SystemExit"
        except SystemExit as e:
            assert e.code == 1

    # Subprocess falla con código de error
    with patch("generate_report.garmin_bin", return_value="/bin/garmin"), \
         patch("subprocess.run", return_value=types.SimpleNamespace(returncode=2)), \
         patch("sys.stderr", new_callable=io.StringIO):
        try:
            sync(date(2026, 1, 1), date(2026, 1, 7))
            assert False, "Debe lanzar SystemExit"
        except SystemExit as e:
            assert e.code == 1

    # Sincronización con start date solamente
    calls = []
    with patch("generate_report.garmin_bin", return_value="/bin/garmin"), \
         patch("subprocess.run", side_effect=lambda cmd, **kw: (calls.append(cmd), types.SimpleNamespace(returncode=0))[1]):
        sync(date(2026, 5, 1))
        assert calls[0] == ["/bin/garmin", "extract", "--start-date", "2026-05-01"]


# ===========================================================================
# 3. Tests de consultas SQLite y esquemas en generate_report.py
# ===========================================================================

def _create_sample_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE sleep (
            calendar_date TEXT PRIMARY KEY,
            start_ts TEXT,
            end_ts TEXT,
            sleep_time_seconds REAL,
            deep_sleep_seconds REAL,
            light_sleep_seconds REAL,
            rem_sleep_seconds REAL,
            awake_sleep_seconds REAL,
            score_overall_value REAL,
            avg_overnight_hrv REAL,
            hrv_status TEXT,
            resting_heart_rate REAL,
            average_spo2 REAL,
            lowest_spo2 REAL,
            average_respiration REAL,
            timezone_offset_hours REAL,
            nap_time_seconds REAL,
            awake_count INTEGER,
            restless_moments_count INTEGER,
            avg_sleep_stress REAL,
            body_battery_change REAL,
            sleep_need_actual REAL,
            sleep_need_baseline REAL,
            breathing_disruption_severity TEXT
        );
        CREATE TABLE training_load (
            date TEXT PRIMARY KEY,
            total_intensity_minutes REAL,
            moderate_minutes REAL,
            vigorous_minutes REAL,
            daily_training_load_acute REAL,
            daily_training_load_chronic REAL,
            daily_acute_chronic_workload_ratio REAL
        );
        CREATE TABLE vo2_max (
            date TEXT,
            vo2_max_generic REAL,
            vo2_max_cycling REAL
        );
        CREATE TABLE user_profile (
            user_profile_id INTEGER PRIMARY KEY,
            latest INTEGER,
            vo2_max_running REAL,
            vo2_max_cycling REAL
        );
        CREATE TABLE race_predictions (
            date TEXT,
            latest INTEGER,
            time_5k REAL,
            time_10k REAL,
            time_half_marathon REAL,
            time_marathon REAL
        );
        CREATE TABLE stress (
            timestamp TEXT,
            value REAL
        );
        CREATE TABLE body_battery (
            timestamp TEXT,
            value REAL
        );
        CREATE TABLE steps (
            timestamp TEXT,
            value REAL
        );
        CREATE TABLE floors (
            timestamp TEXT,
            ascended REAL
        );
        CREATE TABLE personal_record (
            timestamp TEXT,
            label TEXT,
            value REAL
        );
        CREATE TABLE activity (
            activity_id INTEGER PRIMARY KEY,
            start_ts TEXT,
            activity_type_key TEXT,
            duration REAL,
            distance REAL,
            average_hr REAL,
            max_hr REAL,
            calories REAL,
            aerobic_training_effect REAL,
            anaerobic_training_effect REAL,
            training_effect_label TEXT,
            hr_time_in_zone_1 REAL,
            hr_time_in_zone_2 REAL,
            hr_time_in_zone_3 REAL,
            hr_time_in_zone_4 REAL,
            hr_time_in_zone_5 REAL,
            average_speed REAL,
            max_speed REAL,
            difference_body_battery REAL,
            lap_count INTEGER,
            parent INTEGER DEFAULT 0,
            timezone_offset_hours REAL
        );
        CREATE TABLE running_agg_metrics (
            activity_id INTEGER PRIMARY KEY,
            avg_running_cadence REAL,
            avg_stride_length REAL,
            avg_ground_contact_time REAL,
            avg_vertical_oscillation REAL,
            avg_vertical_ratio REAL,
            avg_ground_contact_balance REAL,
            avg_power REAL,
            elevation_gain REAL,
            vo2_max_value REAL
        );
        CREATE TABLE swimming_agg_metrics (
            activity_id INTEGER PRIMARY KEY,
            avg_swolf REAL,
            strokes REAL,
            active_lengths INTEGER,
            pool_length REAL
        );
        CREATE TABLE cycling_agg_metrics (
            activity_id INTEGER PRIMARY KEY,
            avg_biking_cadence REAL,
            avg_power REAL
        );
        CREATE TABLE activity_lap_metric (
            activity_id INTEGER,
            lap_idx INTEGER,
            name TEXT,
            value REAL
        );
        CREATE TABLE activity_ts_metric (
            activity_id INTEGER,
            timestamp TEXT,
            name TEXT,
            value REAL
        );
    """)
    return conn


def test_inspect_schema():
    conn = _create_sample_db()
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        inspect_schema(conn)
        output = mock_stdout.getvalue()
        assert "sleep:" in output
        assert "activity:" in output
        assert "calendar_date" in output


def test_tz_offset_minutes_branches():
    conn = _create_sample_db()
    # Vacío -> devuelve 0
    assert tz_offset_minutes(conn) == 0

    # Desde la tabla activity
    conn.execute("INSERT INTO activity (activity_id, start_ts, timezone_offset_hours) VALUES (1, '2026-06-01 10:00:00', 2.0)")
    assert tz_offset_minutes(conn) == 120

    # Desde la tabla sleep (prioritaria)
    conn.execute("INSERT INTO sleep (calendar_date, timezone_offset_hours) VALUES ('2026-06-02', 1.0)")
    assert tz_offset_minutes(conn) == 60


def test_local_day_helper():
    assert local_day("ts", 120) == "date(ts, '+120 minutes')"
    assert local_day("ts", -60) == "date(ts, '-60 minutes')"


def test_sqlite_queries_standalone():
    conn = _create_sample_db()
    start = date(2026, 6, 1)
    end = date(2026, 6, 7)

    # Insertar sleep
    conn.execute("""
        INSERT INTO sleep (calendar_date, start_ts, end_ts, sleep_time_seconds, score_overall_value,
                           avg_overnight_hrv, resting_heart_rate, average_spo2, lowest_spo2, average_respiration,
                           timezone_offset_hours, nap_time_seconds, breathing_disruption_severity)
        VALUES ('2026-06-02', '2026-06-01 23:00:00', '2026-06-02 07:00:00', 28800, 85, 60, 48, 96, 93, 14, 2, 1800, 'LOW')
    """)
    nights = query_sleep(conn, start, end)
    assert len(nights) == 1
    assert nights[0].score == 85

    # Insertar intensity
    conn.execute("INSERT INTO training_load (date, total_intensity_minutes, moderate_minutes, vigorous_minutes) VALUES ('2026-06-02', 60, 20, 20)")
    intensity = query_intensity(conn, start, end)
    assert intensity["2026-06-02"] == (60, 20, 20)

    # VO2max: primero de user_profile, luego de vo2_max
    assert query_vo2max(conn, end) is None
    conn.execute("INSERT INTO user_profile (user_profile_id, latest, vo2_max_running, vo2_max_cycling) VALUES (1, 1, 48.0, 45.0)")
    assert query_vo2max(conn, end) == (48.0, 45.0, None)
    conn.execute("INSERT INTO vo2_max (date, vo2_max_generic, vo2_max_cycling) VALUES ('2026-06-01', 50.0, 47.0)")
    assert query_vo2max(conn, end) == (50.0, 47.0, "2026-06-01")

    # Race predictions
    conn.execute("INSERT INTO race_predictions (date, latest, time_5k, time_10k, time_half_marathon, time_marathon) VALUES ('2026-06-01', 1, 1200, 2500, 5600, 12000)")
    pred = query_race_predictions(conn)
    assert pred[1] == 1200

    # Stress y Body battery
    conn.execute("INSERT INTO stress (timestamp, value) VALUES ('2026-06-02 12:00:00', 25), ('2026-06-02 14:00:00', 35)")
    stress_map = query_stress(conn, start, end, 0)
    assert stress_map["2026-06-02"] == 30

    conn.execute("INSERT INTO body_battery (timestamp, value) VALUES ('2026-06-02 08:00:00', 95), ('2026-06-02 22:00:00', 25)")
    bb_map = query_body_battery(conn, start, end, 0)
    assert bb_map["2026-06-02"] == (95, 25)

    # Steps y Floors
    conn.execute("INSERT INTO steps (timestamp, value) VALUES ('2026-06-02 10:00:00', 5000), ('2026-06-02 18:00:00', 6000)")
    assert query_steps(conn, start, end, 0)["2026-06-02"] == 11000

    conn.execute("INSERT INTO floors (timestamp, ascended) VALUES ('2026-06-02 12:00:00', 12)")
    assert query_floors(conn, start, end, 0)["2026-06-02"] == 12

    # Personal records
    conn.execute("INSERT INTO personal_record (timestamp, label, value) VALUES ('2026-06-02 12:00:00', '5k', 1230), ('2026-06-02 12:00:00', 'Unknown metric', 99)")
    records = query_records(conn, start, end)
    assert len(records) == 1 and records[0][0] == "5k"

    # Activities & detail & laps & add_min_hr
    conn.execute("""
        INSERT INTO activity (activity_id, start_ts, activity_type_key, duration, distance,
                              average_hr, max_hr, calories, difference_body_battery, lap_count)
        VALUES (10, '2026-06-02 08:00:00', 'running', 1800, 5000, 150, 175, 400, -20, 2)
    """)
    conn.execute("INSERT INTO running_agg_metrics (activity_id, avg_running_cadence) VALUES (10, 170)")
    acts = query_activities(conn, start, end, 0)
    assert len(acts["2026-06-02"]) == 1

    detail = query_activity_detail(conn, start, end, 0)
    assert len(detail) == 1
    assert detail[0]["avg_running_cadence"] == 170

    # Laps
    conn.execute("INSERT INTO activity_lap_metric (activity_id, lap_idx, name, value) VALUES (10, 0, 'total_distance', 2500), (10, 0, 'total_elapsed_time', 900), (10, 1, 'total_distance', 2500), (10, 1, 'total_elapsed_time', 900)")
    conn.execute("INSERT INTO activity_ts_metric (activity_id, timestamp, name, value) VALUES (10, '2026-06-02 08:05:00', 'heart_rate', 142)")
    laps_map = query_laps(conn, start, end, 0)
    assert 10 in laps_map and len(laps_map[10]) == 2
    assert laps_map[10][0]["min_heart_rate"] == 142

    # Metric stats
    stats = metric_stats(conn, start, end, 0)
    assert stats["score"] == 85
    assert stats["steps"] == 11000


def test_query_acwr_with_native_column():
    conn = _create_sample_db()
    end = date(2026, 6, 21)
    # Valor nativo > 1.5 -> status danger
    conn.execute("INSERT INTO training_load (date, daily_training_load_acute, daily_training_load_chronic, daily_acute_chronic_workload_ratio) VALUES ('2026-06-20', 300, 150, 2.0)")
    res = query_acwr(conn, end)
    assert res["acwr"] == 2.0
    assert res["status"] == "danger"


# ===========================================================================
# 4. Tests de reglas de flags y resúmenes en generate_report.py
# ===========================================================================

def test_compute_flags_all_branches():
    base = {"n_nights": 7, "rhr": 46, "hrv": 60, "stress": 30, "sleep_s": 8 * 3600,
            "score": 85, "steps": 9000, "spo2": 95, "intensity_week": 200,
            "bed_sd": 25, "wake_sd": 20, "vo2max": 48, "resp_avg": 13.5, "acwr": 1.0}
    cur = dict(base, sri=85, social_jetlag=15, hrv_cv=5.0, hrv_swc_low=52.0, hrv_swc_high=68.0)

    # 1. HRV alto (> 1.10)
    high_hrv = dict(cur, hrv=70)
    f = compute_flags([_night()] * 7, high_hrv, base)
    assert any("HRV nocturno por encima de tu media" in x for x in f)

    # 2. Inestabilidad autonómica (CV > 10.5)
    high_cv = dict(cur, hrv_cv=12.0)
    f = compute_flags([_night()] * 7, high_cv, base)
    assert any("Inestabilidad autonómica" in x for x in f)

    # 3. Noches cortas (>= 2 noches < 6h)
    short_nights = [_night(sleep_s=5 * 3600), _night(sleep_s=5.5 * 3600)] + [_night()] * 5
    f = compute_flags(short_nights, cur, base)
    assert any("2 noches por debajo de 6 h" in x for x in f)

    # 4. SRI bajo (< 68) y jetlag social
    low_sri = dict(cur, sri=60, social_jetlag=90)
    f = compute_flags([_night()] * 7, low_sri, base)
    assert any("Regularidad de sueño baja" in x and "jetlag social 90 min" in x for x in f)

    # 5. SRI normal pero bed_sd > 60
    high_bed_sd = dict(cur, sri=75, bed_sd=75)
    f = compute_flags([_night()] * 7, high_bed_sd, base)
    assert any("Horario de sueño irregular" in x for x in f)

    # 6. Estrés elevado (+8)
    high_stress = dict(cur, stress=40)
    f = compute_flags([_night()] * 7, high_stress, base)
    assert any("Estrés medio elevado" in x for x in f)

    # 7. ACWR sobrecarga (1.30 < acwr <= 1.50)
    acwr_over = dict(cur, acwr=1.40)
    f = compute_flags([_night()] * 7, acwr_over, base)
    assert any("Sobrecarga progresiva alta" in x for x in f)

    # 8. Actividad por debajo de la recomendación OMS (< 150 min)
    low_im = dict(cur, intensity_week=100)
    f = compute_flags([_night()] * 7, low_im, base)
    assert any("Actividad por debajo de la recomendación" in x for x in f)

    # 9. SpO2 media < 92% en >= 3 noches
    low_spo2_nights = [_night(spo2=90)] * 3 + [_night(spo2=96)] * 4
    f = compute_flags(low_spo2_nights, cur, base)
    assert any("SpO2 nocturna media por debajo de 92%" in x for x in f)

    # 10. Asimetría de apoyo derecha (< 50%)
    act_right = [{"activity_type_key": "running", "duration": 3600, "day": "2026-06-20",
                  "avg_ground_contact_balance": 47.0}]
    f = compute_flags([_night()] * 7, cur, base, act_detail=act_right)
    assert any("pierna derecha" in x for x in f)

    # 11. Sin VO2máx
    no_vo2 = dict(cur, vo2max=None)
    f = compute_flags([_night()] * 7, no_vo2, base)
    assert any("Sin VO2máx" in x for x in f)

    # 12. Buena semana global de sueño
    good_sleep = dict(cur, sleep_s=8 * 3600, score=90)
    f = compute_flags([_night()] * 7, good_sleep, base)
    assert any("Buena semana de sueño y recuperación" in x for x in f)

    # 13. Sin señales destacables (con vo2max presente para evitar flag 12)
    f_empty = compute_flags([_night()] * 7, {"n_nights": 7, "vo2max": 50}, {"n_nights": 0})
    assert any("Sin señales destacables" in x for x in f_empty)


def test_fmt_trend_and_summary_helpers():
    assert _sum_dur(None) == "–"
    assert _sum_dur(7 * 3600) == "7h00"
    assert _sum_num(None) == "–"
    assert _sum_num(45.4, " bpm") == "45 bpm"
    assert _sum_steps(None) == "–"
    assert _sum_steps(10500) == "10.500"
    assert _sum_reg(None) == "–"
    assert _sum_reg(35.2) == "±35 min"

    assert _clamp100(-10) == 0.0
    assert _clamp100(150) == 100.0
    assert _clamp100(50.5) == 50.5

    assert _band(None, 10, 5) == ""
    assert _band(12, 10, 5) == "good"
    assert _band(7, 10, 5) == "warn"
    assert _band(2, 10, 5) == "bad"


def test_summary_tiles_all_branches():
    cur = {"acwr": 1.45, "sri": 60, "hrv_cv": 11.0, "rhr": 55, "vo2max": 45, "n_nights": 7}
    base = {"rhr": 45, "vo2max": 50, "n_nights": 7}
    tiles = summary_tiles(cur, base)
    state_map = {lbl: st for lbl, _v, _tr, st in tiles}
    assert state_map["Carga (ACWR)"] == "bad"
    assert state_map["Regularidad (SRI)"] == "bad"
    assert state_map["Estabilidad HRV"] == "bad"
    assert state_map["FC reposo"] == "bad"
    assert state_map["VO2máx"] == "bad"


def test_weekly_breakdown_and_build_summary():
    w1 = {"wk_label": "W25", "range_label": "15 jun–21 jun",
          "stats": {"sleep_s": 28800, "sri": 85, "score": 80, "rhr": 48, "hrv": 60,
                    "hrv_cv": 5.0, "acwr": 1.0, "vo2max": 48, "stress": 25,
                    "steps": 10000, "intensity_week": 200}}
    w2 = {"wk_label": "W26", "range_label": "22 jun–28 jun",
          "stats": dict(w1["stats"], rhr=52)}
    base = w1["stats"]

    table_lines = weekly_breakdown([w1, w2], base)
    assert any("W25" in l and "W26" in l for l in table_lines)

    # build_summary con multi-week
    sum_lines = build_summary(w2["stats"], base, ["⚠️ Señal"], weeks=2, multi_week=True, weekly=[w1, w2])
    assert any("W25" in l for l in sum_lines)

    # build_summary con base insuficiente (< 5 noches)
    sum_no_base = build_summary(w1["stats"], {"n_nights": 2}, ["ℹ️ Info"], weeks=0)
    assert any("Histórico insuficiente" in l for l in sum_no_base)


def test_day_label_cases():
    d = date(2026, 6, 15)  # Lunes
    assert day_label(d, multi_week=False) == "Lun"
    assert day_label(d, multi_week=True) == "15 jun Lun"


def test_generate_md_and_build_report_branches():
    # generate_md con días ausentes / sin datos
    start, end = date(2026, 6, 1), date(2026, 6, 3)
    md = generate_md(
        sleep_rows=[], stress_map={}, bb_map={}, activity_map={}, steps_map={},
        intensity_map={}, floors_map={}, act_detail=[], laps_map={}, records=[],
        vo2max=None, race_pred=None, start=start, end=end,
        cur_stats={"n_nights": 0}, base_stats={"n_nights": 0}, flags=["ℹ️ Sin datos"],
        baseline_weeks=4, notice="Aviso de test",
    )
    assert "Aviso de test" in md
    assert "sin datos. El FR165 lo estima" in md

    # build_report sobre BD con periodo largo (multi-week)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.db"
        with patch("sys.stdout", new_callable=io.StringIO):
            start, end = demo_data.build(db)
            conn = sqlite3.connect(db)
            md_multi, html_multi = build_report(conn, start - timedelta(days=21), end)
            conn.close()
        assert "Evolución semana a semana" in md_multi


def test_main_cli_arguments_and_execution():
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "out"
        demo_db = Path(tmp) / "demo.db"
        with patch("sys.stdout", new_callable=io.StringIO):
            demo_data.build(demo_db)
        with patch("generate_report.OUTPUT_DIR", output_dir), \
             patch("generate_report.DB_PATH", demo_db), \
             patch("generate_report.sync") as mock_sync, \
             patch("sys.stdout", new_callable=io.StringIO), \
             patch("sys.stderr", new_callable=io.StringIO):

            # 1. --demo ejecuta y escribe fichero
            with patch("sys.argv", ["generate_report.py", "--demo"]):
                main()
                assert len(list(output_dir.glob("*.html"))) == 1
                assert len(list(output_dir.glob("*.md"))) == 1

            # 2. --inspect-schema ejecuta sin error
            with patch("sys.argv", ["generate_report.py", "--inspect-schema", "--no-sync"]):
                main()

            # 3. Error si --end-date sin --start-date
            with patch("sys.argv", ["generate_report.py", "--end-date", "2026-06-01"]):
                try:
                    main()
                    assert False
                except SystemExit:
                    pass

            # 4. Error si end < start
            with patch("sys.argv", ["generate_report.py", "--start-date", "2026-06-10", "--end-date", "2026-06-01"]):
                try:
                    main()
                    assert False
                except SystemExit:
                    pass

            # 5. Error si BD no existe
            with patch("sys.argv", ["generate_report.py", "--no-sync", "--start-date", "2026-06-01"]), \
                 patch("generate_report.DB_PATH", Path(tmp) / "no_existe.db"):
                try:
                    main()
                    assert False
                except SystemExit as e:
                    assert e.code == 1

            # 6. Rango normal con --no-sync
            with patch("sys.argv", ["generate_report.py", "--no-sync", "--start-date", "2026-06-01", "--end-date", "2026-06-07"]):
                main()


# ===========================================================================
# 5. Tests de render_html.py (Helpers, Gráficas SVG y Generación HTML)
# ===========================================================================

def test_render_helpers_all():
    assert _esc("<tag>&'\"") == "&lt;tag&gt;&amp;&#x27;&quot;"

    assert _parse_ts(None) is None
    assert _parse_ts("") is None
    assert _parse_ts("basura") is None
    assert _parse_ts("2026-06-15T23:12:00") == datetime(2026, 6, 15, 23, 12, 0)
    assert _parse_ts("2026-06-15 23:12:00") == datetime(2026, 6, 15, 23, 12, 0)

    assert _median([]) is None
    assert _median([10]) == 10
    assert _median([10, 20]) == 15.0
    assert _median([10, None, 30]) == 20

    assert _nice_bounds([], from_zero=False) == (0.0, 1.0)
    assert _nice_bounds([], from_zero=False, ylim=(10, 20)) == (10.0, 20.0)
    assert _nice_bounds([5, 5], from_zero=False) == (4.85, 6.15)
    assert _nice_bounds([20, 80], from_zero=True, ylim=(0, 100)) == (0.0, 80.0)

    assert _xlabels([]) == ""
    assert '<text' in _xlabels(["Lun", "Mar"])
    assert '<text' in _xlabels([f"D{i}" for i in range(20)])  # Diezmado

    assert _legend([("Serie A", "red")]) == ""  # <2 series
    assert '<div class="legend">' in _legend([("A", "red"), ("B", "blue")])

    frame_html = _frame("Título", "<path/>", note="Nota al pie", cls="custom")
    assert "<figcaption>Título</figcaption>" in frame_html
    assert "class=\"chart custom\"" in frame_html
    assert "Nota al pie" in frame_html


def test_svg_line_all_branches():
    # Con huecos de None intermedios (múltiples polilíneas)
    labels = ["L", "M", "X", "J", "V"]
    values = [50, 55, None, 60, 65]
    svg = svg_line("Línea", labels, values, "Test", unit=" bpm", band=(45, 65), band_label="Banda")
    assert svg.count("<polyline") == 2
    assert "band-range" in svg
    assert "<circle" in svg


def test_svg_sleep_timeline_all_branches():
    # Noche con start >= end debe ignorarse
    bad_night = SleepNight("2026-06-16", "2026-06-16 08:00:00", "2026-06-16 07:00:00")
    # Noche sin desglose de fases (debe dibujar rect liso)
    plain_night = SleepNight("2026-06-17", "2026-06-16 23:00:00", "2026-06-17 07:00:00", sleep_s=8*3600)
    # Noche corta (<6h)
    short_night = SleepNight("2026-06-18", "2026-06-18 01:00:00", "2026-06-18 06:00:00", sleep_s=5*3600)

    svg = svg_sleep_timeline("Sueño", ["1", "2", "3"], [bad_night, plain_night, short_night], fmt_duration)
    assert 'class="tick short"' in svg
    assert 'class="ph-light"' in svg
    assert 'mediana acostarse' in svg


def test_svg_recovery_map_all_branches():
    assert svg_recovery_map("Map", ["L"], [50], [60], 48, 62) == ""  # <2 puntos
    assert svg_recovery_map("Map", ["L", "M"], [50, 52], [60, 58], None, None) == ""  # Sin base

    svg = svg_recovery_map("Map", ["L", "M"], [50, 52], [60, 58], 48, 62, swc_low=55, swc_high=68)
    assert "swc-band" in svg
    assert "RECUPERADO" in svg
    assert "(hoy)" in svg


def test_svg_week_wheel_all_branches():
    assert svg_week_wheel("Wheel", ["L", "M"], [None, 0]) == ""
    svg = svg_week_wheel("Wheel", ["L", "M", "X"], [8000, 12000, 9000], goal=10000)
    assert "wheel-goal" in svg
    assert "wedge good" in svg


def test_svg_battery_range_all_branches():
    assert svg_battery_range("BB", ["L"], [None], [None], [None]) == ""
    svg = svg_battery_range("BB", ["L", "M", "X"], [20, 15, None], [90, 85, None], [30, None, 40])
    assert "bb-range" in svg
    assert "dot stress" in svg


def test_svg_spo2_resp_all_branches():
    assert svg_spo2_resp("SpO2", ["L"], [None], [None], [None]) == ""
    # Con SpO2 y con Respiración
    svg = svg_spo2_resp("SpO2", ["L", "M"], [92, 94], [96, 97], [13.5, 14.0])
    assert "spo2-bar" in svg
    assert "dot resp" in svg
    assert "resp/min" in svg

    # Solo Respiración con valores idénticos (lo_resp == hi_resp)
    svg_same_resp = svg_spo2_resp("Resp", ["L", "M"], [None, None], [None, None], [14.0, 14.0])
    assert "dot resp" in svg_same_resp


def test_svg_intensity_bars_all_branches():
    assert svg_intensity_bars("Int", ["L"], [None]) == ""
    svg = svg_intensity_bars("Int", ["L", "M"], [20, 50], goal=30)
    assert "int-bar good" in svg
    assert "band-line" in svg


def test_fitness_cards_html_all_branches():
    assert fitness_cards_html(None, None) == ""

    vo2max = (48.5, 45.0, "2026-06-01")
    race_pred = ("2026-06-01", 1200, 2500, 5600, 12000)
    html = fitness_cards_html(vo2max, race_pred)
    assert "VO2máx Carrera" in html
    assert "VO2máx Ciclismo" in html
    assert "5K" in html
    assert "Maratón (42K)" in html


def test_build_charts_all_branches():
    start = date(2026, 6, 1)
    end = date(2026, 6, 7)
    sample_night = SleepNight(
        "2026-06-02", "2026-06-01 23:00:00", "2026-06-02 07:00:00",
        8 * 3600, 3600, 4 * 3600, 2 * 3600, 0,
        85, 60, "BALANCED", 48, 95, 92, 14,
    )
    charts = build_charts(
        sleep_rows=[sample_night],
        stress_map={"2026-06-01": 25},
        bb_map={"2026-06-01": (90, 20)},
        steps_map={"2026-06-01": 10000},
        start=start, end=end,
        baselines={"rhr": 46, "hrv": 60, "swc_low": 52, "swc_high": 68},
        intensity_map={"2026-06-01": (40, 20, 10)},
        vo2max=(48, None, "2026-06-01"),
        race_pred=("2026-06-01", 1200, 2500, 5600, 12000),
    )
    assert "Sueño" in charts
    assert "FC reposo + HRV nocturno" in charts
    assert "Respiración y SpO2 nocturnos" in charts
    assert "Estrés y Body Battery" in charts
    assert "Actividad" in charts
    assert "Forma física" in charts


def test_rings_and_tiles_html_branches():
    assert rings_html([]) == ""
    rings = [("Actividad", 1.0, "300 min", "Detalle", "good")]
    r_html = rings_html(rings)
    assert "ring-track" in r_html
    assert "ring-val good" in r_html

    assert tiles_html([]) == ""
    tiles = [("FC reposo", "48 bpm", "▲ 2 bpm", "bad")]
    t_html = tiles_html(tiles)
    assert '<div class="tile">' in t_html
    assert '<div class="t bad">' in t_html


def test_md_to_html_all_branches():
    assert _signal_class("⚠️ Alerta") == "warn"
    assert _signal_class("ℹ️ Info") == "info"
    assert _signal_class("Texto normal") == ""

    assert _slug("FC reposo + HRV") == "fc-reposo-hrv"
    assert _slug("¡¡¿¿!!") == "seccion"

    assert _inline("**Negrita** y _cursiva_") == "<strong>Negrita</strong> y <em>cursiva</em>"
    assert _cell("Texto normal") == "Texto normal"
    assert '<span class="zones"' in _cell("10/20/30/40/0")

    table_raw = ["| Col1 | Col2 |", "|:---|---:|", "| A | B |"]
    t_out = _table(table_raw)
    assert '<td style="text-align:right">B</td>' in t_out

    # Markdown completo cubriendo todas las ramas de md_to_html
    full_md = (
        "# Titular Principal\n\n"
        "_Entradilla del informe_\n\n"
        "---\n\n"
        "## Resumen\n\n"
        "- ⚠️ Señal 1\n\n"
        "| Métrica | Valor |\n"
        "|---------|------:|\n"
        "| FC | 50 |\n\n"
        "## Forma física\n\n"
        "- Nota con viñeta\n"
        "Nota sin viñeta explicativa\n\n"
        "## Sección con detalles\n\n"
        "### Subsección 1\n\n"
        "| Dia | Km |\n"
        "|-----|---:|\n"
        "| Lun | 10 |\n\n"
        "**Media:** 10 km\n"
        "**Intensidad:** 150 min\n\n"
        "- Viñeta interna\n\n"
        "---\n\n"
        "Texto de pie\n"
    )
    rendered = md_to_html(full_md, {"Sección con detalles": "<svg></svg>"})
    assert "<h1>Titular Principal</h1>" in rendered
    assert "Métricas en detalle" in rendered
    assert "Notas sobre VO2máx" in rendered
    assert "Subsección 1" in rendered
    assert "key-metric" in rendered


def test_logo_svg_and_favicon_link_branches():
    assert "<svg" in logo_svg()
    assert '<link rel="icon"' in favicon_link()

    with patch("pathlib.Path.read_text", side_effect=OSError):
        assert logo_svg() == ""
    with patch("pathlib.Path.read_bytes", side_effect=OSError):
        assert favicon_link() == ""


def test_navbar_and_render_full():
    body = '<section class="sec" id="sueno"><h2>Sueño</h2></section>'
    nav = _navbar("Garmin Log", body)
    assert '<a href="#sueno">Sueño</a>' in nav

    full_html = render(
        md="# Título\n\n## Sueño\n\nContenido",
        sleep_rows=[],
        stress_map={},
        bb_map={},
        steps_map={},
        start=date(2026, 6, 1),
        end=date(2026, 6, 7),
        rings=[("Actividad", 1.0, "300 min", "OMS", "good")],
        tiles=[("FC reposo", "48 bpm", "■ =", "")],
    )
    assert "<!doctype html>" in full_html
    assert "topbar" in full_html
    assert "Sueño" in full_html

def test_additional_coverage_cases():
    # 1. compute_social_jetlag con fecha inválida en una noche
    bad_night = SleepNight("2026-06-03", "invalido", "2026-06-03 07:00:00", 8 * 3600)
    thu = SleepNight("2026-06-05", "2026-06-04 23:00:00", "2026-06-05 07:00:00", 8 * 3600)
    fri = SleepNight("2026-06-06", "2026-06-06 01:00:00", "2026-06-06 09:00:00", 8 * 3600)
    sat = SleepNight("2026-06-07", "2026-06-07 01:00:00", "2026-06-07 09:00:00", 8 * 3600)
    assert compute_social_jetlag([bad_night, thu, fri, sat]) == 120

    # 2. compute_aerobic_decoupling con laps de duración 0 y con ef1 <= 0
    zero_dur_laps = [
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 140.0, "total_timer_time": 0, "total_elapsed_time": 0},
        {"enhanced_avg_speed": 3.33, "avg_heart_rate": 140.0, "total_timer_time": 0, "total_elapsed_time": 0},
    ]
    assert compute_aerobic_decoupling(zero_dur_laps) == (23.79, 0.0)

    zero_ef_laps = [
        {"avg_power": 0.0, "enhanced_avg_speed": 0.0, "avg_heart_rate": 140.0},
        {"avg_power": 0.0, "enhanced_avg_speed": 0.0, "avg_heart_rate": 140.0},
    ]
    assert compute_aerobic_decoupling(zero_ef_laps) == (None, None)

    # 3. tz_offset_minutes con sqlite3.Error
    err_conn = MagicMock()
    err_conn.execute.side_effect = sqlite3.OperationalError("db error")
    assert tz_offset_minutes(err_conn) == 0

    # 4. query_acwr con sqlite3.Error y con histórico vacío
    err_conn2 = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = sqlite3.OperationalError("db error")
    err_conn2.cursor.return_value = mock_cursor
    assert query_acwr(err_conn2, date(2026, 6, 21)) == NO_ACWR

    empty_db = _create_sample_db()
    assert query_acwr(empty_db, date(2026, 6, 21)) == NO_ACWR

    # 5. add_min_hr sin filas para la actividad
    laps_test = [{}]
    add_min_hr(empty_db, 999, "2026-06-01 08:00:00", laps_test)
    assert "min_heart_rate" not in laps_test[0]

    # 6. recovery_score con 5 noches pero sin métricas de HRV ni RHR
    assert recovery_score({"n_nights": 5}, {"n_nights": 5}) is None

    # 7. generate_md con alteraciones respiratorias y ciclismo VO2max
    night_sev = SleepNight(
        "2026-06-02", "2026-06-01 23:00:00", "2026-06-02 07:00:00",
        8 * 3600, 3600, 4 * 3600, 2 * 3600, 0,
        85, 60, "BALANCED", 48, 95, 92, 14,
        breathing_severity="MODERATE",
    )
    md = generate_md(
        sleep_rows=[night_sev], stress_map={}, bb_map={}, activity_map={},
        steps_map={}, intensity_map={}, floors_map={}, act_detail=[], laps_map={},
        records=[], vo2max=(50.0, 45.0, "2026-06-01"), race_pred=None,
        start=date(2026, 6, 1), end=date(2026, 6, 1),
        cur_stats={"n_nights": 1}, base_stats={"n_nights": 0}, flags=[],
        baseline_weeks=4,
    )
    assert "Alteraciones respiratorias" in md
    assert "**45** (bici)" in md

    # 8. build_report con BD vacía lanza aviso
    with patch("sys.stdout", new_callable=io.StringIO):
        build_report(empty_db, date(2026, 6, 1), date(2026, 6, 7))

    # 9. main() con --demo y --start-date combinados
    with tempfile.TemporaryDirectory() as tmp_demo:
        with patch("generate_report.OUTPUT_DIR", Path(tmp_demo)), \
             patch("sys.argv", ["generate_report.py", "--demo", "--start-date", "2026-06-01"]), \
             patch("sys.stdout", new_callable=io.StringIO), \
             patch("sys.exit") as mock_exit, patch("sys.stderr", new_callable=io.StringIO):
            main()
            mock_exit.assert_called()

    # 10. main() flujo de sincronización por defecto
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "out"
        demo_db = Path(tmp) / "demo.db"
        with patch("sys.stdout", new_callable=io.StringIO):
            demo_data.build(demo_db)
        with patch("generate_report.OUTPUT_DIR", out_dir), \
             patch("generate_report.DB_PATH", demo_db), \
             patch("generate_report.sync") as mock_sync, \
             patch("sys.stdout", new_callable=io.StringIO), \
             patch("sys.argv", ["generate_report.py", "--start-date", "2026-06-01", "--end-date", "2026-06-07"]):
            main()
            mock_sync.assert_called_once()

    # 11. render_html casos límite
    # svg_sleep_timeline con fase de 0 segundos
    night_zero_ph = SleepNight(
        "2026-06-02", "2026-06-01 23:00:00", "2026-06-02 07:00:00",
        8 * 3600, deep_s=0, rem_s=0, light_s=8 * 3600, awake_s=0,
    )
    assert svg_sleep_timeline("Sueño", ["L"], [night_zero_ph], fmt_duration) != ""

    # fitness_cards_html con tiempos parciales (None, 0 y válidos)
    assert fitness_cards_html(None, ("2026-06-01", 1200, None, 0, None)) != ""
    assert fitness_cards_html(None, ("2026-06-01", None, None, None, None)) == ""

    # build_charts solo con pasos (sin minutos de intensidad) -> activa rama 'elif wheel'
    c = build_charts(
        sleep_rows=[], stress_map={}, bb_map={}, steps_map={"2026-06-01": 8000},
        start=date(2026, 6, 1), end=date(2026, 6, 1),
    )
    assert "Actividad" in c

    # md_to_html con sección vacía
    assert "<h2>Sueño</h2>" in md_to_html("## \n\n## Sueño\n\nTexto")


# ===========================================================================
# Ejecución directa
# ===========================================================================

if __name__ == "__main__":
    count = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            count += 1
            print(f"OK  {name}")
    print(f"\nTodos los {count} tests pasan.")

