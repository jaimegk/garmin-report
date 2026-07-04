#!/usr/bin/env python3
"""Comprobaciones mínimas de la lógica pura de generate_report.py.

Ejecutar: python test_report.py  (sin dependencias, solo asserts)
"""

from datetime import date

from generate_report import (
    SleepNight, bed_minutes, wake_minutes, sd_minutes, fmt_duration,
    fmt_trend, fmt_hms, iso_weeks_in_range, compute_flags,
)


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
    print("Todos los tests pasan.")
