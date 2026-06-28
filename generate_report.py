#!/usr/bin/env python3
"""
Genera un informe en markdown con datos de salud de Garmin Connect.

Flujo: garmin extract (incremental) → SQLite local → output/garmin_log.md

Uso:
  python generate_report.py                                    # última semana ISO + sync
  python generate_report.py --no-sync                         # última semana, sin sync
  python generate_report.py --start-date 2026-05-28           # desde fecha hasta hoy
  python generate_report.py --start-date 2026-05-01 --end-date 2026-05-31
  python generate_report.py --inspect-schema                  # lista tablas y columnas
"""

import argparse
import os
import sqlite3
import statistics
import subprocess
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "garmin_data.db"
OUTPUT_PATH = PROJECT_DIR / "output" / "garmin_log.md"
VENV_BIN = PROJECT_DIR / ".venv" / "bin" / "garmin"

# Semanas previas usadas como media de referencia para las tendencias
BASELINE_WEEKS = 4

DAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]

ACTIVITY_LABELS = {
    "indoor_cycling":      "bici indoor",
    "cycling":             "bici",
    "road_biking":         "bici",
    "treadmill_running":   "cinta",
    "running":             "running",
    "trail_running":       "trail",
    "lap_swimming":        "natación",
    "open_water_swimming": "natación OW",
    "strength_training":   "gym",
    "fitness_equipment":   "gym",
    "elliptical":          "elíptica",
    "yoga":                "yoga",
    "breathwork":          "breathwork",
    "walking":             "caminar",
    "hiking":              "senderismo",
}

# Guía de actividad de la OMS (minutos de intensidad equivalentes/semana).
# Garmin cuenta el minuto vigoroso doble, igual que la OMS.
INTENSITY_TARGET_MIN = 150
INTENSITY_TARGET_MAX = 300

# Estado de HRV nocturno (Garmin) → etiqueta en español
HRV_STATUS_ES = {
    "BALANCED": "equilibrado",
    "UNBALANCED": "desequilibrado",
    "LOW": "bajo",
    "POOR": "malo",
    "NONE": "sin datos",
}

# Fila de sueño con acceso por nombre (evita errores de índice al ampliar columnas).
SleepNight = namedtuple("SleepNight", [
    "calendar_date", "start_ts", "end_ts",
    "sleep_s", "deep_s", "light_s", "rem_s", "awake_s",
    "score", "hrv", "hrv_status", "rhr",
    "spo2_avg", "spo2_min", "resp_avg",
])


# ---------------------------------------------------------------------------
# Helpers de formato
# ---------------------------------------------------------------------------

def fmt_duration(seconds):
    if seconds is None:
        return "–"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m:02d}"


def fmt_val(v, unit="", fallback="–"):
    if v is None:
        return fallback
    if isinstance(v, float):
        return f"{round(v)}{unit}"
    return f"{v}{unit}"


def to_local(ts, offset_hours):
    """Convierte un timestamp UTC de Garmin a hora local.

    Garmin guarda start_ts/end_ts en UTC; la hora local es UTC +
    `timezone_offset_hours`. Sin esto, las horas de acostarse/despertar salen
    desfasadas (p. ej. 2 h en horario de verano peninsular).
    """
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return ts
    return (dt + timedelta(hours=offset_hours or 0)).strftime("%Y-%m-%d %H:%M:%S")


def fmt_clock(ts) -> str:
    """'2026-06-25 22:08:28' → '22:08'. '–' si falta."""
    if not ts or len(str(ts)) < 16:
        return "–"
    return str(ts)[11:16]


def fmt_hms(seconds) -> str:
    """Segundos → 'h:mm:ss' o 'mm:ss' (predicciones de carrera)."""
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clock_minutes(ts, *, wrap_after_midnight: bool):
    """Minuto del día del timestamp. Para la hora de acostarse, suma 24 h si
    es de madrugada (<12 h) para que 23:30 y 00:17 no 'salten' al medir
    dispersión."""
    if not ts or len(str(ts)) < 16:
        return None
    try:
        h, m = int(str(ts)[11:13]), int(str(ts)[14:16])
    except ValueError:
        return None
    mins = h * 60 + m
    if wrap_after_midnight and h < 12:
        mins += 24 * 60
    return mins


def bed_minutes(ts):
    return _clock_minutes(ts, wrap_after_midnight=True)


def wake_minutes(ts):
    return _clock_minutes(ts, wrap_after_midnight=False)


def sd_minutes(values):
    """Desviación típica (muestral) en minutos; None si <3 valores válidos."""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    return statistics.stdev(vals)


# ---------------------------------------------------------------------------
# Rango de fechas
# ---------------------------------------------------------------------------

def last_week_range() -> tuple[date, date]:
    """Devuelve (lunes, domingo) de la semana ISO anterior."""
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    return last_monday, last_monday + timedelta(days=6)


def parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        print(f"[ERROR] Fecha inválida: '{s}'. Usa formato YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------

def sync():
    if not VENV_BIN.exists():
        print(f"[ERROR] No se encuentra el ejecutable: {VENV_BIN}", file=sys.stderr)
        print("Ejecuta: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [str(VENV_BIN), "extract"],
        env={**os.environ},
        cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        print(f"[ERROR] garmin extract falló con código {result.returncode}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Consultas SQLite
# ---------------------------------------------------------------------------

def inspect_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (table,) in cur.fetchall():
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        print(f"\n{table}:")
        print("  " + ", ".join(cols))


def tz_offset_minutes(conn: sqlite3.Connection) -> int:
    """Offset horario (minutos) para convertir UTC→local en las agregaciones por
    día. Garmin guarda los timeseries en UTC pero no incluye el offset en todas
    las tablas, así que lo tomamos del registro más reciente que sí lo trae
    (sleep → activity). Asume un offset estable en el periodo (sin cambio de hora).
    """
    for sql in (
        "SELECT timezone_offset_hours FROM sleep ORDER BY calendar_date DESC LIMIT 1",
        "SELECT timezone_offset_hours FROM activity ORDER BY start_ts DESC LIMIT 1",
    ):
        try:
            row = conn.execute(sql).fetchone()
        except sqlite3.Error:
            row = None
        if row and row[0] is not None:
            return int(round(row[0] * 60))
    return 0


def local_day(col: str, minutes: int) -> str:
    """Expresión SQL para la fecha LOCAL de una columna de timestamp UTC.
    `minutes` es un entero validado, seguro para interpolar."""
    sign = "+" if minutes >= 0 else "-"
    return f"date({col}, '{sign}{abs(minutes)} minutes')"


def query_sleep(conn: sqlite3.Connection, start: date, end: date) -> list:
    # Usamos calendar_date como clave: es única por sesión y garantiza cero huecos.
    # calendar_date = día en que te despiertas; lo mostramos como (calendar_date - 1)
    # para que la etiqueta refleje la noche en que te acostaste.
    # Rango: calendar_date desde start+1 hasta end+1 para capturar las noches correctas.
    range_start = (start + timedelta(days=1)).isoformat()
    range_end = (end + timedelta(days=1)).isoformat()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            calendar_date,
            start_ts,
            end_ts,
            sleep_time_seconds,
            deep_sleep_seconds,
            light_sleep_seconds,
            rem_sleep_seconds,
            awake_sleep_seconds,
            score_overall_value,
            avg_overnight_hrv,
            hrv_status,
            resting_heart_rate,
            average_spo2,
            lowest_spo2,
            average_respiration,
            timezone_offset_hours
        FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
        ORDER BY calendar_date
    """, (range_start, range_end))
    nights = []
    for r in cur.fetchall():
        tz = r[15]  # timezone_offset_hours: start_ts/end_ts → hora local
        nights.append(SleepNight(r[0], to_local(r[1], tz), to_local(r[2], tz), *r[3:15]))
    return nights


def query_intensity(conn: sqlite3.Connection, start: date, end: date) -> dict:
    """Devuelve {fecha_str: (total_equiv, moderada, vigorosa)} en min/día."""
    cur = conn.cursor()
    cur.execute("""
        SELECT date, total_intensity_minutes, moderate_minutes, vigorous_minutes
        FROM training_load
        WHERE date >= ? AND date <= ?
        ORDER BY date
    """, (start.isoformat(), end.isoformat()))
    return {str(r[0]): (r[1], r[2], r[3]) for r in cur.fetchall()}


def query_vo2max(conn: sqlite3.Connection, end: date):
    """(vo2_generico, vo2_cycling, fecha|None) del último registro ≤ end, o None.
    Prioridad: tabla vo2_max (serie por fecha) → user_profile (instantánea)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT vo2_max_generic, vo2_max_cycling, date FROM vo2_max
        WHERE date <= ? ORDER BY date DESC LIMIT 1
    """, (end.isoformat(),))
    r = cur.fetchone()
    if r and (r[0] is not None or r[1] is not None):
        return (r[0], r[1], str(r[2]) if r[2] else None)
    cur.execute("""
        SELECT vo2_max_running, vo2_max_cycling FROM user_profile
        WHERE latest = 1 ORDER BY user_profile_id DESC LIMIT 1
    """)
    r = cur.fetchone()
    if r and (r[0] is not None or r[1] is not None):
        return (r[0], r[1], None)
    return None


def query_race_predictions(conn: sqlite3.Connection):
    """Predicción de ritmos (5k/10k/media/maratón) más reciente, o None.
    Es una instantánea de forma actual; se anota su fecha al mostrarla."""
    cur = conn.cursor()
    cur.execute("""
        SELECT date, time_5k, time_10k, time_half_marathon, time_marathon
        FROM race_predictions
        ORDER BY latest DESC, date DESC LIMIT 1
    """)
    return cur.fetchone()


def regularity_over_period(conn: sqlite3.Connection, start: date, end: date):
    """Media de la regularidad semanal del sueño: (SD acostarse, SD despertar)
    en minutos, agrupando las noches por semana ISO. Para un periodo de una
    semana equivale a la SD de esa semana."""
    s1 = (start + timedelta(days=1)).isoformat()
    e1 = (end + timedelta(days=1)).isoformat()
    rows = conn.execute("""
        SELECT calendar_date, start_ts, end_ts, timezone_offset_hours FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
        ORDER BY calendar_date
    """, (s1, e1)).fetchall()
    weeks: dict = {}
    for cal, start_ts, end_ts, tz in rows:
        night = date.fromisoformat(cal) - timedelta(days=1)
        key = tuple(night.isocalendar()[:2])  # (año, semana ISO)
        weeks.setdefault(key, []).append((to_local(start_ts, tz), to_local(end_ts, tz)))
    bed_sds = [sd_minutes([bed_minutes(s) for s, _ in g]) for g in weeks.values()]
    wake_sds = [sd_minutes([wake_minutes(e) for _, e in g]) for g in weeks.values()]
    bed_sds = [x for x in bed_sds if x is not None]
    wake_sds = [x for x in wake_sds if x is not None]
    bed = statistics.mean(bed_sds) if bed_sds else None
    wake = statistics.mean(wake_sds) if wake_sds else None
    return bed, wake


def query_stress(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    # value < 0 = sin lectura (-1) o durante actividad (-2)
    day = local_day("timestamp", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {day} AS day, ROUND(AVG(value)) AS avg_stress
        FROM stress
        WHERE {day} >= ? AND {day} <= ?
          AND value >= 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: row[1] for row in cur.fetchall()}


def query_body_battery(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    day = local_day("timestamp", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {day} AS day, MAX(value) AS bb_max, MIN(value) AS bb_min
        FROM body_battery
        WHERE {day} >= ? AND {day} <= ?
          AND value >= 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def query_activities(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    """Devuelve {fecha_str: [(tipo, minutos, avg_hr, bb_delta), ...]} por día."""
    day = local_day("start_ts", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            {day} AS day,
            activity_type_key,
            ROUND(duration / 60) AS minutes,
            ROUND(average_hr) AS avg_hr,
            difference_body_battery AS bb_delta
        FROM activity
        WHERE {day} >= ? AND {day} <= ?
          AND parent = 0
          AND activity_type_key != 'breathwork'
        ORDER BY start_ts
    """, (start.isoformat(), end.isoformat()))
    result: dict = {}
    for day, atype, mins, hr, bb in cur.fetchall():
        result.setdefault(day, []).append((atype, mins, hr, bb))
    return result


def query_steps(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    """Devuelve {fecha_str: total_pasos} por día."""
    day = local_day("timestamp", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {day} AS day, SUM(value) AS total
        FROM steps
        WHERE {day} >= ? AND {day} <= ?
          AND value > 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Tendencias y señales
# ---------------------------------------------------------------------------

def metric_stats(conn: sqlite3.Connection, start: date, end: date, tz_min: int = 0) -> dict:
    """Medias agregadas del periodo [start, end] para comparar tendencias.

    Las métricas de sueño se indexan por la noche (calendar_date = día + 1),
    igual que en el resto del informe. Cada métrica es None si no hay datos.
    """
    day_ts = local_day("timestamp", tz_min)
    cur = conn.cursor()
    s1 = (start + timedelta(days=1)).isoformat()
    e1 = (end + timedelta(days=1)).isoformat()
    cur.execute("""
        SELECT
            AVG(NULLIF(sleep_time_seconds, 0)),
            AVG(score_overall_value),
            AVG(resting_heart_rate),
            AVG(avg_overnight_hrv),
            COUNT(NULLIF(sleep_time_seconds, 0))
        FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
    """, (s1, e1))
    sleep_s, score, rhr, hrv, n_nights = cur.fetchone()

    cur.execute(f"""
        SELECT AVG(value) FROM stress
        WHERE {day_ts} >= ? AND {day_ts} <= ? AND value >= 0
    """, (start.isoformat(), end.isoformat()))
    stress = cur.fetchone()[0]

    cur.execute(f"""
        SELECT SUM(value), COUNT(DISTINCT {day_ts})
        FROM steps
        WHERE {day_ts} >= ? AND {day_ts} <= ? AND value > 0
    """, (start.isoformat(), end.isoformat()))
    steps_sum, steps_days = cur.fetchone()
    steps = (steps_sum / steps_days) if steps_sum and steps_days else None

    # SpO2 nocturna media del periodo
    cur.execute("""
        SELECT AVG(average_spo2) FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
    """, (s1, e1))
    spo2 = cur.fetchone()[0]

    # Minutos de intensidad equivalentes, normalizados a semana
    cur.execute("""
        SELECT SUM(total_intensity_minutes), COUNT(*) FROM training_load
        WHERE date >= ? AND date <= ?
    """, (start.isoformat(), end.isoformat()))
    im_sum, im_days = cur.fetchone()
    intensity_week = (im_sum / im_days * 7) if im_sum is not None and im_days else None

    # Regularidad del sueño y VO2máx (último valor disponible)
    bed_sd, wake_sd = regularity_over_period(conn, start, end)
    vo2 = query_vo2max(conn, end)

    return {
        "sleep_s": sleep_s, "score": score, "rhr": rhr, "hrv": hrv,
        "stress": stress, "steps": steps, "n_nights": n_nights or 0,
        "spo2": spo2, "intensity_week": intensity_week,
        "bed_sd": bed_sd, "wake_sd": wake_sd,
        "vo2max": vo2[0] if vo2 else None,
    }


def baseline_range(start: date, weeks: int) -> tuple[date, date]:
    """Ventana de comparación: las `weeks` semanas justo antes del informe."""
    return start - timedelta(days=weeks * 7), start - timedelta(days=1)


def iso_weeks_in_range(start: date, end: date) -> list:
    """Trocea [start, end] en sus semanas ISO, recortadas al rango.

    Devuelve [(num_semana_iso, semana_inicio, semana_fin), ...] en orden
    cronológico. Permite generar tendencias dentro de un informe largo
    (p. ej. un mes → ~4 semanas) en lugar de compararlo con datos previos.
    """
    spans: dict = {}
    d = start
    while d <= end:
        key = tuple(d.isocalendar()[:2])  # (año ISO, semana ISO)
        if key in spans:
            spans[key][1] = d
        else:
            spans[key] = [d, d]
        d += timedelta(days=1)
    return [(key[1], ws, we) for key, (ws, we) in sorted(spans.items(), key=lambda kv: kv[1][0])]


def compute_flags(sleep_rows: list, cur_stats: dict, base_stats: dict) -> list[str]:
    """Reglas simples sobre los datos para resaltar lo que merece atención.

    sleep_rows: lista de SleepNight del periodo, ordenadas por fecha.
    """
    flags: list[str] = []
    have_base = base_stats["n_nights"] >= 5

    # FC reposo elevada varios días seguidos respecto a la media (umbral +5 bpm)
    if have_base and base_stats["rhr"]:
        thr = base_stats["rhr"] + 5
        run = best = 0
        for row in sleep_rows:
            if row.rhr and row.rhr >= thr:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best >= 3:
            flags.append(
                f"⚠️ FC reposo elevada {best} días seguidos respecto a tu media "
                f"({round(base_stats['rhr'])} bpm) — posible fatiga, estrés o estar incubando algo."
            )

    # HRV nocturno desviado de la media (±10%)
    if have_base and base_stats["hrv"] and cur_stats["hrv"]:
        ratio = cur_stats["hrv"] / base_stats["hrv"]
        if ratio <= 0.90:
            flags.append(
                f"⚠️ HRV nocturno un {round((1 - ratio) * 100)}% por debajo de tu media "
                "— señal de carga/estrés; prioriza descanso."
            )
        elif ratio >= 1.10:
            flags.append("✅ HRV nocturno por encima de tu media — buena recuperación.")

    # Noches cortas
    short = sum(1 for r in sleep_rows if r.sleep_s and r.sleep_s < 6 * 3600)
    if short >= 2:
        flags.append(f"⚠️ {short} noches por debajo de 6 h de sueño.")

    # Horario de sueño irregular (SD de la hora de acostarse > 60 min)
    bed_sd = cur_stats.get("bed_sd")
    if bed_sd is not None and bed_sd > 60:
        flags.append(
            f"⚠️ Horario de sueño irregular: la hora de acostarte varía ±{round(bed_sd)} min "
            "esta semana — la regularidad pesa tanto como la duración."
        )

    # Estrés medio elevado respecto a la media (+8)
    if have_base and base_stats["stress"] and cur_stats["stress"]:
        if cur_stats["stress"] >= base_stats["stress"] + 8:
            flags.append(
                f"⚠️ Estrés medio elevado ({round(cur_stats['stress'])}) "
                f"frente a tu media ({round(base_stats['stress'])})."
            )

    # Minutos de intensidad frente a la guía OMS (150–300 equivalentes/semana)
    im = cur_stats.get("intensity_week")
    if im is not None:
        if im < INTENSITY_TARGET_MIN:
            flags.append(
                f"⚠️ Actividad por debajo de la recomendación: {round(im)} min de intensidad "
                f"esta semana (objetivo {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
            )
        elif im <= INTENSITY_TARGET_MAX:
            flags.append(
                f"✅ Actividad en rango saludable: {round(im)} min de intensidad "
                f"(objetivo {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
            )

    # SpO2 nocturna MEDIA baja varias noches (cribado, no diagnóstico).
    # Usamos la media, no el mínimo: caídas puntuales a 85-89% son normales en
    # gente sana; lo relevante es una saturación media sostenidamente baja.
    low_spo2 = sum(1 for n in sleep_rows if n.spo2_avg is not None and n.spo2_avg < 92)
    if low_spo2 >= 3:
        flags.append(
            f"⚠️ SpO2 nocturna media por debajo de 92% en {low_spo2} noches — señal de cribado "
            "(p. ej. apnea del sueño); no es un diagnóstico, coméntalo con un profesional."
        )

    # VO2máx ausente: recordatorio de cómo activarlo
    if cur_stats.get("vo2max") is None:
        flags.append(
            "ℹ️ Sin VO2máx (el predictor de longevidad más potente): el FR165 lo estima con "
            "carreras o caminatas al aire libre con GPS; las sesiones indoor, en cinta o de "
            "natación no lo generan."
        )

    # Señal positiva global (solo si no hay avisos)
    if (cur_stats["sleep_s"] and cur_stats["sleep_s"] >= 7.5 * 3600
            and cur_stats["score"] and cur_stats["score"] >= 85
            and not any(f.startswith("⚠️") for f in flags)):
        flags.append("✅ Buena semana de sueño y recuperación.")

    if not flags:
        flags.append("ℹ️ Sin señales destacables: semana dentro de tus rangos habituales.")
    return flags


def fmt_trend(cur, base, unit: str = "", as_duration: bool = False) -> str:
    """Flecha + magnitud del cambio respecto a la media (sin juzgar el signo)."""
    if cur is None or base is None:
        return "–"
    d = cur - base
    if as_duration:
        mag = abs(round(d / 60))
        if mag == 0:
            return "■ ="
        return f"{'▲' if d > 0 else '▼'} {mag} min"
    arrow = "▲" if d > 0.5 else "▼" if d < -0.5 else "■"
    if arrow == "■":
        return "■ ="
    return f"{arrow} {abs(round(d))}{unit}"


def weekly_breakdown(weekly: list, base: dict, dur, num, steps_fmt, reg) -> list[str]:
    """Tabla de evolución semana a semana (informes multi-semana).

    Una columna por semana ISO del periodo + una columna Tendencia que compara
    la última semana con la media de las anteriores.
    """
    cur = weekly[-1]["stats"]
    heads = " | ".join(w["wk_label"] for w in weekly)
    out = [
        "_Evolución semana a semana. La **tendencia** compara la última semana con la "
        "media de las anteriores._\n\n",
        f"| Métrica | {heads} | Tendencia |\n",
        f"|---------|{'------:|' * len(weekly)}:---------:|\n",
    ]
    specs = [
        ("Sueño",                   "sleep_s",        dur,                      "",     True),
        ("Regularidad (acostarse)", "bed_sd",         reg,                      " min", False),
        ("Score sueño",             "score",          lambda v: num(v),         "",     False),
        ("FC reposo",               "rhr",            lambda v: num(v, " bpm"), " bpm", False),
        ("HRV nocturno",            "hrv",            lambda v: num(v, " ms"),  " ms",  False),
        ("VO2máx",                  "vo2max",         lambda v: num(v),         "",     False),
        ("Estrés medio",            "stress",         lambda v: num(v),         "",     False),
        ("Pasos/día",               "steps",          steps_fmt,                "",     False),
        ("Min. intensidad/sem",     "intensity_week", lambda v: num(v, " min"), " min", False),
    ]
    for label, key, fmt, unit, as_dur in specs:
        cells = " | ".join(fmt(w["stats"][key]) for w in weekly)
        trend = fmt_trend(cur[key], base[key], unit, as_duration=as_dur)
        out.append(f"| {label} | {cells} | {trend} |\n")
    legend = " · ".join(f"{w['wk_label']}: {w['range_label']}" for w in weekly)
    out.append(f"\n_{legend}_\n")
    return out


def build_summary(cur_stats: dict, base_stats: dict, flags: list[str], weeks: int,
                  multi_week: bool = False, weekly: list | None = None) -> list[str]:
    def dur(v):
        return fmt_duration(round(v)) if v else "–"

    def num(v, unit=""):
        return f"{round(v)}{unit}" if v is not None else "–"

    def steps_fmt(v):
        return f"{int(round(v)):,}".replace(",", ".") if v else "–"

    def reg(v):
        return f"±{round(v)} min" if v is not None else "–"

    lines = ["## Resumen\n\n"]
    if multi_week and weekly:
        lines += weekly_breakdown(weekly, base_stats, dur, num, steps_fmt, reg)
    elif base_stats["n_nights"] >= 5:
        lines += [
            f"| Métrica | Esta semana | Tu media (~{weeks} sem) | Tendencia |\n",
            "|---------|------------:|------------------------:|:---------:|\n",
            f"| Sueño | {dur(cur_stats['sleep_s'])} | {dur(base_stats['sleep_s'])} | {fmt_trend(cur_stats['sleep_s'], base_stats['sleep_s'], as_duration=True)} |\n",
            f"| Regularidad (acostarse) | {reg(cur_stats['bed_sd'])} | {reg(base_stats['bed_sd'])} | {fmt_trend(cur_stats['bed_sd'], base_stats['bed_sd'], ' min')} |\n",
            f"| Score sueño | {num(cur_stats['score'])} | {num(base_stats['score'])} | {fmt_trend(cur_stats['score'], base_stats['score'])} |\n",
            f"| FC reposo | {num(cur_stats['rhr'], ' bpm')} | {num(base_stats['rhr'], ' bpm')} | {fmt_trend(cur_stats['rhr'], base_stats['rhr'], ' bpm')} |\n",
            f"| HRV nocturno | {num(cur_stats['hrv'], ' ms')} | {num(base_stats['hrv'], ' ms')} | {fmt_trend(cur_stats['hrv'], base_stats['hrv'], ' ms')} |\n",
            f"| VO2máx | {num(cur_stats['vo2max'])} | {num(base_stats['vo2max'])} | {fmt_trend(cur_stats['vo2max'], base_stats['vo2max'])} |\n",
            f"| Estrés medio | {num(cur_stats['stress'])} | {num(base_stats['stress'])} | {fmt_trend(cur_stats['stress'], base_stats['stress'])} |\n",
            f"| Pasos/día | {steps_fmt(cur_stats['steps'])} | {steps_fmt(base_stats['steps'])} | {fmt_trend(cur_stats['steps'], base_stats['steps'])} |\n",
            f"| Min. intensidad/sem | {num(cur_stats['intensity_week'], ' min')} | {num(base_stats['intensity_week'], ' min')} | {fmt_trend(cur_stats['intensity_week'], base_stats['intensity_week'], ' min')} |\n",
        ]
    else:
        lines += [
            "| Métrica | Esta semana |\n",
            "|---------|------------:|\n",
            f"| Sueño | {dur(cur_stats['sleep_s'])} |\n",
            f"| Regularidad (acostarse) | {reg(cur_stats['bed_sd'])} |\n",
            f"| Score sueño | {num(cur_stats['score'])} |\n",
            f"| FC reposo | {num(cur_stats['rhr'], ' bpm')} |\n",
            f"| HRV nocturno | {num(cur_stats['hrv'], ' ms')} |\n",
            f"| VO2máx | {num(cur_stats['vo2max'])} |\n",
            f"| Estrés medio | {num(cur_stats['stress'])} |\n",
            f"| Pasos/día | {steps_fmt(cur_stats['steps'])} |\n",
            f"| Min. intensidad/sem | {num(cur_stats['intensity_week'], ' min')} |\n",
            "\n_Histórico insuficiente para comparar tendencias (se necesitan ~2 semanas"
            " previas). Aparecerá automáticamente cuando haya más datos._\n",
        ]
    lines.append("\n### Señales\n\n")
    lines += [f"- {f}\n" for f in flags]
    lines.append("\n---\n\n")
    return lines


# ---------------------------------------------------------------------------
# Generación del markdown
# ---------------------------------------------------------------------------

def day_label(d: date, multi_week: bool) -> str:
    """Etiqueta de fila: 'Lun' para semana, '28 may Mié' para rangos largos."""
    if not multi_week:
        return DAYS_ES[d.weekday()]
    return f"{d.day} {MONTHS_ES[d.month]} {DAYS_ES[d.weekday()]}"


def generate_md(
    sleep_rows: list,
    stress_map: dict,
    bb_map: dict,
    activity_map: dict,
    steps_map: dict,
    intensity_map: dict,
    vo2max,
    race_pred,
    start: date,
    end: date,
    cur_stats: dict,
    base_stats: dict,
    flags: list[str],
    baseline_weeks: int,
    weekly: list | None = None,
) -> str:
    num_days = (end - start).days + 1
    multi_week = num_days > 7
    # Mapear calendar_date → noche anterior (el día en que el usuario se acostó)
    sleep_by_date = {
        (date.fromisoformat(n.calendar_date) - timedelta(days=1)).isoformat(): n
        for n in sleep_rows
    }

    # Título dinámico
    if not multi_week:
        week_num = start.isocalendar()[1]
        titulo = f"semana {start.year}-W{week_num:02d} ({start.day} {MONTHS_ES[start.month]} – {end.day} {MONTHS_ES[end.month]} {end.year})"
    else:
        titulo = f"{start.day} {MONTHS_ES[start.month]} – {end.day} {MONTHS_ES[end.month]} {end.year}"

    lines = [
        f"# Garmin log — {titulo}\n\n",
        f"_Generado el {date.today().isoformat()} · Garmin Forerunner 165_\n\n",
        "---\n\n",
    ]

    lines += build_summary(cur_stats, base_stats, flags, baseline_weeks, multi_week, weekly)

    day_col_width = "------------" if multi_week else "-----"

    # --- Sueño ---
    lines += [
        "## Sueño\n\n",
        f"| {'Día':<{len(day_col_width)}} | Acostarse | Despertar | Horas | Deep | REM | Light | Score |\n",
        f"|{day_col_width}|:--------:|:--------:|------:|-----:|----:|------:|------:|\n",
    ]
    total_sleep_s = 0
    total_score = 0
    sleep_count = 0
    present = []
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        n = sleep_by_date.get(d.isoformat())
        if n:
            present.append(n)
            lines.append(
                f"| {label} | {fmt_clock(n.start_ts)} | {fmt_clock(n.end_ts)}"
                f" | {fmt_duration(n.sleep_s)} | {fmt_duration(n.deep_s)}"
                f" | {fmt_duration(n.rem_s)} | {fmt_duration(n.light_s)} | {fmt_val(n.score)} |\n"
            )
            if n.sleep_s:
                total_sleep_s += n.sleep_s
                sleep_count += 1
            if n.score:
                total_score += n.score
        else:
            lines.append(f"| {label} | – | – | – | – | – | – | – |\n")

    avg_sleep = fmt_duration(total_sleep_s // sleep_count) if sleep_count else "–"
    avg_score = round(total_score / sleep_count) if sleep_count else "–"

    # Regularidad (dispersión de las horas de acostarse/despertar) y desvelo medio
    bed_sd = sd_minutes([bed_minutes(n.start_ts) for n in present])
    wake_sd = sd_minutes([wake_minutes(n.end_ts) for n in present])
    awake_vals = [n.awake_s for n in present if n.awake_s is not None]
    avg_awake = round(sum(awake_vals) / len(awake_vals) / 60) if awake_vals else None

    reg_parts = []
    if bed_sd is not None:
        reg_parts.append(f"acostarse ±{round(bed_sd)} min")
    if wake_sd is not None:
        reg_parts.append(f"despertar ±{round(wake_sd)} min")
    reg_str = f" · Regularidad: {', '.join(reg_parts)}" if reg_parts else ""
    awake_str = f" · Desvelo medio: {avg_awake} min" if avg_awake is not None else ""
    lines.append(
        f"\n**Media:** {avg_sleep} · Score medio: {avg_score}{reg_str}{awake_str}\n\n"
        "_La regularidad (cuánto varían tus horarios) influye en la salud tanto como las "
        "horas dormidas: cuanto menor la dispersión, mejor._\n\n"
    )

    # --- FC reposo + HRV ---
    lines += [
        "## FC reposo + HRV nocturno\n\n",
        f"| {'Día':<{len(day_col_width)}} | FC reposo | HRV (RMSSD aprox.) |\n",
        f"|{day_col_width}|---------:|-------------------:|\n",
    ]
    total_hr = 0
    total_hrv = 0.0
    hr_count = 0
    hrv_count = 0
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        n = sleep_by_date.get(d.isoformat())
        if n:
            lines.append(
                f"| {label} | {fmt_val(n.rhr, ' bpm')} | {fmt_val(n.hrv, ' ms') if n.hrv else '–'} |\n"
            )
            if n.rhr:
                total_hr += n.rhr
                hr_count += 1
            if n.hrv:
                total_hrv += n.hrv
                hrv_count += 1
        else:
            lines.append(f"| {label} | – | – |\n")

    avg_hr = f"{round(total_hr / hr_count)} bpm" if hr_count else "–"
    avg_hrv = f"{round(total_hrv / hrv_count)} ms" if hrv_count else "–"
    status_raw = next((n.hrv_status for n in reversed(present) if n.hrv_status), None)
    status_str = f" · Estado HRV: {HRV_STATUS_ES.get(status_raw, status_raw.lower())}" if status_raw else ""
    lines.append(f"\n**Media:** {avg_hr} · HRV medio: {avg_hrv}{status_str}\n\n")

    # --- Respiración y SpO2 nocturnos ---
    lines += [
        "## Respiración y SpO2 nocturnos\n\n",
        f"| {'Día':<{len(day_col_width)}} | SpO2 media | SpO2 mín | Resp. media |\n",
        f"|{day_col_width}|----------:|--------:|-----------:|\n",
    ]
    spo2_avgs, spo2_mins, resp_avgs = [], [], []
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        n = sleep_by_date.get(d.isoformat())
        if n and (n.spo2_avg is not None or n.resp_avg is not None):
            spo2_avg = f"{round(n.spo2_avg)}%" if n.spo2_avg is not None else "–"
            spo2_min = f"{n.spo2_min}%" if n.spo2_min is not None else "–"
            resp = f"{n.resp_avg:.0f}" if n.resp_avg is not None else "–"
            lines.append(f"| {label} | {spo2_avg} | {spo2_min} | {resp} |\n")
            if n.spo2_avg is not None:
                spo2_avgs.append(n.spo2_avg)
            if n.spo2_min is not None:
                spo2_mins.append(n.spo2_min)
            if n.resp_avg is not None:
                resp_avgs.append(n.resp_avg)
        else:
            lines.append(f"| {label} | – | – | – |\n")

    mean_spo2 = f"{round(statistics.mean(spo2_avgs))}%" if spo2_avgs else "–"
    week_min_spo2 = f"{min(spo2_mins)}%" if spo2_mins else "–"
    mean_resp = f"{round(statistics.mean(resp_avgs))} resp/min" if resp_avgs else "–"
    lines.append(
        f"\n**Media SpO2:** {mean_spo2} · **Mínimo de la semana:** {week_min_spo2}"
        f" · **Respiración media:** {mean_resp}\n\n"
        "_Medidas ópticas de muñeca: orientativas, no de uso médico. Caídas mantenidas de "
        "SpO2 nocturna pueden ser señal de cribado (p. ej. apnea); no son un diagnóstico._\n\n"
    )

    # --- Estrés y Body Battery ---
    lines += [
        "## Estrés y Body Battery\n\n",
        f"| {'Día':<{len(day_col_width)}} | Estrés medio | BB max | BB min |\n",
        f"|{day_col_width}|------------:|-------:|-------:|\n",
    ]
    total_stress = 0.0
    stress_count = 0
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        d_str = d.isoformat()
        stress = stress_map.get(d_str)
        bb = bb_map.get(d_str)
        lines.append(
            f"| {label} | {fmt_val(stress) if stress is not None else '–'}"
            f" | {fmt_val(bb[0]) if bb else '–'}"
            f" | {fmt_val(bb[1]) if bb else '–'} |\n"
        )
        if stress is not None:
            total_stress += stress
            stress_count += 1

    avg_stress = round(total_stress / stress_count) if stress_count else "–"
    last_bb_min = None
    for i in range(num_days - 1, -1, -1):
        d_str = (start + timedelta(days=i)).isoformat()
        if d_str in bb_map:
            last_bb_min = bb_map[d_str][1]
            break
    lines.append(
        f"\n**Media estrés:** {avg_stress} · BB cierre periodo: {fmt_val(last_bb_min)}\n\n"
    )

    # --- Actividad ---
    lines += [
        "## Actividad\n\n",
        f"| {'Día':<{len(day_col_width)}} | Sesiones | FC media | Intens. | BB Δ | Pasos |\n",
        f"|{day_col_width}|----------|--------:|-------:|-----:|------:|\n",
    ]
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        d_str = d.isoformat()
        acts = activity_map.get(d_str, [])
        steps = steps_map.get(d_str)
        im = intensity_map.get(d_str)

        if acts:
            parts = []
            total_bb = 0
            hrs = []
            for atype, mins, hr, bb in acts:
                name = ACTIVITY_LABELS.get(atype, atype.replace("_", " "))
                parts.append(f"{name} {int(mins) if mins else '?'}min")
                if bb is not None:
                    total_bb += bb
                if hr:
                    hrs.append(hr)
            session_str = " · ".join(parts)
            hr_str = f"{round(sum(hrs)/len(hrs))} bpm" if hrs else "–"
            bb_str = f"{total_bb:+d}" if total_bb else "–"
        else:
            session_str = "descanso"
            hr_str = "–"
            bb_str = "–"

        im_str = f"{im[0]} min" if im and im[0] else "–"
        steps_str = f"{int(steps):,}".replace(",", ".") if steps else "–"
        lines.append(f"| {label} | {session_str} | {hr_str} | {im_str} | {bb_str} | {steps_str} |\n")

    # Total de intensidad del periodo frente a la guía OMS
    if intensity_map:
        tot = sum(v[0] for v in intensity_map.values() if v[0] is not None)
        modt = sum(v[1] for v in intensity_map.values() if v[1] is not None)
        vigt = sum(v[2] for v in intensity_map.values() if v[2] is not None)
        extra = f" (~{round(tot / num_days * 7)} min/sem)" if multi_week else ""
        lines.append(
            f"\n**Intensidad:** {tot} min equivalentes (moderada {modt} + vigorosa {vigt}×2)"
            f"{extra} · objetivo OMS {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX} min/sem.\n"
        )

    # --- Forma física: VO2máx y ritmos previstos ---
    lines.append("\n## Forma física\n\n")
    if vo2max:
        run_v, cyc_v, vo2_date = vo2max
        parts = []
        if run_v is not None:
            parts.append(f"**{round(run_v)}** (carrera)")
        if cyc_v is not None:
            parts.append(f"**{round(cyc_v)}** (bici)")
        fecha = f" · actualizado {vo2_date}" if vo2_date else ""
        lines.append(
            f"- **VO2máx:** {' · '.join(parts)} ml/kg/min{fecha} — es el predictor de "
            "longevidad más potente; vigila la tendencia, no el valor absoluto.\n"
        )
    else:
        lines.append(
            "- **VO2máx:** sin datos. El FR165 lo estima a partir de **carreras o caminatas "
            "al aire libre con GPS** (y ciclismo con potenciómetro). Las sesiones indoor, en "
            "cinta o de natación no generan estimación: haz alguna salida al aire libre para "
            "activarlo.\n"
        )
    if race_pred:
        rp_date, t5, t10, thalf, tmar = race_pred
        lines.append(
            f"- **Ritmos previstos** (estimación de Garmin según tu forma, a {rp_date}): "
            f"5K {fmt_hms(t5)} · 10K {fmt_hms(t10)} · media {fmt_hms(thalf)} · "
            f"maratón {fmt_hms(tmar)}\n"
        )

    return "".join(lines)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-sync", action="store_true", help="No llama a garmin extract (BD ya actualizada)")
    parser.add_argument("--inspect-schema", action="store_true", help="Muestra las tablas y columnas de la BD y sale")
    parser.add_argument("--start-date", metavar="YYYY-MM-DD", help="Fecha de inicio del informe (por defecto: lunes de la semana pasada)")
    parser.add_argument("--end-date", metavar="YYYY-MM-DD", help="Fecha de fin del informe (por defecto: domingo de la semana pasada, o hoy si se usa --start-date)")
    args = parser.parse_args()

    if not args.no_sync:
        print("Sincronizando con Garmin Connect...")
        sync()

    if not DB_PATH.exists():
        print(f"[ERROR] BD no encontrada: {DB_PATH}", file=sys.stderr)
        print("Autentica primero con: .venv/bin/garmin auth", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    if args.inspect_schema:
        inspect_schema(conn)
        conn.close()
        return

    if args.start_date:
        start = parse_date(args.start_date)
        end = parse_date(args.end_date) if args.end_date else date.today() - timedelta(days=1)
    else:
        start, end = last_week_range()

    print(f"Generando informe: {start} – {end} ({(end - start).days + 1} días)")

    # Offset UTC→local para que las agregaciones por día (y las horas de sueño)
    # usen la fecha local, no la UTC en que Garmin guarda los timeseries.
    tz_min = tz_offset_minutes(conn)

    sleep_rows = query_sleep(conn, start, end)
    stress_map = query_stress(conn, start, end, tz_min)
    bb_map = query_body_battery(conn, start, end, tz_min)
    activity_map = query_activities(conn, start, end, tz_min)
    steps_map = query_steps(conn, start, end, tz_min)
    intensity_map = query_intensity(conn, start, end)
    vo2max = query_vo2max(conn, end)
    race_pred = query_race_predictions(conn)

    # Tendencias: una semana se compara con las ~4 previas; un periodo largo se
    # trocea en sus semanas ISO y se compara la última con la media de las anteriores.
    multi_week = (end - start).days + 1 > 7
    weekly = None
    if multi_week:
        weeks_meta = iso_weeks_in_range(start, end)
        weekly = [
            {"wk_label": f"W{wknum}",
             "range_label": f"{ws.day} {MONTHS_ES[ws.month]}–{we.day} {MONTHS_ES[we.month]}",
             "stats": metric_stats(conn, ws, we, tz_min)}
            for wknum, ws, we in weeks_meta
        ]
        cur_stats = weekly[-1]["stats"]
        last_week_start = weeks_meta[-1][1]
        base_stats = metric_stats(conn, start, last_week_start - timedelta(days=1), tz_min)
    else:
        cur_stats = metric_stats(conn, start, end, tz_min)
        b_start, b_end = baseline_range(start, BASELINE_WEEKS)
        base_stats = metric_stats(conn, b_start, b_end, tz_min)
    conn.close()

    flags = compute_flags(sleep_rows, cur_stats, base_stats)

    if not sleep_rows and not stress_map and not bb_map:
        print("[AVISO] No hay datos para ese rango de fechas. ¿Se completó la sincronización?")

    md = generate_md(
        sleep_rows, stress_map, bb_map, activity_map, steps_map, intensity_map,
        vo2max, race_pred, start, end, cur_stats, base_stats, flags, BASELINE_WEEKS, weekly,
    )
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"Informe guardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
