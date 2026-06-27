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
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "garmin_data.db"
OUTPUT_PATH = PROJECT_DIR / "output" / "garmin_log.md"
VENV_BIN = PROJECT_DIR / ".venv" / "bin" / "garmin"

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
            sleep_time_seconds,
            deep_sleep_seconds,
            light_sleep_seconds,
            rem_sleep_seconds,
            score_overall_value,
            avg_overnight_hrv,
            resting_heart_rate
        FROM sleep
        WHERE calendar_date >= ? AND calendar_date <= ?
        ORDER BY calendar_date
    """, (range_start, range_end))
    return cur.fetchall()


def query_stress(conn: sqlite3.Connection, start: date, end: date) -> dict:
    # value < 0 = sin lectura (-1) o durante actividad (-2)
    cur = conn.cursor()
    cur.execute("""
        SELECT date(timestamp) AS day, ROUND(AVG(value)) AS avg_stress
        FROM stress
        WHERE date(timestamp) >= ? AND date(timestamp) <= ?
          AND value >= 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: row[1] for row in cur.fetchall()}


def query_body_battery(conn: sqlite3.Connection, start: date, end: date) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT date(timestamp) AS day, MAX(value) AS bb_max, MIN(value) AS bb_min
        FROM body_battery
        WHERE date(timestamp) >= ? AND date(timestamp) <= ?
          AND value >= 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def query_activities(conn: sqlite3.Connection, start: date, end: date) -> dict:
    """Devuelve {fecha_str: [(tipo, minutos, avg_hr, bb_delta), ...]} por día."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            date(start_ts) AS day,
            activity_type_key,
            ROUND(duration / 60) AS minutes,
            ROUND(average_hr) AS avg_hr,
            difference_body_battery AS bb_delta
        FROM activity
        WHERE date(start_ts) >= ? AND date(start_ts) <= ?
          AND parent = 0
          AND activity_type_key != 'breathwork'
        ORDER BY start_ts
    """, (start.isoformat(), end.isoformat()))
    result: dict = {}
    for day, atype, mins, hr, bb in cur.fetchall():
        result.setdefault(day, []).append((atype, mins, hr, bb))
    return result


def query_steps(conn: sqlite3.Connection, start: date, end: date) -> dict:
    """Devuelve {fecha_str: total_pasos} por día."""
    cur = conn.cursor()
    cur.execute("""
        SELECT date(timestamp) AS day, SUM(value) AS total
        FROM steps
        WHERE date(timestamp) >= ? AND date(timestamp) <= ?
          AND value > 0
        GROUP BY day
        ORDER BY day
    """, (start.isoformat(), end.isoformat()))
    return {row[0]: row[1] for row in cur.fetchall()}


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
    start: date,
    end: date,
) -> str:
    num_days = (end - start).days + 1
    multi_week = num_days > 7
    # Mapear calendar_date → noche anterior (el día en que el usuario se acostó)
    sleep_by_date = {
        (date.fromisoformat(row[0]) - timedelta(days=1)).isoformat(): row
        for row in sleep_rows
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

    day_col_width = "------------" if multi_week else "-----"

    # --- Sueño ---
    lines += [
        "## Sueño\n\n",
        f"| {'Día':<{len(day_col_width)}} | Horas | Deep | REM | Light | Score |\n",
        f"|{day_col_width}|------:|-----:|----:|------:|------:|\n",
    ]
    total_sleep_s = 0
    total_score = 0
    sleep_count = 0
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        row = sleep_by_date.get(d.isoformat())
        if row:
            _, sleep_s, deep_s, light_s, rem_s, score, _, _ = row
            lines.append(
                f"| {label} | {fmt_duration(sleep_s)} | {fmt_duration(deep_s)}"
                f" | {fmt_duration(rem_s)} | {fmt_duration(light_s)} | {fmt_val(score)} |\n"
            )
            if sleep_s:
                total_sleep_s += sleep_s
                sleep_count += 1
            if score:
                total_score += score
        else:
            lines.append(f"| {label} | – | – | – | – | – |\n")

    avg_sleep = fmt_duration(total_sleep_s // sleep_count) if sleep_count else "–"
    avg_score = round(total_score / sleep_count) if sleep_count else "–"
    lines.append(f"\n**Media:** {avg_sleep} · Score medio: {avg_score}\n\n")

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
        row = sleep_by_date.get(d.isoformat())
        if row:
            _, _, _, _, _, _, hrv, rhr = row
            lines.append(
                f"| {label} | {fmt_val(rhr, ' bpm')} | {fmt_val(hrv, ' ms') if hrv else '–'} |\n"
            )
            if rhr:
                total_hr += rhr
                hr_count += 1
            if hrv:
                total_hrv += hrv
                hrv_count += 1
        else:
            lines.append(f"| {label} | – | – |\n")

    avg_hr = f"{round(total_hr / hr_count)} bpm" if hr_count else "–"
    avg_hrv = f"{round(total_hrv / hrv_count)} ms" if hrv_count else "–"
    lines.append(f"\n**Media:** {avg_hr} · HRV medio: {avg_hrv}\n\n")

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
        f"| {'Día':<{len(day_col_width)}} | Sesiones | FC media | BB Δ | Pasos |\n",
        f"|{day_col_width}|----------|--------:|-----:|------:|\n",
    ]
    for i in range(num_days):
        d = start + timedelta(days=i)
        label = day_label(d, multi_week)
        d_str = d.isoformat()
        acts = activity_map.get(d_str, [])
        steps = steps_map.get(d_str)

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

        steps_str = f"{int(steps):,}".replace(",", ".") if steps else "–"
        lines.append(f"| {label} | {session_str} | {hr_str} | {bb_str} | {steps_str} |\n")

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

    sleep_rows = query_sleep(conn, start, end)
    stress_map = query_stress(conn, start, end)
    bb_map = query_body_battery(conn, start, end)
    activity_map = query_activities(conn, start, end)
    steps_map = query_steps(conn, start, end)
    conn.close()

    if not sleep_rows and not stress_map and not bb_map:
        print("[AVISO] No hay datos para ese rango de fechas. ¿Se completó la sincronización?")

    md = generate_md(sleep_rows, stress_map, bb_map, activity_map, steps_map, start, end)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"Informe guardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
