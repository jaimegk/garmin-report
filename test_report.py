#!/usr/bin/env python3
"""Comprobaciones mínimas de la lógica pura de generate_report.py.

Ejecutar: python test_report.py  (sin dependencias, solo asserts)
"""

import re
import types
from datetime import date

import generate_report
from generate_report import (
    SleepNight, bed_minutes, wake_minutes, sd_minutes, fmt_duration,
    fmt_trend, fmt_hms, iso_weeks_in_range, compute_flags,
    fmt_pace, fmt_zones, sync,
)
from render_html import md_to_html, svg_bars


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
            "bed_sd": 25, "wake_sd": 20, "vo2max": 48}
    cur = dict(base)

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


def test_fmt_pace_por_deporte():
    # 3.33 m/s ≈ 5:00/km corriendo; en bici se muestra km/h; en pádel, nada
    assert fmt_pace(1000 / 300, "running") == "5:00/km"
    assert fmt_pace(1000 / 300, "indoor_cycling") == "12.0 km/h"
    assert fmt_pace(100 / 130, "lap_swimming") == "2:10/100m"
    assert fmt_pace(1000 / 300, "paddelball") == "–"
    assert fmt_pace(None, "running") == "–"


def test_fmt_zones():
    assert fmt_zones([0, 300, 600, 100, 0]) == "0/30/60/10/0"
    assert fmt_zones([None] * 5) == "–"


def test_md_to_html():
    md = (
        "## Sueño\n\n"
        "| Día | Horas |\n"
        "|-----|------:|\n"
        "| Lun | 7h30 |\n\n"
        "**Media:** 7h30\n\n"
        "- ⚠️ Una señal\n"
    )
    out = md_to_html(md, {"Sueño": "<svg id='grafica'></svg>"})

    assert "<h2>Sueño</h2>" in out
    # La gráfica se inyecta justo después de su encabezado, no al final
    assert out.index("<svg id='grafica'>") == out.index("</h2>") + len("</h2>") + 1
    # La fila separadora no se convierte en datos y la alineación se traslada
    assert out.count("<tr>") == 2 and "<th>Día</th>" in out
    assert '<td style="text-align:right">7h30</td>' in out
    assert "<strong>Media:</strong>" in out
    assert "<ul><li>⚠️ Una señal</li></ul>" in out


def test_svg_bars_escala_y_huecos():
    svg = svg_bars("t", ["a", "b", "c"], [[10, None, 20]], ("Pasos",))
    heights = [float(h) for h in re.findall(r'height="([\d.]+)"', svg)]

    # Dos barras, no tres: el None no dibuja nada
    assert len(heights) == 2
    # ...y no desplaza la escala: 10 es la mitad de 20
    assert abs(heights[0] * 2 - heights[1]) < 0.5
    # Un rango entero sin datos no revienta
    assert '<rect' not in svg_bars("t", ["a", "b"], [[None, None]], ("Pasos",))


def test_sync_pasa_el_rango_a_extract():
    calls = []
    orig_run, orig_bin = generate_report.subprocess.run, generate_report.VENV_BIN
    generate_report.subprocess.run = lambda cmd, **kw: (calls.append(cmd), types.SimpleNamespace(returncode=0))[1]
    generate_report.VENV_BIN = type("P", (), {"exists": lambda self: True, "__str__": lambda self: "garmin"})()
    try:
        sync(date(2026, 4, 11), date(2026, 5, 5))
        sync(date(2026, 4, 11), date(2026, 4, 11))
        sync()
    finally:
        generate_report.subprocess.run, generate_report.VENV_BIN = orig_run, orig_bin

    # --end-date de garmin extract es exclusivo → +1 día para incluir el 05-05
    assert calls[0][1:] == ["extract", "--start-date", "2026-04-11", "--end-date", "2026-05-06"]
    # Un solo día es el caso especial: extract lo incluye sin --end-date
    assert calls[1][1:] == ["extract", "--start-date", "2026-04-11"]
    # Sin rango, sincronización incremental de siempre
    assert calls[2][1:] == ["extract"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
    print("Todos los tests pasan.")
