#!/usr/bin/env python3
"""
Genera un informe en markdown con datos de salud de Garmin Connect.

Flujo: garmin extract (incremental) → SQLite local → output/garmin_log_<inicio>_<fin>.md

Uso:
  python generate_report.py                                    # última semana ISO + sync
  python generate_report.py --no-sync                         # última semana, sin sync
  python generate_report.py --start-date 2026-05-28           # desde fecha hasta hoy
  python generate_report.py --start-date 2026-05-01 --end-date 2026-05-31
  python generate_report.py --demo                            # ejemplo con datos sintéticos
  python generate_report.py --inspect-schema                  # lista tablas y columnas
"""

import argparse
import math
import shutil
import sqlite3
import statistics
import subprocess
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

import demo_data
import render_html

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "garmin_data.db"
OUTPUT_DIR = PROJECT_DIR / "output"
VENV_BIN = PROJECT_DIR / ".venv" / "bin" / "garmin"

# Semanas previas usadas como media de referencia para las tendencias
BASELINE_WEEKS = 4

DAYS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "es": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
}

MONTHS_SHORT = {
    "en": ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
}

# Abreviado en tablas y etiquetas, entero en el titular: ahí sobra sitio.
MONTHS_LONG = {
    "en": ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "es": ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
           "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}

ACTIVITY_LABELS = {
    "en": {
        "indoor_cycling":      "indoor bike",
        "cycling":             "cycling",
        "road_biking":         "road cycling",
        "treadmill_running":   "treadmill",
        "running":             "running",
        "trail_running":       "trail run",
        "lap_swimming":        "swimming",
        "open_water_swimming": "OW swimming",
        "strength_training":   "gym",
        "fitness_equipment":   "gym",
        "elliptical":          "elliptical",
        "yoga":                "yoga",
        "breathwork":          "breathwork",
        "walking":             "walking",
        "hiking":              "hiking",
    },
    "es": {
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
}

# Guía de actividad de la OMS (minutos de intensidad equivalentes/semana).
# Garmin cuenta el minuto vigoroso doble, igual que la OMS.
INTENSITY_TARGET_MIN = 150
INTENSITY_TARGET_MAX = 300

# Estado de HRV nocturno (Garmin) → etiqueta legible
HRV_STATUS_MAP = {
    "en": {
        "BALANCED": "balanced",
        "UNBALANCED": "unbalanced",
        "LOW": "low",
        "POOR": "poor",
        "NONE": "no data",
    },
    "es": {
        "BALANCED": "equilibrado",
        "UNBALANCED": "desequilibrado",
        "LOW": "bajo",
        "POOR": "malo",
        "NONE": "sin datos",
    }
}

# Fila de sueño con acceso por nombre (evita errores de índice al ampliar columnas).
SleepNight = namedtuple("SleepNight", [
    "calendar_date", "start_ts", "end_ts",
    "sleep_s", "deep_s", "light_s", "rem_s", "awake_s",
    "score", "hrv", "hrv_status", "rhr",
    "spo2_avg", "spo2_min", "resp_avg",
    "nap_s", "awake_count", "restless", "sleep_stress", "bb_change",
    "need_actual", "need_baseline", "breathing_severity",
])
# Los campos de contexto son opcionales: no todos los relojes los rellenan.
SleepNight.__new__.__defaults__ = (None,) * 20

# Etiqueta de esfuerzo de la sesión (training_effect_label de Garmin)
TE_LABELS_MAP = {
    "en": {
        "RECOVERY": "recovery", "BASE": "base", "AEROBIC_BASE": "aerobic base",
        "TEMPO": "tempo", "THRESHOLD": "threshold", "VO2MAX": "VO2max",
        "SPEED": "speed", "ANAEROBIC_CAPACITY": "anaerobic cap.",
        "SPRINT": "sprint", "UNKNOWN": "–",
    },
    "es": {
        "RECOVERY": "recuperación", "BASE": "base", "AEROBIC_BASE": "base aeróbica",
        "TEMPO": "tempo", "THRESHOLD": "umbral", "VO2MAX": "VO2máx",
        "SPEED": "velocidad", "ANAEROBIC_CAPACITY": "cap. anaeróbica",
        "SPRINT": "sprint", "UNKNOWN": "–",
    }
}


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
    if not ts or offset_hours is None:
        return ts
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return ts  # timestamp con formato inesperado: mejor crudo que reventar el informe
    return (dt + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M:%S")


def fmt_clock(ts) -> str:
    """'2026-06-15 23:12:00' → '23:12'; '–' si no hay dato."""
    return str(ts)[11:16] if ts and len(str(ts)) >= 16 else "–"


def fmt_hms(seconds) -> str:
    """Segundos → 'h:mm:ss' o 'mm:ss' (predicciones de carrera)."""
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(meters_per_sec, sport: str) -> str:
    """Ritmo formateado según el deporte.

    - Carrera / caminar: '5:23/km' (minutos:segundos por km).
    - Ciclismo: '26.4 km/h' (velocidad, no ritmo).
    - Natación: '2:10/100m' (ritmo por 100 m).
    - Deportes sin distancia/ritmo útil (gym, pádel): '–'. Ahí la distancia es
      deambular por la pista, y enseñar min/km es ruido.

    Se compara por subcadena, no por lista cerrada: Garmin inventa variantes sin
    parar (road_biking, gravel_cycling, obstacle_run...) y una lista exacta las
    deja a todas en '–'.
    """
    if not meters_per_sec or meters_per_sec <= 0:
        return "–"
    if "swim" in sport:
        sec_per_100m = 100.0 / meters_per_sec
        return f"{int(sec_per_100m // 60)}:{int(round(sec_per_100m % 60)):02d}/100m"
    if "cycl" in sport or "bik" in sport:
        return f"{meters_per_sec * 3.6:.1f} km/h"
    if any(s in sport for s in ("run", "walk", "hik")):
        sec_per_km = 1000.0 / meters_per_sec
        return f"{int(sec_per_km // 60)}:{int(round(sec_per_km % 60)):02d}/km"
    return "–"


def fmt_zones(z: list) -> str:
    """Reparto porcentual del tiempo en zonas 1-5 de FC: '8/23/36/26/6'."""
    vals = [v or 0 for v in z]
    total = sum(vals)
    if not total:
        return "–"
    return "/".join(str(round(v / total * 100)) for v in vals)


def sport_extras(a: dict) -> str:
    """Métricas propias del deporte, compactadas en una celda."""
    p = []
    if a.get("avg_running_cadence"):
        p.append(f"cad {round(a['avg_running_cadence'])} ppm")
    if a.get("avg_stride_length"):
        p.append(f"zancada {a['avg_stride_length'] / 100:.2f} m")
    if a.get("avg_ground_contact_time"):
        p.append(f"GCT {round(a['avg_ground_contact_time'])} ms")
    if a.get("avg_vertical_ratio"):
        p.append(f"ratio vert. {a['avg_vertical_ratio']:.1f}%")
    elif a.get("avg_vertical_oscillation"):
        p.append(f"osc. vert. {a['avg_vertical_oscillation']:.1f} cm")
    if a.get("avg_ground_contact_balance"):
        p.append(f"apoyo {a['avg_ground_contact_balance']:.1f}% I")
    if a.get("decoupling") is not None:
        p.append(f"deriva {a['decoupling']:+.1f}%")
    if a.get("hrr_60"):
        p.append(f"HRR60 {round(a['hrr_60'])} bpm")
    if a.get("avg_power") or a.get("cycling_power"):
        p.append(f"pot. {round(a.get('avg_power') or a.get('cycling_power'))} W")
    if a.get("elevation_gain"):
        p.append(f"D+ {round(a['elevation_gain'])} m")
    if a.get("avg_swolf"):
        p.append(f"SWOLF {round(a['avg_swolf'])}")
    if a.get("active_lengths"):
        p.append(f"{a['active_lengths']} largos de {round((a.get('pool_length') or 0) / 100)} m")
    if a.get("strokes"):
        p.append(f"{round(a['strokes'])} brazadas")
    if a.get("avg_biking_cadence"):
        p.append(f"cad {round(a['avg_biking_cadence'])} rpm")
    return " · ".join(p) if p else "–"


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


def compute_sri(nights: list) -> int | None:
    """Índice de Regularidad del Sueño (SRI, Sleep Regularity Index).

    Calcula la probabilidad (escalada de 0 a 100) de que un individuo esté en el
    mismo estado (dormido vs despierto) en dos momentos separados por exactamente
    24 horas (Phillips et al., 2017; Windred et al., 2024).

    SRI = -100 (inversión total día/noche), 0 (azar), 100 (rutina idéntica).
    """
    if not nights or len(nights) < 2:
        return None

    intervals = []
    for n in nights:
        if n and n.start_ts and n.end_ts:
            try:
                s = datetime.fromisoformat(str(n.start_ts))
                e = datetime.fromisoformat(str(n.end_ts))
                if s < e:
                    intervals.append((s, e))
            except (ValueError, TypeError):
                continue

    if len(intervals) < 2:
        return None

    intervals.sort(key=lambda x: x[0])
    first_date = intervals[0][0].date()
    last_date = intervals[-1][1].date()
    first_dt = datetime(first_date.year, first_date.month, first_date.day, 18, 0, 0)
    if intervals[0][0] < first_dt:
        first_dt -= timedelta(days=1)
    last_dt = datetime(last_date.year, last_date.month, last_date.day, 18, 0, 0)

    total_days = (last_dt - first_dt).days
    if total_days < 2:
        return None

    def is_asleep(dt: datetime) -> bool:
        return any(start <= dt < end for start, end in intervals)

    EPOCH_MINUTES = 5
    concordance = 0
    total_samples = 0

    curr = first_dt
    end_eval = last_dt - timedelta(days=1)
    while curr < end_eval:
        s1 = is_asleep(curr)
        s2 = is_asleep(curr + timedelta(days=1))
        concordance += 1 if (s1 == s2) else -1
        total_samples += 1
        curr += timedelta(minutes=EPOCH_MINUTES)

    if not total_samples:
        return None

    sri_val = round((concordance / total_samples) * 100)
    return max(0, min(100, sri_val))


def compute_social_jetlag(nights: list) -> int | None:
    """Calcula el Jetlag Social en minutos.

    Diferencia absoluta entre el punto medio del sueño en días libres/fin de semana
    (viernes-noche y sábado-noche) y días laborables (domingo a jueves noche) (Roenneberg et al., 2019).
    """
    if not nights or len(nights) < 3:
        return None

    workday_mids = []
    weekend_mids = []

    for n in nights:
        if not n or not n.start_ts or not n.end_ts:
            continue
        try:
            s = datetime.fromisoformat(str(n.start_ts))
            e = datetime.fromisoformat(str(n.end_ts))
            midpoint = s + (e - s) / 2
            mid_minutes = midpoint.hour * 60 + midpoint.minute
            if mid_minutes < 12 * 60:
                mid_minutes += 24 * 60

            night_day = (s - timedelta(days=1)).date() if s.hour < 12 else s.date()
            if night_day.weekday() in (4, 5):
                weekend_mids.append(mid_minutes)
            else:
                workday_mids.append(mid_minutes)
        except (ValueError, TypeError):
            continue

    if not workday_mids or not weekend_mids:
        return None

    avg_work = statistics.mean(workday_mids)
    avg_free = statistics.mean(weekend_mids)
    return round(abs(avg_free - avg_work))


def compute_hrv_stability(cur_hrv_list: list[float], base_hrv_list: list[float]) -> dict:
    """Evalúa la estabilidad autonómica semanal de HRV y calcula la banda SWC individual.

    - Coeficiente de variación (CV de lnRMSSD): CV = (SD / Media) * 100 (Plews et al., 2012).
    - Banda SWC (Smallest Worthwhile Change): Media_base ± 0.75 * SD_base (Buchheit, 2014; Plews et al., 2013).
      Aplica un margen fisiológico proporcional (mínimo ~8% de la media o 4.5 ms) para que el
      pasillo de referencia sea representativo y no colapse en periodos con baja desviación.
    """
    valid_cur = [float(v) for v in cur_hrv_list if v and v > 0]
    valid_base = [float(v) for v in base_hrv_list if v and v > 0]

    res = {
        "cv": None,
        "swc_low": None,
        "swc_high": None,
        "status": "unknown"
    }

    if len(valid_cur) >= 3:
        ln_cur = [math.log(v) for v in valid_cur]
        mean_ln = statistics.mean(ln_cur)
        sd_ln = statistics.stdev(ln_cur)
        if mean_ln > 0:
            res["cv"] = round((sd_ln / mean_ln) * 100, 1)

    if len(valid_base) >= 5:
        base_mean = statistics.mean(valid_base)
        base_sd = statistics.stdev(valid_base)
        swc_margin = max(0.75 * base_sd, base_mean * 0.08, 4.5)
        res["swc_low"] = round(base_mean - swc_margin, 1)
        res["swc_high"] = round(base_mean + swc_margin, 1)

        if valid_cur:
            cur_mean = statistics.mean(valid_cur)
            if cur_mean < res["swc_low"]:
                res["status"] = "low"
            elif cur_mean > res["swc_high"]:
                res["status"] = "high"
            else:
                res["status"] = "balanced"

    return res


# La carga crónica es una ventana de 4 semanas: por debajo de eso el cociente
# ACWR compara la semana contra sí misma y no dice nada.
ACWR_MIN_DAYS = 28
NO_ACWR = {"acute": None, "chronic": None, "acwr": None, "status": ""}


def compute_acwr_ewma(daily_loads: list[float], acute_days: int = 7, chronic_days: int = 28) -> dict:
    """Calcula la Carga Aguda:Crónica (ACWR) mediante Media Móvil Ponderada Exponencialmente (EWMA).

    Williams et al. (2017) & Gabbett (2016):
    lambda_a = 2 / (acute_days + 1)
    EWMA_today = Load_today * lambda + EWMA_yesterday * (1 - lambda)
    """
    if not daily_loads or len(daily_loads) < 7:
        return dict(NO_ACWR)

    lambda_a = 2.0 / (acute_days + 1.0)
    lambda_c = 2.0 / (chronic_days + 1.0)

    acute = float(daily_loads[0])
    chronic = float(daily_loads[0])

    for load in daily_loads[1:]:
        l = float(load or 0.0)
        acute = l * lambda_a + acute * (1.0 - lambda_a)
        chronic = l * lambda_c + chronic * (1.0 - lambda_c)

    if chronic <= 0:
        return dict(NO_ACWR, acute=round(acute, 1), chronic=0.0)

    acwr = round(acute / chronic, 2)
    if acwr > 1.50:
        status = "danger"
    elif acwr > 1.30:
        status = "overload"
    elif acwr >= 0.80:
        status = "optimal"
    else:
        status = "undertraining"

    return {"acute": round(acute, 1), "chronic": round(chronic, 1), "acwr": acwr, "status": status}


def compute_aerobic_decoupling(laps: list[dict]) -> tuple[float | None, float | None]:
    """Calcula el Desacoplamiento Aeróbico (Pa:HR / Pw:HR) y Factor de Eficiencia (EF).

    Compara el Factor de Eficiencia (Velocidad / FC o Potencia / FC) entre la primera
    y la segunda mitad de la sesión (Friel, 2018).
    """
    if not laps or len(laps) < 2:
        return None, None

    valid_laps = []
    for l in laps:
        spd = l.get("enhanced_avg_speed") or (
            (l.get("total_distance") / l.get("total_timer_time"))
            if (l.get("total_distance") and l.get("total_timer_time")) else None
        )
        pwr = l.get("avg_power")
        hr = l.get("avg_heart_rate")
        dur = l.get("total_timer_time") or l.get("total_elapsed_time") or 1.0
        output = pwr if pwr else (spd * 1000.0 if spd else None)
        if output and hr and hr > 40:
            valid_laps.append({"output": output, "hr": hr, "dur": dur})

    if len(valid_laps) < 2:
        return None, None

    mid = len(valid_laps) // 2
    laps_1 = valid_laps[:mid]
    laps_2 = valid_laps[mid:]

    def calc_ef(lap_subset):
        tot_dur = sum(l["dur"] for l in lap_subset)
        if not tot_dur:
            return None
        weighted_out = sum(l["output"] * l["dur"] for l in lap_subset) / tot_dur
        weighted_hr = sum(l["hr"] * l["dur"] for l in lap_subset) / tot_dur
        return weighted_out / weighted_hr if weighted_hr > 0 else None

    ef1 = calc_ef(laps_1)
    ef2 = calc_ef(laps_2)

    if not ef1 or not ef2 or ef1 <= 0:
        return (round(ef1, 2) if ef1 else None), None

    decoupling_pct = round(((ef1 - ef2) / ef1) * 100.0, 1)
    return round(ef1, 2), decoupling_pct


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

def garmin_bin() -> str | None:
    """Ejecutable de garmin-health-data: el del venv del proyecto, o el del PATH
    para quien lo haya instalado con pipx o a nivel de sistema."""
    return str(VENV_BIN) if VENV_BIN.exists() else shutil.which("garmin")


def sync(start: date | None = None, end: date | None = None):
    binary = garmin_bin()
    if not binary:
        print(f"[ERROR] No se encuentra el ejecutable `garmin` (ni en {VENV_BIN} ni en el PATH)", file=sys.stderr)
        print("Ejecuta: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    cmd = [binary, "extract"]
    if start:
        # Sin rango, `garmin extract` solo trae lo nuevo desde el último dato de la
        # BD: pedir un informe antiguo daría un informe vacío.
        cmd += ["--start-date", start.isoformat()]
        if end:
            # Garmin guarda la noche con la fecha del despertar, así que el sueño
            # del último día del informe vive en `end + 1`. --end-date es exclusivo
            # → +2 días. Nunca más allá de mañana: el futuro no tiene datos.
            hasta = max(start, min(end + timedelta(days=2), date.today() + timedelta(days=1)))
            cmd += ["--end-date", hasta.isoformat()]

    result = subprocess.run(
        cmd,
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
            timezone_offset_hours,
            nap_time_seconds,
            awake_count,
            restless_moments_count,
            avg_sleep_stress,
            body_battery_change,
            sleep_need_actual,
            sleep_need_baseline,
            breathing_disruption_severity
        FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
        ORDER BY calendar_date
    """, (range_start, range_end))
    nights = []
    for r in cur.fetchall():
        tz = r[15]  # timezone_offset_hours: start_ts/end_ts → hora local
        nights.append(SleepNight(r[0], to_local(r[1], tz), to_local(r[2], tz), *r[3:15], *r[16:]))
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


def query_acwr(conn: sqlite3.Connection, end: date) -> dict:
    """Calcula ACWR a partir de la tabla training_load (nativa o calculada EWMA)."""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT daily_training_load_acute, daily_training_load_chronic, daily_acute_chronic_workload_ratio
            FROM training_load
            WHERE date <= ? AND daily_acute_chronic_workload_ratio IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """, (end.isoformat(),))
        row = cur.fetchone()
        if row and row[2] is not None:
            acwr_val = round(float(row[2]), 2)
            status = "danger" if acwr_val > 1.5 else ("overload" if acwr_val > 1.3 else ("optimal" if acwr_val >= 0.8 else "undertraining"))
            return {
                "acute": round(float(row[0]), 1) if row[0] is not None else None,
                "chronic": round(float(row[1]), 1) if row[1] is not None else None,
                "acwr": acwr_val,
                "status": status,
            }
    except sqlite3.Error:
        pass

    start_hist = end - timedelta(days=60)
    try:
        cur.execute("""
            SELECT date, total_intensity_minutes FROM training_load
            WHERE date >= ? AND date <= ? ORDER BY date
        """, (start_hist.isoformat(), end.isoformat()))
        history = {str(r[0]): r[1] for r in cur.fetchall()}
    except sqlite3.Error:
        history = {}

    if not history:
        return dict(NO_ACWR)

    # El histórico empieza donde hay dato, no 60 días atrás: rellenar con carga 0
    # los días previos a la primera sincronización hunde la carga crónica y
    # dispara falsos "pico de carga agudo" a todo el que lleve poco con el reloj.
    # Dentro del tramo con datos, un hueco sí es un día de descanso (carga 0).
    first = date.fromisoformat(min(history))
    if (end - first).days + 1 < ACWR_MIN_DAYS:
        return dict(NO_ACWR)

    days_seq = [first + timedelta(days=i) for i in range((end - first).days + 1)]
    loads = [float(history.get(d.isoformat(), 0) or 0) for d in days_seq]
    return compute_acwr_ewma(loads)


def query_activity_detail(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> list:
    """Una fila por sesión con todo lo que Garmin guarda de ella.

    Las métricas específicas de deporte viven en tablas aparte (*_agg_metrics);
    se unen con LEFT JOIN porque cada actividad solo puebla la suya.
    """
    day = local_day("start_ts", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            {day} AS day, a.activity_id, a.activity_type_key, a.duration, a.distance,
            a.average_hr, a.max_hr, a.calories,
            a.aerobic_training_effect, a.anaerobic_training_effect, a.training_effect_label,
            a.hr_time_in_zone_1, a.hr_time_in_zone_2, a.hr_time_in_zone_3,
            a.hr_time_in_zone_4, a.hr_time_in_zone_5,
            a.average_speed, a.max_speed, a.difference_body_battery, a.lap_count,
            r.avg_running_cadence, r.avg_stride_length, r.avg_ground_contact_time,
            r.avg_vertical_oscillation, r.avg_vertical_ratio, r.avg_ground_contact_balance,
            r.avg_power, r.elevation_gain, r.vo2_max_value,
            s.avg_swolf, s.strokes, s.active_lengths, s.pool_length,
            c.avg_biking_cadence, c.avg_power AS cycling_power
        FROM activity a
        LEFT JOIN running_agg_metrics  r ON r.activity_id = a.activity_id
        LEFT JOIN swimming_agg_metrics s ON s.activity_id = a.activity_id
        LEFT JOIN cycling_agg_metrics  c ON c.activity_id = a.activity_id
        WHERE {day} >= ? AND {day} <= ?
          AND a.parent = 0
          AND a.activity_type_key != 'breathwork'
        ORDER BY a.start_ts
    """, (start.isoformat(), end.isoformat()))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def add_min_hr(conn: sqlite3.Connection, act_id: int, start_ts: str, laps: list):
    """Añade min_heart_rate a cada vuelta.

    Garmin no guarda la FC mínima por vuelta (solo media y máxima), así que se
    saca de la serie a 1 Hz. Los límites de cada vuelta salen de acumular
    total_elapsed_time desde el inicio: es tiempo de pared e incluye las pausas,
    a diferencia de total_timer_time.
    """
    rows = conn.execute("""
        SELECT timestamp, value FROM activity_ts_metric
        WHERE activity_id = ? AND name = 'heart_rate' ORDER BY timestamp
    """, (act_id,)).fetchall()
    if not rows:
        return
    t0 = datetime.fromisoformat(start_ts)
    series = [((datetime.fromisoformat(ts) - t0).total_seconds(), v)
              for ts, v in rows if v]
    offset = 0.0
    for lap in laps:
        lap_end = offset + (lap.get("total_elapsed_time") or 0)
        vals = [v for t, v in series if offset <= t < lap_end]
        lap["min_heart_rate"] = min(vals) if vals else None
        offset = lap_end


def query_laps(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    """Devuelve {activity_id: [{métrica: valor}, ...]} para sesiones con ≥2 vueltas.

    activity_lap_metric guarda una fila por (vuelta, métrica); aquí se pivota a
    un dict por vuelta y se filtran las métricas que caben en la tabla.
    """
    day = local_day("a.start_ts", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT l.activity_id, a.start_ts, l.lap_idx, l.name, l.value
        FROM activity_lap_metric l
        JOIN activity a ON a.activity_id = l.activity_id
        WHERE {day} >= ? AND {day} <= ?
          AND l.name IN ('total_timer_time', 'total_elapsed_time', 'total_distance',
                         'enhanced_avg_speed', 'avg_heart_rate', 'max_heart_rate',
                         'avg_running_cadence', 'total_ascent', 'total_descent')
        ORDER BY l.activity_id, l.lap_idx
    """, (start.isoformat(), end.isoformat()))
    by_activity: dict = {}
    starts: dict = {}
    for act_id, start_ts, lap_idx, name, value in cur.fetchall():
        by_activity.setdefault(act_id, {}).setdefault(lap_idx, {})[name] = value
        starts[act_id] = start_ts
    # Una sola vuelta = la sesión entera; ya está en la tabla de detalle.
    result = {aid: [laps[i] for i in sorted(laps)]
              for aid, laps in by_activity.items() if len(laps) > 1}
    for aid, laps in result.items():
        add_min_hr(conn, aid, starts[aid], laps)
    return result


def query_floors(conn: sqlite3.Connection, start: date, end: date, tz_min: int) -> dict:
    """Devuelve {fecha_str: pisos_subidos} por día."""
    day = local_day("timestamp", tz_min)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {day} AS day, SUM(ascended) AS up
        FROM floors
        WHERE {day} >= ? AND {day} <= ? AND ascended > 0
        GROUP BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: row[1] for row in cur.fetchall()}


def query_records(conn: sqlite3.Connection, start: date, end: date) -> list:
    """Récords personales conseguidos dentro del periodo."""
    cur = conn.cursor()
    cur.execute("""
        SELECT label, value, date(timestamp) FROM personal_record
        WHERE date(timestamp) >= ? AND date(timestamp) <= ?
          AND label NOT LIKE '%Unknown%'
        ORDER BY timestamp
    """, (start.isoformat(), end.isoformat()))
    return cur.fetchall()


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

    # SpO2 y respiración nocturnas
    cur.execute("""
        SELECT AVG(average_spo2), AVG(average_respiration) FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
    """, (s1, e1))
    spo2, resp_avg = cur.fetchone()

    # Minutos de intensidad equivalentes, normalizados a semana
    cur.execute("""
        SELECT SUM(total_intensity_minutes), COUNT(*) FROM training_load
        WHERE date >= ? AND date <= ?
    """, (start.isoformat(), end.isoformat()))
    im_sum, im_days = cur.fetchone()
    intensity_week = (im_sum / im_days * 7) if im_sum is not None and im_days else None

    # Regularidad del sueño (SRI, jetlag social y dispersión horaria)
    sleep_rows = query_sleep(conn, start, end)
    sri = compute_sri(sleep_rows)
    social_jetlag = compute_social_jetlag(sleep_rows)
    bed_sd, wake_sd = regularity_over_period(conn, start, end)

    # Estabilidad autonómica de HRV (CV de lnRMSSD y SWC contra 4 semanas previas)
    cur_hrvs = [n.hrv for n in sleep_rows if n.hrv]
    b_start, b_end = baseline_range(start, BASELINE_WEEKS)
    base_sleep_rows = query_sleep(conn, b_start, b_end)
    base_hrvs = [n.hrv for n in base_sleep_rows if n.hrv]
    hrv_stab = compute_hrv_stability(cur_hrvs, base_hrvs)

    # Carga de entrenamiento ACWR con EWMA
    acwr_info = query_acwr(conn, end)

    vo2 = query_vo2max(conn, end)

    return {
        "sleep_s": sleep_s, "score": score, "rhr": rhr, "hrv": hrv,
        "stress": stress, "steps": steps, "n_nights": n_nights or 0,
        "spo2": spo2, "resp_avg": resp_avg, "intensity_week": intensity_week,
        "bed_sd": bed_sd, "wake_sd": wake_sd,
        "sri": sri, "social_jetlag": social_jetlag,
        "hrv_cv": hrv_stab.get("cv"),
        "hrv_swc_low": hrv_stab.get("swc_low"),
        "hrv_swc_high": hrv_stab.get("swc_high"),
        "hrv_status_stab": hrv_stab.get("status"),
        "acwr": acwr_info.get("acwr"),
        "acute_load": acwr_info.get("acute"),
        "chronic_load": acwr_info.get("chronic"),
        "acwr_status": acwr_info.get("status"),
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


def compute_flags(sleep_rows: list, cur_stats: dict, base_stats: dict, act_detail: list | None = None, lang: str = "en") -> list[str]:
    """Reglas simples sobre los datos para resaltar lo que merece atención.

    sleep_rows: lista de SleepNight del periodo, ordenadas por fecha.
    """
    flags: list[str] = []
    have_base = base_stats.get("n_nights", 0) >= 5
    is_es = lang == "es"

    # 1. FC reposo elevada varios días seguidos respecto a la media (umbral +5 bpm)
    if have_base and base_stats.get("rhr"):
        thr = base_stats["rhr"] + 5
        run = best = 0
        for row in sleep_rows:
            if row.rhr and row.rhr >= thr:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best >= 3:
            if is_es:
                flags.append(
                    f"⚠️ FC reposo elevada {best} días seguidos respecto a tu media "
                    f"({round(base_stats['rhr'])} bpm) — posible fatiga, estrés o estar incubando algo."
                )
            else:
                flags.append(
                    f"⚠️ Resting HR elevated for {best} consecutive days compared to your baseline "
                    f"({round(base_stats['rhr'])} bpm) — possible fatigue, stress, or brewing illness."
                )

    # 2. HRV nocturno desviado de la media o bajo la banda SWC
    if have_base and base_stats.get("hrv") and cur_stats.get("hrv"):
        ratio = cur_stats["hrv"] / base_stats["hrv"]
        if ratio <= 0.90 or (cur_stats.get("hrv_swc_low") and cur_stats["hrv"] < cur_stats["hrv_swc_low"]):
            if is_es:
                swc_str = f" (fuera de tu banda normal {round(cur_stats['hrv_swc_low'])}–{round(cur_stats['hrv_swc_high'])} ms)" if cur_stats.get("hrv_swc_low") else ""
                flags.append(
                    f"⚠️ HRV nocturno un {round((1 - ratio) * 100)}% por debajo de tu media{swc_str} "
                    "— señal de carga/estrés; prioriza descanso."
                )
            else:
                swc_str = f" (outside your normal range {round(cur_stats['hrv_swc_low'])}–{round(cur_stats['hrv_swc_high'])} ms)" if cur_stats.get("hrv_swc_low") else ""
                flags.append(
                    f"⚠️ Overnight HRV is {round((1 - ratio) * 100)}% below your baseline{swc_str} "
                    "— signal of autonomic load/stress; prioritize recovery."
                )
        elif ratio >= 1.10:
            flags.append("✅ HRV nocturno por encima de tu media — buena recuperación." if is_es
                         else "✅ Overnight HRV above baseline — good recovery.")

    # 3. Estabilidad de HRV (CV elevado -> inestabilidad autonómica)
    hrv_cv = cur_stats.get("hrv_cv")
    if hrv_cv is not None and hrv_cv > 10.5:
        flags.append(
            f"⚠️ Inestabilidad autonómica (CV de HRV {hrv_cv:.1f}%) — oscilaciones nocturnas elevadas asociadas a fatiga acumulada."
            if is_es else
            f"⚠️ Autonomic instability (HRV CV {hrv_cv:.1f}%) — high overnight fluctuations associated with accumulated fatigue."
        )

    # 4. Noches cortas
    short = sum(1 for r in sleep_rows if r.sleep_s and r.sleep_s < 6 * 3600)
    if short >= 2:
        flags.append(f"⚠️ {short} noches por debajo de 6 h de sueño." if is_es
                     else f"⚠️ {short} nights with under 6 h of sleep.")

    # 5. Regularidad del sueño (SRI y dispersión de horarios)
    sri = cur_stats.get("sri")
    bed_sd = cur_stats.get("bed_sd")
    sjl = cur_stats.get("social_jetlag")
    if sri is not None and sri < 68:
        if is_es:
            sjl_str = f", jetlag social {sjl} min" if sjl else ""
            flags.append(
                f"⚠️ Regularidad de sueño baja (SRI {sri}/100{sjl_str}): horarios variables que desincronizan el "
                "ritmo circadiano — la regularidad influye en la longevidad tanto como la duración."
            )
        else:
            sjl_str = f", social jetlag {sjl} min" if sjl else ""
            flags.append(
                f"⚠️ Low sleep regularity (SRI {sri}/100{sjl_str}): irregular bed/wake times disrupt circadian rhythm "
                "— consistency influences longevity as much as duration."
            )
    elif bed_sd is not None and bed_sd > 60:
        flags.append(
            f"⚠️ Horario de sueño irregular: la hora de acostarte varía ±{round(bed_sd)} min esta semana — la regularidad pesa tanto como la duración."
            if is_es else
            f"⚠️ Irregular sleep schedule: bedtime varies by ±{round(bed_sd)} min this week — consistency matters as much as duration."
        )

    # 6. Estrés medio elevado respecto a la media (+8)
    if have_base and base_stats.get("stress") and cur_stats.get("stress"):
        if cur_stats["stress"] >= base_stats["stress"] + 8:
            flags.append(
                f"⚠️ Estrés medio elevado ({round(cur_stats['stress'])}) frente a tu media ({round(base_stats['stress'])})."
                if is_es else
                f"⚠️ High average daily stress ({round(cur_stats['stress'])}) compared to your baseline ({round(base_stats['stress'])})."
            )

    # 7. Carga de entrenamiento (ACWR con EWMA)
    acwr = cur_stats.get("acwr")
    if acwr is not None:
        if acwr > 1.50:
            flags.append(
                f"⚠️ Pico de carga agudo (ACWR {acwr:.2f}): incremento >50% respecto a tu preparación crónica — riesgo elevado de sobrecarga lesiva."
                if is_es else
                f"⚠️ Acute training load spike (ACWR {acwr:.2f}): >50% increase over chronic preparation — elevated injury risk."
            )
        elif acwr > 1.30:
            flags.append(
                f"ℹ️ Sobrecarga progresiva alta (ACWR {acwr:.2f}): carga exigente en el límite superior seguro."
                if is_es else
                f"ℹ️ High progressive overload (ACWR {acwr:.2f}): demanding training load at the upper safe threshold."
            )
        elif 0.80 <= acwr <= 1.30 and (cur_stats.get("intensity_week") or 0) >= INTENSITY_TARGET_MIN:
            flags.append(
                f"✅ Carga de entrenamiento en rango óptimo (ACWR {acwr:.2f}) — estímulo progresivo y seguro."
                if is_es else
                f"✅ Training load in optimal range (ACWR {acwr:.2f}) — progressive and safe stimulus."
            )

    # 8. Minutos de intensidad frente a la guía OMS (150–300 equivalentes/semana)
    im = cur_stats.get("intensity_week")
    if im is not None:
        if im < INTENSITY_TARGET_MIN:
            flags.append(
                f"⚠️ Actividad por debajo de la recomendación: {round(im)} min de intensidad esta semana (objetivo {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
                if is_es else
                f"⚠️ Physical activity below recommendation: {round(im)} intensity min this week (goal {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
            )
        elif im <= INTENSITY_TARGET_MAX:
            flags.append(
                f"✅ Actividad en rango saludable: {round(im)} min de intensidad (objetivo {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
                if is_es else
                f"✅ Physical activity in healthy range: {round(im)} intensity min (goal {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})."
            )

    # 9. SpO2 nocturna MEDIA baja varias noches (cribado, no diagnóstico).
    # Usamos la media, no el mínimo: caídas puntuales a 85-89% son normales en
    # gente sana; lo relevante es una saturación media sostenidamente baja.
    low_spo2 = sum(1 for n in sleep_rows if n.spo2_avg is not None and n.spo2_avg < 92)
    if low_spo2 >= 3:
        flags.append(
            f"⚠️ SpO2 nocturna media por debajo de 92% en {low_spo2} noches — señal de cribado (p. ej. apnea del sueño); no es un diagnóstico, coméntalo con un profesional."
            if is_es else
            f"⚠️ Average overnight SpO2 below 92% across {low_spo2} nights — indicative screening signal (e.g. sleep apnea); consult a physician."
        )

    # 10. Desviación de frecuencia respiratoria nocturna (alerta precoz de infección / estrés)
    if have_base and base_stats.get("resp_avg") and cur_stats.get("resp_avg"):
        if cur_stats["resp_avg"] >= base_stats["resp_avg"] + 1.0:
            delta = cur_stats["resp_avg"] - base_stats["resp_avg"]
            flags.append(
                f"⚠️ Frecuencia respiratoria nocturna elevada (+{delta:.1f} resp/min sobre tu media de {round(base_stats['resp_avg'], 1)}) — posible señal de infección, estrés o inflamación."
                if is_es else
                f"⚠️ Elevated overnight respiration (+{delta:.1f} br/min over baseline {round(base_stats['resp_avg'], 1)}) — possible respiratory infection, stress, or inflammation."
            )

    # 11. Desacoplamiento aeróbico y asimetría biomecánica en sesiones
    act_labels = ACTIVITY_LABELS.get(lang, ACTIVITY_LABELS["en"])
    if act_detail:
        for a in act_detail:
            dec = a.get("decoupling")
            if dec is not None and dec > 7.5 and (a.get("duration") or 0) >= 1500:
                name = act_labels.get(a.get("activity_type_key", ""), a.get("activity_type_key", "session"))
                flags.append(
                    f"⚠️ Desacoplamiento aeróbico elevado (+{dec:.1f}%) en {name} ({a.get('day', '')}) — deriva cardíaca atribuible a fatiga aeróbica, calor o deshidratación."
                    if is_es else
                    f"⚠️ High aerobic decoupling (+{dec:.1f}%) in {name} ({a.get('day', '')}) — cardiac drift attributable to aerobic fatigue, heat, or dehydration."
                )
                break
        for a in act_detail:
            bal = a.get("avg_ground_contact_balance")
            if bal is not None and abs(bal - 50.0) >= 1.6:
                if is_es:
                    side = "izquierda" if bal > 50.0 else "derecha"
                    flags.append(
                        f"⚠️ Asimetría de apoyo en carrera ({bal:.1f}% I / {100-bal:.1f}% D) en {a.get('day', '')} — vigila posibles sobrecargas en pierna {side}."
                    )
                else:
                    side = "left" if bal > 50.0 else "right"
                    flags.append(
                        f"⚠️ Running ground contact asymmetry ({bal:.1f}% L / {100-bal:.1f}% R) on {a.get('day', '')} — watch for potential overload on {side} leg."
                    )
                break

    # 12. VO2máx ausente: recordatorio de cómo activarlo
    if cur_stats.get("vo2max") is None:
        flags.append(
            "ℹ️ Sin VO2máx (el predictor de longevidad más potente): el FR165 lo estima con carreras o caminatas al aire libre con GPS; las sesiones indoor, en cinta o de natación no lo generan."
            if is_es else
            "ℹ️ No VO2max estimate (the strongest single predictor of longevity): the watch estimates it from outdoor GPS runs or walks; indoor/treadmill sessions do not trigger it."
        )

    # Señal positiva global (solo si no hay avisos)
    if (cur_stats.get("sleep_s") and cur_stats["sleep_s"] >= 7.5 * 3600
            and cur_stats.get("score") and cur_stats["score"] >= 85
            and not any(f.startswith("⚠️") for f in flags)):
        flags.append("✅ Buena semana de sueño y recuperación." if is_es else "✅ Great week of sleep and recovery.")

    if not flags:
        flags.append("ℹ️ Sin señales destacables: semana dentro de tus rangos habituales." if is_es
                     else "ℹ️ No noteworthy flags: week within your usual ranges.")
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


def _sum_dur(v):
    return fmt_duration(round(v)) if v else "–"


def _sum_num(v, unit=""):
    return f"{round(v)}{unit}" if v is not None else "–"


def _sum_steps(v):
    return f"{int(round(v)):,}".replace(",", ".") if v else "–"


def _sum_reg(v):
    return f"±{round(v)} min" if v is not None else "–"


def get_summary_specs(lang: str = "en") -> list[tuple]:
    """Métricas del Resumen: (etiqueta, clave en metric_stats, formateador, unidad,
    es_duración, dirección buena). Única fuente para las tres variantes de tabla
    (semanal, sin histórico, multi-semana) y para las tarjetas del HTML.

    La dirección no se puede deducir del signo de la tendencia: subir es malo en FC
    en reposo y bueno en VO2máx. None = ni bueno ni malo por sí solo.
    """
    if lang == "es":
        return [
            ("Sueño",                   "sleep_s",        _sum_dur,                       "",     True,  "up"),
            ("Regularidad (SRI)",       "sri",            lambda v: _sum_num(v, "/100"),  "/100", False, "up"),
            ("Score sueño",             "score",          _sum_num,                       "",     False, "up"),
            ("FC reposo",               "rhr",            lambda v: _sum_num(v, " bpm"),  " bpm", False, "down"),
            ("HRV nocturno",            "hrv",            lambda v: _sum_num(v, " ms"),   " ms",  False, "up"),
            ("Estabilidad HRV",         "hrv_cv",         lambda v: f"{v:.1f}%" if v is not None else "–", "%", False, "down"),
            ("Carga (ACWR)",            "acwr",           lambda v: f"{v:.2f}" if v is not None else "–",  "", False, None),
            ("VO2máx",                  "vo2max",         _sum_num,                       "",     False, "up"),
            ("Estrés medio",            "stress",         _sum_num,                       "",     False, "down"),
            ("Pasos/día",               "steps",          _sum_steps,                     "",     False, "up"),
            ("Min. intensidad/sem",     "intensity_week", lambda v: _sum_num(v, " min"),  " min", False, None),
        ]
    return [
        ("Sleep",                   "sleep_s",        _sum_dur,                       "",     True,  "up"),
        ("Regularity (SRI)",        "sri",            lambda v: _sum_num(v, "/100"),  "/100", False, "up"),
        ("Sleep Score",             "score",          _sum_num,                       "",     False, "up"),
        ("Resting HR",              "rhr",            lambda v: _sum_num(v, " bpm"),  " bpm", False, "down"),
        ("Overnight HRV",           "hrv",            lambda v: _sum_num(v, " ms"),   " ms",  False, "up"),
        ("HRV Stability",           "hrv_cv",         lambda v: f"{v:.1f}%" if v is not None else "–", "%", False, "down"),
        ("Training Load (ACWR)",    "acwr",           lambda v: f"{v:.2f}" if v is not None else "–",  "", False, None),
        ("VO2max",                  "vo2max",         _sum_num,                       "",     False, "up"),
        ("Avg. Stress",             "stress",         _sum_num,                       "",     False, "down"),
        ("Daily Steps",             "steps",          _sum_steps,                     "",     False, "up"),
        ("Intensity Min/wk",        "intensity_week", lambda v: _sum_num(v, " min"),  " min", False, None),
    ]



# Anillos del resumen. Garmin no da una nota de recuperación en la BD, así que
# se estima aquí desde cuánto se desvían HRV y FC en reposo de TU media, con la
# HRV pesando más (es la señal autonómica que antes se mueve). Los coeficientes
# son una calibración, no una ley: RECOVERY_CENTER es la nota de una semana
# idéntica a tu media, y las ganancias, cuántos puntos cuesta desviarse.
RECOVERY_CENTER = 65
RECOVERY_HRV_GAIN = 250   # puntos por cada 100 % de desviación de la HRV
RECOVERY_RHR_GAIN = 8     # puntos por cada bpm sobre tu media
SLEEP_TARGET_S = 8 * 3600


def _clamp100(v: float) -> float:
    return min(100.0, max(0.0, v))


def recovery_score(cur_stats: dict, base_stats: dict) -> float | None:
    """Nota 0–100 de recuperación. None si no hay histórico con el que comparar.

    Cada componente se acota a 0–100 antes de mezclarse: una HRV disparada no
    debe compensar una FC en reposo por las nubes.
    """
    if base_stats.get("n_nights", 0) < 5:
        return None
    parts = []
    if cur_stats.get("hrv") and base_stats.get("hrv"):
        dev = cur_stats["hrv"] / base_stats["hrv"] - 1
        parts.append((0.6, _clamp100(RECOVERY_CENTER + dev * RECOVERY_HRV_GAIN)))
    if cur_stats.get("rhr") and base_stats.get("rhr"):
        dev = cur_stats["rhr"] - base_stats["rhr"]
        parts.append((0.4, _clamp100(RECOVERY_CENTER - dev * RECOVERY_RHR_GAIN)))
    if not parts:
        return None
    return sum(w * v for w, v in parts) / sum(w for w, _ in parts)


def compute_health_traffic_light(cur_stats: dict, base_stats: dict, flags: list[str],
                                 sleep_rows: list | None = None, lang: str = "en") -> dict:
    """Calcula el estado global (Semáforo de Salud) y 3 frases de diagnóstico en lenguaje natural."""
    warn_count = sum(1 for f in flags if f.startswith("⚠️"))
    rec = recovery_score(cur_stats, base_stats)
    sleep_s = cur_stats.get("sleep_s")
    rhr_cur, rhr_base = cur_stats.get("rhr"), base_stats.get("rhr")
    hrv_cur, hrv_base = cur_stats.get("hrv"), base_stats.get("hrv")
    stress_cur = cur_stats.get("stress")
    sri = cur_stats.get("sri")
    acwr = cur_stats.get("acwr")
    is_es = lang == "es"

    # 1. Determinación del estado global
    if (warn_count >= 3
        or (rec is not None and rec < 40)
        or (rhr_base and rhr_cur and rhr_cur >= rhr_base + 5 and hrv_base and hrv_cur and hrv_cur < hrv_base * 0.85)):
        state = "recovery"
        badge = "🔴"
        title = "Descanso necesario" if is_es else "Recovery Needed"
    elif (warn_count >= 1
          or (rec is not None and rec < 60)
          or (sleep_s is not None and sleep_s < 6.5 * 3600)
          or (stress_cur is not None and stress_cur > 38)
          or (sri is not None and sri < 70)
          or (acwr is not None and (acwr > 1.40 or acwr < 0.70))):
        state = "warning"
        badge = "🟡"
        title = "Atención requerida" if is_es else "Attention Needed"
    else:
        state = "optimal"
        badge = "🟢"
        title = "Estado óptimo" if is_es else "Optimal State"

    # 2. Diagnóstico de Sueño
    if sleep_s:
        dur_str = fmt_duration(round(sleep_s))
        if is_es:
            if sleep_s >= 7.5 * 3600:
                s_lead = f"Excelente duración media de {dur_str} por noche"
            elif sleep_s >= 7.0 * 3600:
                s_lead = f"Duración de sueño adecuada ({dur_str}/noche)"
            elif sleep_s >= 6.0 * 3600:
                s_lead = f"Ligero déficit de sueño ({dur_str}/noche, por debajo del objetivo)"
            else:
                s_lead = f"Déficit severo de sueño acumulado ({dur_str}/noche)"

            if sri is not None:
                if sri >= 80:
                    s_tail = f" con gran regularidad circadiana (SRI {sri}/100)."
                elif sri < 68:
                    s_tail = f" pero con horarios muy irregulares (SRI {sri}/100) que conviene estabilizar."
                else:
                    s_tail = f" y regularidad moderada (SRI {sri}/100)."
            else:
                s_tail = "."
        else:
            if sleep_s >= 7.5 * 3600:
                s_lead = f"Excellent average duration of {dur_str} per night"
            elif sleep_s >= 7.0 * 3600:
                s_lead = f"Adequate sleep duration ({dur_str}/night)"
            elif sleep_s >= 6.0 * 3600:
                s_lead = f"Mild sleep deficit ({dur_str}/night, below target)"
            else:
                s_lead = f"Severe accumulated sleep deficit ({dur_str}/night)"

            if sri is not None:
                if sri >= 80:
                    s_tail = f" with strong circadian regularity (SRI {sri}/100)."
                elif sri < 68:
                    s_tail = f" with irregular sleep timing (SRI {sri}/100) that should be stabilized."
                else:
                    s_tail = f" and moderate regularity (SRI {sri}/100)."
            else:
                s_tail = "."
        sleep_diag = s_lead + s_tail
    else:
        sleep_diag = ("Sin registros suficientes de sueño para evaluar el descanso nocturno."
                      if is_es else "Insufficient sleep records to evaluate nightly rest.")

    # 3. Diagnóstico de Recuperación y Estrés
    rec_parts = []
    if hrv_cur and hrv_base and base_stats.get("n_nights", 0) >= 5:
        pct_diff = round((hrv_cur / hrv_base - 1) * 100)
        if pct_diff >= 5:
            rec_parts.append(
                f"Sistema nervioso autónomo en supercompensación (+{pct_diff}% HRV vs tu media)"
                if is_es else
                f"Autonomic nervous system in supercompensation (+{pct_diff}% HRV vs baseline)"
            )
        elif pct_diff <= -10:
            rec_parts.append(
                f"Sistema nervioso bajo carga (HRV {abs(pct_diff)}% por debajo de tu media)"
                if is_es else
                f"Autonomic nervous system under load (HRV {abs(pct_diff)}% below baseline)"
            )
        else:
            rec_parts.append(
                f"Equilibrio autonómico estable (HRV {round(hrv_cur)} ms, FC reposo {round(rhr_cur) if rhr_cur else '–'} bpm)"
                if is_es else
                f"Stable autonomic balance (HRV {round(hrv_cur)} ms, resting HR {round(rhr_cur) if rhr_cur else '–'} bpm)"
            )
    elif hrv_cur:
        rec_parts.append(
            f"HRV nocturno en {round(hrv_cur)} ms y FC reposo en {round(rhr_cur) if rhr_cur else '–'} bpm"
            if is_es else
            f"Overnight HRV at {round(hrv_cur)} ms and resting HR at {round(rhr_cur) if rhr_cur else '–'} bpm"
        )
    else:
        rec_parts.append("Nivel de recuperación en seguimiento" if is_es else "Recovery level being tracked")

    if stress_cur is not None:
        if is_es:
            if stress_cur >= 38:
                rec_parts.append(f"con estrés diario elevado ({round(stress_cur)}/100).")
            elif stress_cur <= 25:
                rec_parts.append(f"con estrés diario bajo y relajado ({round(stress_cur)}/100).")
            else:
                rec_parts.append(f"con estrés diario moderado ({round(stress_cur)}/100).")
        else:
            if stress_cur >= 38:
                rec_parts.append(f"with high daily stress ({round(stress_cur)}/100).")
            elif stress_cur <= 25:
                rec_parts.append(f"with low and relaxed daily stress ({round(stress_cur)}/100).")
            else:
                rec_parts.append(f"with moderate daily stress ({round(stress_cur)}/100).")
    else:
        rec_parts.append("")
    recovery_diag = " ".join(p for p in rec_parts if p).rstrip(".") + "."

    # 4. Recomendación Práctica
    if state == "optimal":
        recommendation = ("Cuerpo preparado para asimilar entrenamientos de calidad, tiradas largas o progresión de intensidad."
                          if is_es else
                          "Body primed to absorb quality training sessions, long runs, or intensity progression.")
    elif state == "warning":
        if sleep_s and sleep_s < 7 * 3600:
            recommendation = ("Procura acostarte 30-45 min antes hoy y mantén la actividad deportiva en zona aeróbica suave (Zona 2)."
                              if is_es else
                              "Aim to go to bed 30–45 min earlier tonight and keep workouts in easy aerobic zones (Zone 2).")
        elif acwr and acwr > 1.40:
            recommendation = ("Carga acumulada alta: modera el volumen o la intensidad en los próximos días para evitar lesiones."
                              if is_es else
                              "High accumulated load: moderate volume or intensity over the coming days to prevent injury.")
        elif stress_cur and stress_cur > 38:
            recommendation = ("Nivel de estrés fisiológico alto: prioriza paseos ligeros, hidratación y desconexión antes de dormir."
                              if is_es else
                              "High physiological stress: prioritize easy walks, hydration, and winding down before bed.")
        else:
            recommendation = ("Día para trabajo suave o descanso activo; vigila sensaciones antes de subir la exigencia."
                              if is_es else
                              "Good day for light work or active recovery; check feelings before increasing load.")
    else: # recovery
        recommendation = ("Prioriza descanso total o caminata suave. Evita esfuerzos intensos hasta normalizar la FC en reposo y el HRV."
                          if is_es else
                          "Prioritize complete rest or gentle walking. Avoid intense efforts until resting HR and HRV return to baseline.")

    return {
        "state": state,
        "badge": badge,
        "title": title,
        "sleep_diag": sleep_diag,
        "recovery_diag": recovery_diag,
        "recommendation": recommendation,
    }


def _band(value, good, warn) -> str:
    """Estado por umbrales: bueno / a vigilar / malo. Sin dato, no se moja."""
    if value is None:
        return ""
    return "good" if value >= good else "warn" if value >= warn else "bad"


def summary_rings(cur_stats: dict, base_stats: dict, lang: str = "en",
                  goals: dict | None = None) -> list[tuple]:
    """(etiqueta, fracción 0–1, valor, detalle, estado) de fuera a dentro.

    Tres anillos concéntricos con lo que resume una semana: cuánto te has
    movido, cuánto has dormido y cómo has recuperado. Cada fracción es
    "lo logrado / el objetivo", así que el anillo lleno significa lo mismo
    en los tres aunque las unidades no tengan nada que ver.

    Los objetivos de sueño y de minutos de intensidad salen de los Ajustes; los
    umbrales de color (`_band`) no: esos son referencias de salud, no preferencias.
    """
    g = goals or {}
    sleep_target_s = int(float(g.get("sleep_target_hours") or SLEEP_TARGET_S / 3600) * 3600)
    im_goal = int(g.get("intensity_weekly_goal") or INTENSITY_TARGET_MAX)
    im = cur_stats.get("intensity_week")
    sleep_s = cur_stats.get("sleep_s")
    rec = recovery_score(cur_stats, base_stats)
    sleep_h = f"{sleep_target_s / 3600:g}"

    if lang == "es":
        labels = ("Actividad", "Sueño", "Recuperación")
        im_detail = (f"Minutos de intensidad · objetivo {im_goal} min/semana "
                     f"(guía OMS {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})")
        sleep_detail = f"Media por noche · objetivo {sleep_h} h"
        rec_detail = ("Sin histórico suficiente para comparar HRV y FC en reposo" if rec is None
                      else "HRV nocturno y FC en reposo frente a tu media de las semanas anteriores")
    else:
        labels = ("Activity", "Sleep", "Recovery")
        im_detail = (f"Intensity minutes · {im_goal} min/week goal "
                     f"(WHO guidance {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX})")
        sleep_detail = f"Nightly average · {sleep_h} h goal"
        rec_detail = ("Insufficient baseline history to compare HRV and resting HR" if rec is None
                      else "Overnight HRV and resting HR vs. your previous weeks' average")

    return [
        (labels[0],
         (im / im_goal) if im is not None else None,
         f"{round(im)} min" if im is not None else "–",
         im_detail,
         _band(im, INTENSITY_TARGET_MIN, INTENSITY_TARGET_MIN / 2)),
        (labels[1],
         (sleep_s / sleep_target_s) if sleep_s else None,
         _sum_dur(sleep_s),
         sleep_detail,
         _band(sleep_s, 7 * 3600, 6 * 3600)),
        (labels[2],
         (rec / 100) if rec is not None else None,
         f"{round(rec)}" if rec is not None else "–",
         rec_detail,
         _band(rec, 67, 34)),
    ]


# Métricas que ya son el valor de un anillo: en las tarjetas serían la misma
# cifra por segunda vez.
RING_KEYS = {"sleep_s", "intensity_week"}


def summary_tiles(cur_stats: dict, base_stats: dict, lang: str = "en") -> list[tuple]:
    """(etiqueta, valor, tendencia, estado) por métrica, para la cabecera del HTML.

    El estado es "good"/"bad"/"" según si la métrica se ha movido hacia su lado
    bueno; sin histórico con el que comparar, no se moja. Las métricas que se
    leen contra un rango fijo (ACWR, SRI, CV de HRV) sí se pronuncian solas.
    """
    comparable = base_stats.get("n_nights", 0) >= 5
    tiles = []
    specs = get_summary_specs(lang)
    for label, key, fmt, unit, as_dur, good in specs:
        if key in RING_KEYS:
            continue
        cur, base = cur_stats.get(key), base_stats.get(key)
        trend = fmt_trend(cur, base, unit, as_duration=as_dur) if (comparable and base is not None) else ""
        state = ""
        if key == "acwr" and cur is not None:
            if 0.80 <= cur <= 1.30:
                state = "good"
            elif cur > 1.40:
                state = "bad"
        elif key == "sri" and cur is not None:
            if cur >= 80:
                state = "good"
            elif cur < 68:
                state = "bad"
        elif key == "hrv_cv" and cur is not None:
            if cur <= 6.5:
                state = "good"
            elif cur > 10.5:
                state = "bad"
        elif good and comparable and cur is not None and base is not None and cur != base:
            rose = cur > base
            state = "good" if rose == (good == "up") else "bad"
        tiles.append((label, fmt(cur), trend, state))
    return tiles


def weekly_breakdown(weekly: list, base: dict, lang: str = "en") -> list[str]:
    """Tabla de evolución semana a semana (informes multi-semana).

    Una columna por semana ISO del periodo + una columna Tendencia que compara
    la última semana con la media de las anteriores.
    """
    cur = weekly[-1]["stats"]
    heads = " | ".join(w["wk_label"] for w in weekly)
    is_es = lang == "es"
    if is_es:
        out = [
            "_Evolución semana a semana. La **tendencia** compara la última semana con la media de las anteriores._\n\n",
            f"| Métrica | {heads} | Tendencia |\n",
            f"|---------|{'------:|' * len(weekly)}:---------:|\n",
        ]
    else:
        out = [
            "_Week-by-week evolution. The **trend** compares the last week against the average of the previous ones._\n\n",
            f"| Metric | {heads} | Trend |\n",
            f"|---------|{'------:|' * len(weekly)}:---------:|\n",
        ]
    specs = get_summary_specs(lang)
    for label, key, fmt, unit, as_dur, _good in specs:
        cells = " | ".join(fmt(w["stats"].get(key)) for w in weekly)
        trend = fmt_trend(cur.get(key), base.get(key), unit, as_duration=as_dur)
        out.append(f"| {label} | {cells} | {trend} |\n")
    legend = " · ".join(f"{w['wk_label']}: {w['range_label']}" for w in weekly)
    out.append(f"\n_{legend}_\n")
    return out


def title_range(start: date, end: date, lang: str = "en") -> str:
    """Titular del informe: el rango de días, sin repetir lo que no cambia.

    El número de semana ISO es jerga y el resto de la portada ya dice de qué es
    el informe, así que el titular se queda con lo único que lo identifica.
    """
    m_long = MONTHS_LONG.get(lang, MONTHS_LONG["en"])
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {m_long[end.month]} {end.year}"
    if start.year == end.year:
        return f"{start.day} {m_long[start.month]} – {end.day} {m_long[end.month]} {end.year}"
    return f"{start.day} {m_long[start.month]} {start.year} – {end.day} {m_long[end.month]} {end.year}"


def build_summary(cur_stats: dict, base_stats: dict, flags: list[str], weeks: int,
                  multi_week: bool = False, weekly: list | None = None, lang: str = "en") -> list[str]:
    is_es = lang == "es"
    if is_es:
        lines = ["## Resumen\n\n", "### Señales\n\n"]
        lines += [f"- {f}\n" for f in flags]
        lines.append("\n### Métricas\n\n")
        if multi_week and weekly:
            lines += weekly_breakdown(weekly, base_stats, lang=lang)
        elif base_stats.get("n_nights", 0) >= 5:
            lines += [
                f"| Métrica | Esta semana | Tu media (~{weeks} sem) | Tendencia |\n",
                "|---------|------------:|------------------------:|:---------:|\n",
            ]
            for label, key, fmt, unit, as_dur, _good in get_summary_specs(lang):
                trend = fmt_trend(cur_stats.get(key), base_stats.get(key), unit, as_duration=as_dur)
                lines.append(f"| {label} | {fmt(cur_stats.get(key))} | {fmt(base_stats.get(key))} | {trend} |\n")
        else:
            lines += [
                "| Métrica | Esta semana |\n",
                "|---------|------------:|\n",
            ]
            for label, key, fmt, _unit, _as_dur, _good in get_summary_specs(lang):
                lines.append(f"| {label} | {fmt(cur_stats.get(key))} |\n")
            lines.append(
                "\n_Histórico insuficiente para comparar tendencias (se necesitan ~2 semanas"
                " previas). Aparecerá automáticamente cuando haya más datos._\n"
            )
    else:
        lines = ["## Summary\n\n", "### Signals\n\n"]
        lines += [f"- {f}\n" for f in flags]
        lines.append("\n### Metrics\n\n")
        if multi_week and weekly:
            lines += weekly_breakdown(weekly, base_stats, lang=lang)
        elif base_stats.get("n_nights", 0) >= 5:
            lines += [
                f"| Metric | This week | Your baseline (~{weeks} wks) | Trend |\n",
                "|---------|------------:|------------------------:|:---------:|\n",
            ]
            for label, key, fmt, unit, as_dur, _good in get_summary_specs(lang):
                trend = fmt_trend(cur_stats.get(key), base_stats.get(key), unit, as_duration=as_dur)
                lines.append(f"| {label} | {fmt(cur_stats.get(key))} | {fmt(base_stats.get(key))} | {trend} |\n")
        else:
            lines += [
                "| Metric | This week |\n",
                "|---------|------------:|\n",
            ]
            for label, key, fmt, _unit, _as_dur, _good in get_summary_specs(lang):
                lines.append(f"| {label} | {fmt(cur_stats.get(key))} |\n")
            lines.append(
                "\n_Insufficient baseline history to calculate trends (~2 previous weeks needed)."
                " Will appear automatically as more data is recorded._\n"
            )
    lines.append("\n---\n\n")
    return lines


# ---------------------------------------------------------------------------
# Generación del markdown
# ---------------------------------------------------------------------------

def day_label(d: date, multi_week: bool, lang: str = "en") -> str:
    """Etiqueta de fila: 'Mon'/'Lun' para semana, '28 May Wed' para rangos largos."""
    days = DAYS.get(lang, DAYS["en"])
    months = MONTHS_SHORT.get(lang, MONTHS_SHORT["en"])
    if not multi_week:
        return days[d.weekday()]
    return f"{d.day} {months[d.month]} {days[d.weekday()]}"


def generate_md(
    sleep_rows: list,
    stress_map: dict,
    bb_map: dict,
    activity_map: dict,
    steps_map: dict,
    intensity_map: dict,
    floors_map: dict,
    act_detail: list,
    laps_map: dict,
    records: list,
    vo2max,
    race_pred,
    start: date,
    end: date,
    cur_stats: dict,
    base_stats: dict,
    flags: list[str],
    baseline_weeks: int,
    weekly: list | None = None,
    generated_on: date | None = None,
    notice: str = "",
    lang: str = "en",
) -> str:
    num_days = (end - start).days + 1
    multi_week = num_days > 7
    is_es = lang == "es"
    act_labels = ACTIVITY_LABELS.get(lang, ACTIVITY_LABELS["en"])
    te_labels = TE_LABELS_MAP.get(lang, TE_LABELS_MAP["en"])
    hrv_map = HRV_STATUS_MAP.get(lang, HRV_STATUS_MAP["en"])

    # Mapear calendar_date → noche anterior (el día en que el usuario se acostó)
    sleep_by_date = {
        (date.fromisoformat(n.calendar_date) - timedelta(days=1)).isoformat(): n
        for n in sleep_rows
    }

    gen_str = f"Generado el {(generated_on or date.today()).isoformat()} · Garmin Forerunner 165" if is_es \
              else f"Generated on {(generated_on or date.today()).isoformat()} · Garmin Forerunner 165"

    lines = [
        f"# {title_range(start, end, lang=lang)}\n\n",
        f"_{gen_str}_\n\n",
    ]
    if notice:
        lines.append(f"**{notice}**\n\n")
    lines.append("---\n\n")

    lines += build_summary(cur_stats, base_stats, flags, baseline_weeks, multi_week, weekly, lang=lang)

    day_col_width = "------------" if multi_week else "-----"

    # --- Sueño ---
    # La columna de siesta solo aparece si hubo alguna: en semanas sin siestas
    # sería una columna de guiones.
    has_naps = any(n.nap_s for n in sleep_rows)
    if is_es:
        nap_head = " Siesta |" if has_naps else ""
        nap_sep = "------:|" if has_naps else ""
        lines += [
            "## Sueño\n\n",
            f"| {'Día':<{len(day_col_width)}} | Acostarse | Despertar | Horas |{nap_head} Deep | REM | Light | Score |\n",
            f"|{day_col_width}|:--------:|:--------:|------:|{nap_sep}-----:|----:|------:|------:|\n",
        ]
    else:
        nap_head = " Nap |" if has_naps else ""
        nap_sep = "----:|" if has_naps else ""
        lines += [
            "## Sleep\n\n",
            f"| {'Day':<{len(day_col_width)}} | Bedtime | Wake time | Hours |{nap_head} Deep | REM | Light | Score |\n",
            f"|{day_col_width}|:--------:|:--------:|------:|{nap_sep}-----:|----:|------:|------:|\n",
        ]

    total_sleep_s = 0
    total_score = 0
    sleep_count = 0
    score_count = 0
    present = []
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week, lang=lang)
        n = sleep_by_date.get(d.isoformat())
        if n:
            present.append(n)
            nap_cell = f" {fmt_duration(n.nap_s) if n.nap_s else '–'} |" if has_naps else ""
            lines.append(
                f"| {label} | {fmt_clock(n.start_ts)} | {fmt_clock(n.end_ts)}"
                f" | {fmt_duration(n.sleep_s)} |{nap_cell} {fmt_duration(n.deep_s)}"
                f" | {fmt_duration(n.rem_s)} | {fmt_duration(n.light_s)} | {fmt_val(n.score)} |\n"
            )
            if n.sleep_s:
                total_sleep_s += n.sleep_s
                sleep_count += 1
            if n.score:
                total_score += n.score
                score_count += 1
        else:
            empty_nap = " – |" if has_naps else ""
            lines.append(f"| {label} | – | – | – |{empty_nap} – | – | – | – |\n")

    avg_sleep = fmt_duration(total_sleep_s // sleep_count) if sleep_count else "–"
    avg_score = round(total_score / score_count) if score_count else "–"

    # Regularidad (dispersión de las horas de acostarse/despertar) y desvelo medio
    bed_sd = sd_minutes([bed_minutes(n.start_ts) for n in present])
    wake_sd = sd_minutes([wake_minutes(n.end_ts) for n in present])
    awake_vals = [n.awake_s for n in present if n.awake_s is not None]
    avg_awake = round(sum(awake_vals) / len(awake_vals) / 60) if awake_vals else None

    reg_parts = []
    if bed_sd is not None:
        reg_parts.append(f"acostarse ±{round(bed_sd)} min" if is_es else f"bedtime ±{round(bed_sd)} min")
    if wake_sd is not None:
        reg_parts.append(f"despertar ±{round(wake_sd)} min" if is_es else f"wake ±{round(wake_sd)} min")
    reg_str = (f" · Regularidad: {', '.join(reg_parts)}" if is_es else f" · Regularity: {', '.join(reg_parts)}") if reg_parts else ""
    sri_val = cur_stats.get("sri")
    sri_str = f" · SRI: {sri_val}/100" if sri_val is not None else ""
    sjl_val = cur_stats.get("social_jetlag")
    sjl_str = (f" · Jetlag social: {sjl_val} min" if is_es else f" · Social jetlag: {sjl_val} min") if sjl_val is not None else ""
    awake_str = (f" · Desvelo medio: {avg_awake} min" if is_es else f" · Avg awake time: {avg_awake} min") if avg_awake is not None else ""

    if is_es:
        lines.append(f"\n**Media:** {avg_sleep} · Score medio: {avg_score}{sri_str}{sjl_str}{reg_str}{awake_str}\n\n")
    else:
        lines.append(f"\n**Average:** {avg_sleep} · Avg Score: {avg_score}{sri_str}{sjl_str}{reg_str}{awake_str}\n\n")

    # Contexto de la noche: lo que Garmin mide pero no cabe en la tabla.
    def avg_of(field, scale=1):
        vals = [getattr(n, field) for n in present if getattr(n, field) is not None]
        return statistics.mean(vals) * scale if vals else None

    ctx = []
    naps = [n.nap_s for n in present if n.nap_s]
    if naps:
        if is_es:
            ctx.append(f"**Siestas:** {len(naps)} de {len(present)} días, "
                       f"{fmt_duration(round(statistics.mean(naps)))} de media "
                       f"({fmt_duration(sum(naps))} en total)")
        else:
            ctx.append(f"**Naps:** {len(naps)} of {len(present)} days, "
                       f"{fmt_duration(round(statistics.mean(naps)))} avg "
                       f"({fmt_duration(sum(naps))} total)")

    fields_labels = [
        ("awake_count", "Despertares" if is_es else "Awakenings", "/noche" if is_es else "/night"),
        ("sleep_stress", "Estrés durante el sueño" if is_es else "Overnight stress", ""),
        ("bb_change", "Body Battery recuperada" if is_es else "Body Battery recharged", ""),
    ]
    for field, label, unit in fields_labels:
        v = avg_of(field)
        if v is not None:
            sign = "+" if field == "bb_change" else ""
            ctx.append(f"{label}: {sign}{round(v)}{unit}")
    sev = [n.breathing_severity for n in present
           if n.breathing_severity and n.breathing_severity != "NONE"]
    if sev:
        ctx.append(f"Alteraciones respiratorias: {len(sev)} noches" if is_es else f"Breathing disruptions: {len(sev)} nights")
    if ctx:
        lines.append(" · ".join(ctx) + "\n\n")

    if is_es:
        lines.append(
            "_La regularidad circadiana (SRI) y la dispersión horaria influyen en la salud y la "
            "recuperación tanto como las horas dormidas._\n\n"
        )
    else:
        lines.append(
            "_Circadian regularity (SRI) and schedule consistency influence health and "
            "recovery as much as total sleep duration._\n\n"
        )

    # --- FC reposo + HRV ---
    if is_es:
        lines += [
            "## FC reposo + HRV nocturno\n\n",
            f"| {'Día':<{len(day_col_width)}} | FC reposo | HRV (RMSSD aprox.) |\n",
            f"|{day_col_width}|---------:|-------------------:|\n",
        ]
    else:
        lines += [
            "## Resting HR + Overnight HRV\n\n",
            f"| {'Day':<{len(day_col_width)}} | Resting HR | Overnight HRV (approx. RMSSD) |\n",
            f"|{day_col_width}|-----------:|------------------------------:|\n",
        ]
    total_hr = 0
    total_hrv = 0.0
    hr_count = 0
    hrv_count = 0
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week, lang=lang)
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
    status_str = f" · {'Estado HRV' if is_es else 'HRV Status'}: {hrv_map.get(status_raw, status_raw.lower())}" if status_raw else ""
    swc_lo = cur_stats.get("hrv_swc_low")
    swc_hi = cur_stats.get("hrv_swc_high")
    swc_str = f" ({'banda normal' if is_es else 'normal band'} {round(swc_lo)}–{round(swc_hi)} ms)" if (swc_lo and swc_hi) else ""
    cv_val = cur_stats.get("hrv_cv")
    cv_str = f" · CV: {cv_val:.1f}%" if cv_val is not None else ""
    if is_es:
        lines.append(f"\n**Media:** {avg_hr} · HRV medio: {avg_hrv}{swc_str}{cv_str}{status_str}\n\n")
    else:
        lines.append(f"\n**Average:** {avg_hr} · Avg HRV: {avg_hrv}{swc_str}{cv_str}{status_str}\n\n")

    # --- Respiración y SpO2 nocturnos ---
    if is_es:
        lines += [
            "## Respiración y SpO2 nocturnos\n\n",
            f"| {'Día':<{len(day_col_width)}} | SpO2 media | SpO2 mín | Resp. media |\n",
            f"|{day_col_width}|----------:|--------:|-----------:|\n",
        ]
    else:
        lines += [
            "## Overnight Respiration & SpO2\n\n",
            f"| {'Day':<{len(day_col_width)}} | Avg SpO2 | Min SpO2 | Avg Resp |\n",
            f"|{day_col_width}|---------:|---------:|---------:|\n",
        ]
    spo2_avgs, spo2_mins, resp_avgs = [], [], []
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week, lang=lang)
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
    if is_es:
        lines.append(
            f"\n**Media SpO2:** {mean_spo2} · **Mínimo de la semana:** {week_min_spo2}"
            f" · **Respiración media:** {mean_resp}\n\n"
            "_Medidas ópticas de muñeca: orientativas, no de uso médico. Caídas mantenidas de "
            "SpO2 nocturna pueden ser señal de cribado (p. ej. apnea); no son un diagnóstico._\n\n"
        )
    else:
        lines.append(
            f"\n**Avg SpO2:** {mean_spo2} · **Week Minimum:** {week_min_spo2}"
            f" · **Avg Respiration:** {mean_resp}\n\n"
            "_Wrist-optical measurements: indicative, not for medical use. Sustained drops "
            "in overnight SpO2 can serve as a screening signal (e.g. sleep apnea); not a diagnosis._\n\n"
        )

    # --- Estrés y Body Battery ---
    if is_es:
        lines += [
            "## Estrés y Body Battery\n\n",
            f"| {'Día':<{len(day_col_width)}} | Estrés medio | BB max | BB min |\n",
            f"|{day_col_width}|------------:|-------:|-------:|\n",
        ]
    else:
        lines += [
            "## Stress & Body Battery\n\n",
            f"| {'Day':<{len(day_col_width)}} | Avg Stress | BB Max | BB Min |\n",
            f"|{day_col_width}|-----------:|-------:|-------:|\n",
        ]
    total_stress = 0.0
    stress_count = 0
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week, lang=lang)
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
    if is_es:
        lines.append(f"\n**Media estrés:** {avg_stress} · BB cierre periodo: {fmt_val(last_bb_min)}\n\n")
    else:
        lines.append(f"\n**Avg Stress:** {avg_stress} · Period Closing BB: {fmt_val(last_bb_min)}\n\n")

    # --- Actividad ---
    if is_es:
        lines += [
            "## Actividad\n\n",
            f"| {'Día':<{len(day_col_width)}} | Sesiones | FC media | Intens. | BB Δ | Pasos | Pisos |\n",
            f"|{day_col_width}|----------|--------:|-------:|-----:|------:|------:|\n",
        ]
    else:
        lines += [
            "## Activity\n\n",
            f"| {'Day':<{len(day_col_width)}} | Sessions | Avg HR | Intens. | BB Δ | Steps | Floors |\n",
            f"|{day_col_width}|----------|-------:|-------:|-----:|------:|-------:|\n",
        ]
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week, lang=lang)
        d_str = d.isoformat()
        acts = activity_map.get(d_str, [])
        steps = steps_map.get(d_str)
        im = intensity_map.get(d_str)

        if acts:
            parts = []
            bbs = []
            hrs = []
            for atype, mins, hr, bb in acts:
                name = act_labels.get(atype, atype.replace("_", " "))
                parts.append(f"{name} {int(mins) if mins else '?'}min")
                if bb is not None:
                    bbs.append(bb)
                if hr:
                    hrs.append(hr)
            session_str = " · ".join(parts)
            hr_str = f"{round(sum(hrs)/len(hrs))} bpm" if hrs else "–"
            bb_str = f"{sum(bbs):+d}" if bbs else "–"
        else:
            session_str = "descanso" if is_es else "rest"
            hr_str = "–"
            bb_str = "–"

        im_str = f"{im[0]} min" if im and im[0] else "–"
        steps_str = f"{int(steps):,}".replace(",", ".") if steps else "–"
        floors = floors_map.get(d_str)
        floors_str = f"{round(floors)}" if floors else "–"
        lines.append(
            f"| {label} | {session_str} | {hr_str} | {im_str} | {bb_str} | {steps_str} | {floors_str} |\n"
        )

    # Total de intensidad del periodo frente a la guía OMS
    if intensity_map:
        tot = sum(v[0] for v in intensity_map.values() if v[0] is not None)
        modt = sum(v[1] for v in intensity_map.values() if v[1] is not None)
        vigt = sum(v[2] for v in intensity_map.values() if v[2] is not None)
        if is_es:
            extra = f" (~{round(tot / num_days * 7)} min/sem)" if multi_week else ""
            lines.append(
                f"\n**Intensidad:** {tot} min equivalentes (moderada {modt} + vigorosa {vigt}×2)"
                f"{extra} · objetivo OMS {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX} min/sem.\n"
            )
        else:
            extra = f" (~{round(tot / num_days * 7)} min/wk)" if multi_week else ""
            lines.append(
                f"\n**Intensity:** {tot} equivalent min (moderate {modt} + vigorous {vigt}×2)"
                f"{extra} · WHO goal {INTENSITY_TARGET_MIN}–{INTENSITY_TARGET_MAX} min/wk.\n"
            )

    # --- Detalle por sesión ---
    if act_detail:
        if is_es:
            lines += [
                "\n### Detalle de sesiones\n\n",
                "| Día | Sesión | Dur | Distancia | Ritmo | FC med/máx | Zonas 1-5 | Efecto aer/ana | kcal | BB Δ | Específicas |\n",
                "|-----|--------|----:|----------:|------:|-----------:|:---------:|:--------------:|-----:|-----:|-------------|\n",
            ]
        else:
            lines += [
                "\n### Session Breakdown\n\n",
                "| Day | Session | Dur | Distance | Pace | Avg/Max HR | Zones 1-5 | Aer/Ana Effect | kcal | BB Δ | Specifics |\n",
                "|-----|---------|----:|---------:|-----:|-----------:|:---------:|:--------------:|-----:|-----:|----------:|\n",
            ]
        for a in act_detail:
            d = date.fromisoformat(a["day"])
            name = act_labels.get(a["activity_type_key"], a["activity_type_key"].replace("_", " "))
            dist = f"{a['distance'] / 1000:.2f} km" if a["distance"] else "–"
            hr = (f"{round(a['average_hr'])}/{round(a['max_hr'])}"
                  if a["average_hr"] and a["max_hr"] else "–")
            zones = fmt_zones([a[f"hr_time_in_zone_{i}"] for i in range(1, 6)])
            te_lbl = te_labels.get(a["training_effect_label"], "")
            te = (f"{a['aerobic_training_effect']:.1f}/{a['anaerobic_training_effect']:.1f}"
                  f"{f' · {te_lbl}' if te_lbl and te_lbl != '–' else ''}"
                  if a["aerobic_training_effect"] is not None else "–")
            lines.append(
                f"| {day_label(d, multi_week, lang=lang)} | {name} | {fmt_duration(round(a['duration'] or 0))}"
                f" | {dist} | {fmt_pace(a['average_speed'], a['activity_type_key'])}"
                f" | {hr} | {zones} | {te} | {fmt_val(a['calories'], fallback='–')}"
                f" | {a['difference_body_battery'] if a['difference_body_battery'] is not None else '–'}"
                f" | {sport_extras(a)} |\n"
            )
        if is_es:
            lines.append(
                "\n_Zonas 1-5: reparto porcentual del tiempo en cada zona de FC. "
                "Efecto aer/ana: escala 0–5 de Garmin (aeróbico / anaeróbico) — por encima "
                "de 3 la sesión mejora la forma, por debajo de 2 la mantiene._\n"
            )
        else:
            lines.append(
                "\n_Zones 1-5: time percentage split across heart rate zones. "
                "Aer/ana effect: Garmin 0–5 scale (aerobic / anaerobic) — above "
                "3.0 improves fitness, below 2.0 maintains it._\n"
            )

    # --- Vueltas / Laps ---
    if laps_map:
        lines.append("\n### Vueltas\n" if is_es else "\n### Laps / Splits\n")
        for a in act_detail:
            laps = laps_map.get(a["activity_id"])
            if not laps:
                continue
            d = date.fromisoformat(a["day"])
            name = act_labels.get(a["activity_type_key"], a["activity_type_key"].replace("_", " "))
            lap_title = f"{len(laps)} vueltas" if is_es else f"{len(laps)} laps"
            if is_es:
                lines += [
                    f"\n**{day_label(d, multi_week, lang=lang)} · {name}** — {lap_title}\n\n",
                    "| # | Tiempo | Distancia | Ritmo | FC mín/med/máx | Cadencia | Vertical |\n",
                    "|--:|-------:|----------:|------:|---------------:|---------:|---------:|\n",
                ]
            else:
                lines += [
                    f"\n**{day_label(d, multi_week, lang=lang)} · {name}** — {lap_title}\n\n",
                    "| # | Time | Distance | Pace | Min/Avg/Max HR | Cadence | Elevation |\n",
                    "|--:|-----:|---------:|-----:|---------------:|--------:|----------:|\n",
                ]
            for i, lap in enumerate(laps, 1):
                dist = lap.get("total_distance")
                hr = [lap.get(k) for k in
                      ("min_heart_rate", "avg_heart_rate", "max_heart_rate")]
                hr_str = "/".join(str(round(v)) if v else "–" for v in hr) \
                    if any(hr) else "–"
                # En las vueltas la cadencia viene en zancadas/min (una pierna).
                cad = lap.get("avg_running_cadence")
                # Garmin da subida y bajada como dos magnitudes positivas. Se
                # muestran ambas: el neto escondería el desnivel de las vueltas
                # onduladas (subir 7 y bajar 10 no es "bajar 3").
                asc, desc = lap.get("total_ascent"), lap.get("total_descent")
                vert = " / ".join(p for p in (f"+{round(asc)}" if asc else "",
                                              f"-{round(desc)}" if desc else "") if p)
                lines.append(
                    f"| {i} | {fmt_hms(lap.get('total_timer_time'))}"
                    f" | {f'{dist / 1000:.2f} km' if dist else '–'}"
                    f" | {fmt_pace(lap.get('enhanced_avg_speed'), a['activity_type_key'])}"
                    f" | {hr_str}"
                    f" | {f'{round(cad * 2)} ppm' if cad else '–'}"
                    f" | {f'{vert} m' if vert else '–'} |\n"
                )

    if records:
        rec_title = "Récords personales en el periodo:" if is_es else "Personal records in period:"
        lines.append(f"\n**{rec_title}** "
                     + " · ".join(f"{lbl} {round(val):,}".replace(",", ".") + f" ({d})"
                                  for lbl, val, d in records) + "\n")

    # --- Forma física: VO2máx y ritmos previstos ---
    lines.append("\n## Forma física\n\n" if is_es else "\n## Fitness\n\n")
    if vo2max:
        run_v, cyc_v, vo2_date = vo2max
        parts = []
        if run_v is not None:
            parts.append(f"**{round(run_v)}** ({'carrera' if is_es else 'running'})")
        if cyc_v is not None:
            parts.append(f"**{round(cyc_v)}** ({'bici' if is_es else 'cycling'})")
        fecha = f" · {'actualizado' if is_es else 'updated'} {vo2_date}" if vo2_date else ""
        if is_es:
            lines.append(
                f"- **VO2máx:** {' · '.join(parts)} ml/kg/min{fecha} — es el predictor de "
                "longevidad más potente; vigila la tendencia, no el valor absoluto.\n"
            )
        else:
            lines.append(
                f"- **VO2max:** {' · '.join(parts)} ml/kg/min{fecha} — the single strongest predictor "
                "of longevity; monitor the trend, not just the absolute number.\n"
            )
    else:
        if is_es:
            lines.append(
                "- **VO2máx:** sin datos. El FR165 lo estima a partir de **carreras o caminatas "
                "al aire libre con GPS** (y ciclismo con potenciómetro). Las sesiones indoor, en "
                "cinta o de natación no generan estimación: haz alguna salida al aire libre para "
                "activarlo.\n"
            )
        else:
            lines.append(
                "- **VO2max:** no data. The watch estimates it from **outdoor GPS runs or walks** "
                "(and cycling with a power meter). Indoor, treadmill or swimming sessions do not generate "
                "an estimate.\n"
            )
    if race_pred:
        rp_date, t5, t10, thalf, tmar = race_pred
        if is_es:
            lines.append(
                f"- **Ritmos previstos** (estimación de Garmin según tu forma, a {rp_date}): "
                f"5K {fmt_hms(t5)} · 10K {fmt_hms(t10)} · media {fmt_hms(thalf)} · "
                f"maratón {fmt_hms(tmar)}\n"
            )
        else:
            lines.append(
                f"- **Predicted race times** (Garmin estimate based on your fitness as of {rp_date}): "
                f"5K {fmt_hms(t5)} · 10K {fmt_hms(t10)} · Half {fmt_hms(thalf)} · "
                f"Marathon {fmt_hms(tmar)}\n"
            )

    return "".join(lines)


def build_report(conn: sqlite3.Connection, start: date, end: date,
                 generated_on: date | None = None, notice: str = "",
                 lang: str = "en", goals: dict | None = None,
                 standalone: bool = True) -> tuple[str, str]:
    """Genera el informe completo a partir de la BD: devuelve (markdown, html).

    `standalone=False` devuelve el HTML como fragmento incrustable (sin <head>
    ni barra propia), que es como lo pide el panel web.
    """
    # Offset UTC→local para que las agregaciones por día (y las horas de sueño)
    # usen la fecha local, no la UTC en que Garmin guarda los timeseries.
    tz_min = tz_offset_minutes(conn)
    is_es = lang == "es"

    sleep_rows = query_sleep(conn, start, end)
    stress_map = query_stress(conn, start, end, tz_min)
    bb_map = query_body_battery(conn, start, end, tz_min)
    activity_map = query_activities(conn, start, end, tz_min)
    steps_map = query_steps(conn, start, end, tz_min)
    intensity_map = query_intensity(conn, start, end)
    floors_map = query_floors(conn, start, end, tz_min)
    act_detail = query_activity_detail(conn, start, end, tz_min)
    laps_map = query_laps(conn, start, end, tz_min)
    records = query_records(conn, start, end)
    vo2max = query_vo2max(conn, end)
    race_pred = query_race_predictions(conn)

    # Tendencias: una semana se compara con las ~4 previas; un periodo largo se
    # trocea en sus semanas ISO y se compara la última con la media de las anteriores.
    multi_week = (end - start).days + 1 > 7
    weekly = None
    m_short = MONTHS_SHORT.get(lang, MONTHS_SHORT["en"])
    if multi_week:
        weeks_meta = iso_weeks_in_range(start, end)
        weekly = [
            {"wk_label": f"W{wknum}",
             "range_label": f"{ws.day} {m_short[ws.month]}–{we.day} {m_short[we.month]}",
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

    for a in act_detail:
        laps = laps_map.get(a["activity_id"])
        if laps and len(laps) >= 2:
            ef, dec = compute_aerobic_decoupling(laps)
            a["ef"] = ef
            a["decoupling"] = dec

    flags = compute_flags(sleep_rows, cur_stats, base_stats, act_detail, lang=lang)

    if not sleep_rows and not stress_map and not bb_map:
        print("[AVISO] No hay datos para ese rango de fechas." if is_es else "[WARNING] No data found for date range.")

    md = generate_md(
        sleep_rows, stress_map, bb_map, activity_map, steps_map, intensity_map,
        floors_map, act_detail, laps_map, records,
        vo2max, race_pred, start, end, cur_stats, base_stats, flags, BASELINE_WEEKS, weekly,
        generated_on, notice, lang=lang,
    )

    traffic_light = compute_health_traffic_light(cur_stats, base_stats, flags, sleep_rows, lang=lang)

    # Las medias del periodo previo son la cruz del mapa de recuperación: sin
    # ellas la gráfica no tiene contra qué comparar y no se dibuja.
    baselines = ({"rhr": base_stats["rhr"], "hrv": base_stats["hrv"],
                  "swc_low": cur_stats.get("hrv_swc_low"), "swc_high": cur_stats.get("hrv_swc_high")}
                 if base_stats.get("n_nights", 0) >= 5 else None)
    return md, render_html.render(md, sleep_rows, stress_map, bb_map, steps_map,
                                  start, end, tiles=summary_tiles(cur_stats, base_stats, lang=lang),
                                  rings=summary_rings(cur_stats, base_stats, lang=lang, goals=goals),
                                  baselines=baselines,
                                  intensity_map=intensity_map,
                                  vo2max=vo2max,
                                  race_pred=race_pred,
                                  traffic_light=traffic_light,
                                  lang=lang,
                                  goals=goals,
                                  standalone=standalone)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="Genera un informe de ejemplo con datos sintéticos / Generates a demo report")
    parser.add_argument("--no-sync", action="store_true", help="No llama a garmin extract (BD ya actualizada) / Skip sync")
    parser.add_argument("--inspect-schema", action="store_true", help="Muestra las tablas y columnas de la BD y sale / Inspect DB schema")
    parser.add_argument("--start-date", metavar="YYYY-MM-DD", help="Fecha de inicio del informe (YYYY-MM-DD) / Start date")
    parser.add_argument("--end-date", metavar="YYYY-MM-DD", help="Fecha de fin del informe (YYYY-MM-DD) / End date")
    parser.add_argument("--lang", choices=["en", "es"], default="en", help="Report language: 'en' (default) or 'es'")
    args = parser.parse_args()

    if args.end_date and not args.start_date:
        parser.error("--end-date requiere --start-date")

    lang = args.lang
    is_es = lang == "es"
    db_path, generated_on = DB_PATH, date.today()
    if args.demo:
        if args.start_date or args.end_date:
            parser.error("--demo trae su propio rango de fechas: no lo combines con --start-date/--end-date")
        db_path = OUTPUT_DIR / "demo.db"
        db_path.parent.mkdir(exist_ok=True)
        db_path.unlink(missing_ok=True)
        print("Construyendo la base de datos de ejemplo (datos sintéticos)..." if is_es
              else "Building synthetic demo database...")
        start, end = demo_data.build(db_path)
        generated_on = demo_data.GENERATED_ON
        args.no_sync = True
    elif args.start_date:
        start = parse_date(args.start_date)
        end = parse_date(args.end_date) if args.end_date else date.today() - timedelta(days=1)
    else:
        start, end = last_week_range()

    if end < start:
        parser.error(f"--end-date ({end}) es anterior a --start-date ({start})")

    if not args.no_sync:
        print(f"Sincronizando con Garmin Connect ({start} – {end})..." if is_es
              else f"Syncing with Garmin Connect ({start} – {end})...")
        sync(start, end)

    if not db_path.exists():
        print(f"[ERROR] BD no encontrada: {db_path}" if is_es else f"[ERROR] DB not found: {db_path}", file=sys.stderr)
        print("Autentica primero con: .venv/bin/garmin auth" if is_es else "Authenticate first with: .venv/bin/garmin auth", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    if args.inspect_schema:
        inspect_schema(conn)
        conn.close()
        return

    print(f"Generando informe: {start} – {end} ({(end - start).days + 1} días)" if is_es
          else f"Generating report: {start} – {end} ({(end - start).days + 1} days)")

    notice = ("Informe de ejemplo con datos sintéticos: no corresponde a ninguna persona real." if is_es
              else "Sample report with synthetic data: does not correspond to any real person.") if args.demo else ""
    md, html = build_report(conn, start, end, generated_on, notice, lang=lang)
    conn.close()

    OUTPUT_DIR.mkdir(exist_ok=True)
    suffix = f"_{lang}" if lang == "es" else ""
    output_path = OUTPUT_DIR / f"garmin_log_{start.isoformat()}_{end.isoformat()}{suffix}.md"
    output_path.write_text(md, encoding="utf-8")
    print(f"Informe guardado en: {output_path}" if is_es else f"Report saved to: {output_path}")

    # Misma información, formato legible por un humano: tablas + gráficas SVG.
    html_path = output_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"Versión HTML en: {html_path}" if is_es else f"HTML report saved to: {html_path}")


if __name__ == "__main__":
    main()

