#!/usr/bin/env python3
"""Base de datos sintética para el modo demo (`generate_report.py --demo`).

Permite ver un informe completo sin cuenta de Garmin ni sincronización: seis
semanas de datos plausibles de una persona que entrena de forma regular, con la
última semana deliberadamente peor (menos sueño, FC en reposo alta, HRV baja,
horarios irregulares) para que las señales automáticas del informe se disparen y
se vea lo que el proyecto realmente hace.

El esquema no se duplica aquí: se crea con los propios modelos de
`garmin-health-data`, así que siempre coincide con lo que escribe `garmin extract`.

Todo es determinista (semilla fija y fechas fijas): la misma llamada produce
siempre el mismo informe, y el ejemplo publicado en `docs/` no cambia solo.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta

USER_ID = 1
TZ_HOURS = 2.0                       # UTC+2, verano peninsular

# Fechas fijas, no `today()`: el informe de ejemplo tiene que ser reproducible.
REPORT_END = date(2026, 6, 21)       # domingo, cierra la semana ISO 2026-W25
REPORT_START = REPORT_END - timedelta(days=6)
FIRST_DAY = REPORT_START - timedelta(days=35)   # + 5 semanas previas de contexto
GENERATED_ON = date(2026, 6, 22)

# Por deporte: fracción del tiempo que cuenta como vigorosa y como moderada
# (Garmin cuenta el minuto vigoroso doble), y pasos por km. Pedalear no da pasos.
EFFORT = {
    "running":           (0.60, 0.40, 900),
    "trail_running":     (0.60, 0.40, 900),
    "cycling":           (0.00, 0.50, 30),
    "strength_training": (0.00, 0.33, 0),
    "walking":           (0.00, 0.30, 1300),
}

# Reparto del tiempo en las 5 zonas de FC y rango de efecto aeróbico. Un mismo
# perfil para todos los deportes delataría al instante que los datos son de
# mentira: correr no reparte el pulso como una sesión de fuerza.
PROFILE = {
    "running":           ([.08, .22, .38, .25, .07], (3.2, 4.2)),
    "trail_running":     ([.10, .25, .35, .23, .07], (3.4, 4.4)),
    "cycling":           ([.15, .40, .32, .11, .02], (2.6, 3.4)),
    "strength_training": ([.35, .40, .20, .05, .00], (1.8, 2.6)),
    "walking":           ([.58, .32, .10, .00, .00], (1.2, 2.0)),
}

# Plan semanal: weekday → [(tipo, minutos, km)]. km = None en sesiones indoor.
WEEK_PLAN = {
    0: [("running", 45, 8.4)],
    2: [("strength_training", 60, None)],
    3: [("cycling", 90, 38.0)],
    5: [("trail_running", 75, 11.2), ("strength_training", 30, None)],
    6: [("walking", 50, 4.2)],
}

# La semana mala cuenta una historia: la FC en reposo sube, se mantiene alta tres
# días (lo que dispara la señal de fatiga) y remite despacio. El HRV hace el
# camino inverso. Explícito y no aleatorio, para que las dos gráficas del informe
# cuenten lo mismo en vez de tres días planos por azar de la semilla.
HARD_RHR = [48, 51, 54, 52, 50, 49, 47]
HARD_HRV_FACTOR = [0.93, 0.85, 0.74, 0.79, 0.87, 0.91, 0.96]
# Desfases de la hora de acostarse en la semana dura (minutos): dispersión
# suficiente para que salte la señal de horario irregular.
HARD_BED_SHIFT = [0, 75, -50, 90, -35, 120, -20]


def _utc(d: date, hour: float) -> str:
    """Hora local del día `d` → timestamp UTC como lo guarda Garmin."""
    local = datetime(d.year, d.month, d.day) + timedelta(hours=hour)
    return (local - timedelta(hours=TZ_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def build(db_path) -> tuple[date, date]:
    """Crea la BD demo en `db_path`. Devuelve el rango del informe."""
    from sqlalchemy import create_engine
    from garmin_health_data.models import Base

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    conn = sqlite3.connect(str(db_path))
    now = datetime(2026, 6, 22, 8, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
    cols_of = {t: {c.name for c in Base.metadata.tables[t].columns}
               for t in Base.metadata.tables}

    def ins(table, **values):
        """INSERT rellenando por su cuenta las marcas de tiempo obligatorias."""
        for stamp in ("create_ts", "update_ts"):
            if stamp in cols_of[table]:
                values.setdefault(stamp, now)
        if "user_id" in cols_of[table]:
            values.setdefault("user_id", USER_ID)
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({','.join(values)}) "
            f"VALUES ({','.join('?' * len(values))})",
            list(values.values()),
        )

    rnd = random.Random(7)
    days = [FIRST_DAY + timedelta(days=i) for i in range((REPORT_END - FIRST_DAY).days + 1)]
    act_id = 9_000_000

    ins("user", full_name="Demo User", birth_date="1988-04-12")
    ins("user_profile", user_profile_id=1, gender="MALE", weight=72000.0, height=178.0,
        vo2_max_running=48.0, latest=1)

    for d in days:
        hard = d >= REPORT_START            # la última semana va peor a propósito
        i = (d - REPORT_START).days

        # --- Sueño (la noche se cuelga del día en que te acuestas) --------------
        bed = 23.2 + (HARD_BED_SHIFT[i] if hard else rnd.uniform(-26, 26)) / 60
        hours = 7.9 + rnd.uniform(-0.4, 0.4)
        if hard and i in (2, 5):
            hours = 5.7 + rnd.uniform(0, 0.3)   # dos noches cortas
        elif hard:
            hours -= 0.5
        sleep_s = int(hours * 3600)
        awake_s = int(rnd.uniform(12, 28) * 60)
        deep_s = int(sleep_s * rnd.uniform(0.19, 0.24))
        rem_s = int(sleep_s * rnd.uniform(0.17, 0.22))
        rhr = HARD_RHR[i] if hard else 46 + rnd.randint(-2, 2)
        hrv = round((62 + rnd.uniform(-3, 3)) * (HARD_HRV_FACTOR[i] if hard else 1.0), 1)
        score = max(45, min(96, int(hours * 9.5 + (0 if hard else 6) + rnd.randint(-4, 4))))

        ins("sleep", sleep_id=int(d.strftime("%Y%m%d")),
            calendar_date=(d + timedelta(days=1)).isoformat(),
            start_ts=_utc(d, bed), end_ts=_utc(d, bed + hours + awake_s / 3600),
            timezone_offset_hours=TZ_HOURS,
            sleep_time_seconds=sleep_s, awake_sleep_seconds=awake_s,
            deep_sleep_seconds=deep_s, rem_sleep_seconds=rem_s,
            light_sleep_seconds=sleep_s - deep_s - rem_s,
            nap_time_seconds=int(rnd.uniform(20, 40) * 60) if d.weekday() == 6 else 0,
            awake_count=rnd.randint(1, 4), restless_moments_count=rnd.randint(20, 55),
            score_overall_value=score, avg_overnight_hrv=hrv,
            hrv_status="UNBALANCED" if hard else "BALANCED",
            resting_heart_rate=rhr,
            average_spo2=round(95.5 + rnd.uniform(-0.8, 0.8), 1),
            lowest_spo2=89 + rnd.randint(0, 3),
            average_respiration=round(13.8 + rnd.uniform(-0.7, 0.7), 1),
            avg_sleep_stress=round((22 if hard else 16) + rnd.uniform(-3, 3), 1),
            body_battery_change=int(hours * 8 + rnd.randint(-5, 5)),
            sleep_need_actual=int(7.8 * 3600), sleep_need_baseline=int(7.6 * 3600),
            breathing_disruption_severity="NONE")

        # --- Actividades del día ------------------------------------------------
        sessions = WEEK_PLAN.get(d.weekday(), [])
        busy = []      # tramos (hora_ini, hora_fin) locales, para el estrés
        day_moderate = day_vigorous = 0
        for n, (kind, minutes, km) in enumerate(sessions):
            # Alguna sesión se cae, como en la vida real. La semana del informe se
            # respeta entera: es la que se enseña con su detalle y sus vueltas.
            if not hard and rnd.random() < 0.12:
                continue
            jitter = rnd.uniform(0.88, 1.12)          # ni el plan más férreo cuadra al minuto
            minutes = int(minutes * jitter)
            km = round(km * jitter, 1) if km else None
            act_id += 1
            begin = 18.0 + n * 1.5
            busy.append((begin, begin + minutes / 60))
            avg_hr = {"running": 152, "trail_running": 145, "cycling": 134,
                      "strength_training": 118, "walking": 96}[kind]
            if hard:
                avg_hr += 4        # mismo esfuerzo, pulso más alto: eso es la fatiga
            vig_share, mod_share, _ = EFFORT[kind]
            vigorous, moderate = int(minutes * vig_share), int(minutes * mod_share)
            day_vigorous += vigorous
            day_moderate += moderate
            speed = (km * 1000 / (minutes * 60)) if km else None

            ins("activity", activity_id=act_id, activity_name=f"{kind} demo",
                activity_type_id=1, activity_type_key=kind,
                event_type_id=9, event_type_key="uncategorized",
                start_ts=_utc(d, begin), end_ts=_utc(d, begin + minutes / 60),
                timezone_offset_hours=TZ_HOURS,
                duration=minutes * 60.0, elapsed_duration=minutes * 60.0,
                moving_duration=minutes * 60.0,
                distance=(km * 1000) if km else None,
                lap_count=int(km) if km else 1,
                average_speed=speed, max_speed=speed * 1.25 if speed else None,
                aerobic_training_effect=round(rnd.uniform(*PROFILE[kind][1]), 1),
                anaerobic_training_effect=round(
                    rnd.uniform(0.8, 1.8) if vigorous else rnd.uniform(0.0, 0.5), 1),
                training_effect_label="TEMPO" if vigorous else "BASE",
                difference_body_battery=-int(minutes / 2.2),
                moderate_intensity_minutes=moderate, vigorous_intensity_minutes=vigorous,
                calories=float(minutes * (9 if vigorous else 6)),
                **{f"hr_time_in_zone_{z + 1}": minutes * 60 * share * rnd.uniform(0.85, 1.15)
                   for z, share in enumerate(PROFILE[kind][0])},
                average_hr=float(avg_hr), max_hr=float(avg_hr + 24),
                has_polyline=0, has_images=0, has_video=0, has_heat_map=0,
                parent=0, purposeful=1, favorite=0, manual_activity=0, pr=0,
                auto_calc_calories=1, ts_data_available=1)

            if kind in ("running", "trail_running"):
                ins("running_agg_metrics", activity_id=act_id,
                    steps=int(km * 1150), vo2_max_value=48.0,
                    avg_running_cadence=round(84 + rnd.uniform(-2, 2), 1),
                    avg_stride_length=round(112 + rnd.uniform(-6, 6), 1),
                    avg_ground_contact_time=round(255 + rnd.uniform(-12, 12), 1),
                    avg_vertical_oscillation=round(8.4 + rnd.uniform(-0.5, 0.5), 1),
                    avg_vertical_ratio=round((8.4 / 1.12) + (1.0 if hard else rnd.uniform(-0.3, 0.3)), 1),
                    avg_ground_contact_balance=round(51.8 if (hard and kind == "trail_running") else (50.1 + rnd.uniform(-0.3, 0.3)), 1),
                    avg_power=round(255 + rnd.uniform(-15, 15), 1),
                    elevation_gain=float(rnd.randint(250, 620) if kind == "trail_running"
                                        else rnd.randint(35, 130)))
            elif kind == "cycling":
                ins("cycling_agg_metrics", activity_id=act_id,
                    avg_biking_cadence=round(82 + rnd.uniform(-4, 4), 1),
                    avg_power=round(180 + rnd.uniform(-20, 20), 1),
                    elevation_gain=float(rnd.randint(200, 500)))

            # Vueltas y serie de FC solo dentro del informe: es lo único que se lee.
            if km and REPORT_START <= d <= REPORT_END:
                lap_km = 5.0 if kind == "cycling" else 1.0   # el autolap de la bici es más largo
                laps = max(1, int(km / lap_km))
                pace = minutes * 60 / (km / lap_km)          # segundos por vuelta
                climbs = 40 if kind == "trail_running" else 12
                # El pulso deriva a lo largo de la sesión: arranca frío y acaba alto.
                # La media de cada vuelta tiene que seguir esa misma deriva, o la FC
                # mínima (que sale de la serie a 1 Hz) acabaría por encima de la media.
                def hr_drift(fraction): return -12 + 20 * fraction
                for lap in range(laps):
                    lap_s = pace * rnd.uniform(0.94, 1.07)
                    lap_hr = round(avg_hr + hr_drift((lap + 0.5) / laps) + rnd.randint(-3, 3))
                    metrics = [
                        ("total_timer_time", lap_s), ("total_elapsed_time", lap_s),
                        ("total_distance", lap_km * 1000), ("enhanced_avg_speed", lap_km * 1000 / lap_s),
                        ("avg_heart_rate", float(lap_hr)),
                        ("max_heart_rate", float(lap_hr + 9)),
                        ("total_ascent", float(rnd.randint(2, climbs))),
                        ("total_descent", float(rnd.randint(2, climbs))),
                    ]
                    # La cadencia se cuenta en zancadas: en bici no aplica, y andando
                    # no es la de correr.
                    if kind in ("running", "trail_running"):
                        metrics.append(("avg_running_cadence", round(84 + rnd.uniform(-3, 3), 1)))
                    elif kind == "walking":
                        metrics.append(("avg_running_cadence", round(56 + rnd.uniform(-2, 2), 1)))
                    for name, value in metrics:
                        ins("activity_lap_metric", activity_id=act_id, lap_idx=lap,
                            name=name, value=value)
                total_s = minutes * 60
                for sec in range(0, total_s, 10):
                    ins("activity_ts_metric", activity_id=act_id,
                        timestamp=_utc(d, begin + sec / 3600), name="heart_rate",
                        value=float(round(avg_hr + hr_drift(sec / total_s) + rnd.randint(-6, 6))))

        ins("training_load", date=d.isoformat(),
            total_intensity_minutes=day_moderate + day_vigorous * 2,   # el vigoroso cuenta doble
            moderate_minutes=day_moderate, vigorous_minutes=day_vigorous,
            training_status=3)

        # --- Series intradía: estrés, Body Battery, pasos y pisos ----------------
        target_steps = rnd.randint(5200, 7800) + sum(
            int((km or 0) * EFFORT[k][2]) for k, _, km in sessions)
        # Un sesgo por día además del ruido por muestra: sin él, el ruido se promedia
        # y la media diaria de estrés sale casi constante toda la semana.
        stress_bias = rnd.uniform(-7, 7)
        slots = [7 + n * 0.5 for n in range(28)]     # 07:00 → 20:30, cada 30 min
        weights = [3.5 if any(a <= h < b for a, b in busy) else 1.0 for h in slots]
        total_w = sum(weights)
        battery = 22 + int(hours * 8)
        for hour, weight in zip(slots, weights):
            active = weight > 1.0
            stress = -2 if active else max(
                5, int((37 if hard else 28) + stress_bias + rnd.uniform(-9, 11)))
            ins("stress", timestamp=_utc(d, hour), value=stress)
            battery = max(5, min(100, battery - (5 if active else rnd.randint(1, 3))))
            ins("body_battery", timestamp=_utc(d, hour), value=battery)
            ins("steps", timestamp=_utc(d, hour), value=int(target_steps * weight / total_w),
                activity_level="active" if active else "sedentary")
        for hour in (9.5, 14.0, 19.5):
            ins("floors", timestamp=_utc(d, hour), ascended=rnd.randint(2, 7), descended=rnd.randint(2, 7))
        # La noche recarga la batería para el día siguiente.
        ins("body_battery", timestamp=_utc(d, 3.0), value=min(100, battery + int(hours * 9)))

        if d.weekday() == 6:                          # una lectura de VO2máx por semana
            ins("vo2_max", date=d.isoformat(),
                vo2_max_generic=47.0 if d < REPORT_START else 48.0)

    ins("race_predictions", date=REPORT_END.isoformat(), time_5k=1350.0, time_10k=2830.0,
        time_half_marathon=6300.0, time_marathon=13080.0, latest=1)
    ins("personal_record", timestamp=_utc(REPORT_START + timedelta(days=5), 19.0),
        type_id=12, label="Más pasos en un día", value=14350.0, latest=1,
        activity_id=None)

    conn.commit()
    conn.close()
    return REPORT_START, REPORT_END
