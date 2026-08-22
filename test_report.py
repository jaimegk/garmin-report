#!/usr/bin/env python3
"""Comprobaciones de generate_report.py y render_html.py.

Ejecutar: python test_report.py  (sin dependencias, solo asserts)
"""

import re
import sqlite3
import tempfile
import types
from datetime import date, timedelta
from pathlib import Path

import generate_report
import demo_data
from generate_report import (
    SleepNight, bed_minutes, wake_minutes, sd_minutes, fmt_duration,
    fmt_trend, fmt_hms, iso_weeks_in_range, compute_flags,
    fmt_pace, fmt_zones, sync, build_report, summary_tiles, summary_rings,
    recovery_score, compute_sri, compute_social_jetlag, compute_hrv_stability,
    compute_acwr_ewma, compute_aerobic_decoupling, query_acwr,
)
from render_html import md_to_html, svg_sleep_timeline, svg_week_wheel


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
    print("Todos los tests pasan.")
