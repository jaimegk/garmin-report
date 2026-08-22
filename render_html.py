"""Vista HTML del informe: las tablas del markdown más gráficas SVG.

El .md lo genera generate_report.generate_md() y está pensado para una IA; este
módulo produce la versión legible por un humano a partir de ese mismo texto,
insertando gráficas construidas desde las series diarias originales.

Sin dependencias: solo stdlib, SVG inline y CSS. El fichero resultante se abre
con doble clic y funciona offline.
"""

import base64
import html as _html
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

# El logo vive en assets/ y se incrusta en el informe: el HTML tiene que seguir
# siendo un fichero suelto que se abre sin red. Se busca junto a este módulo,
# no en el directorio de trabajo.
LOGO_DIR = Path(__file__).with_name("assets") / "logo"

# Geometría común de las gráficas de serie temporal. viewBox fijo + width:100%
# => escalan con el contenedor sin recalcular nada.
W, H = 720, 170
PAD_L, PAD_R, PAD_T, PAD_B = 46, 10, 14, 26
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B

# Referencias de las gráficas que las llevan. No son objetivos del informe
# (esos los pone generate_report), solo la línea contra la que se lee el dibujo.
STEPS_GOAL = 10000
NIGHT_START_H = 18        # el eje de la noche empieza a las 18:00...
NIGHT_SPAN_MIN = 18 * 60  # ...y acaba 18 h después, a las 12:00 del día siguiente


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(s) -> str:
    return _html.escape(str(s), quote=True)


def _parse_ts(ts):
    """'2026-06-15 23:12:00' → datetime; None si no hay dato o no se entiende."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("T", " ")[:19])
    except ValueError:
        return None


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _nice_bounds(values, from_zero: bool, ylim=None):
    """Rango del eje: bonito, con margen, y nunca degenerado.

    ylim acota el resultado al rango físico de la métrica: el margen no debe
    inventar un eje de -9 a 114 para algo que solo puede valer entre 0 y 100.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return (0.0, 1.0) if not ylim else (float(ylim[0]), float(ylim[1]))
    lo = 0.0 if from_zero else min(vals)
    hi = max(vals)
    if hi == lo:
        hi = lo + 1
    if not from_zero:
        margin = (hi - lo) * 0.15
        lo, hi = lo - margin, hi + margin
    if ylim:
        lo, hi = max(lo, ylim[0]), min(hi, ylim[1])
    return float(lo), float(hi)


def _grid(lo: float, hi: float, fmt, width=W, pad_l=PAD_L, pad_r=PAD_R,
          pad_t=PAD_T, plot_h=PLOT_H) -> str:
    """Tres líneas horizontales con su etiqueta. Recesivas, por detrás."""
    out = []
    for frac in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * frac
        y = pad_t + plot_h * (1 - frac)
        out.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{pad_l - 6}" y="{y:.1f}" class="tick" text-anchor="end"'
            f' dominant-baseline="central">{_esc(fmt(v))}</text>'
        )
    return "".join(out)


def _xlabels(labels, plot_w=PLOT_W) -> str:
    """Etiquetas del eje X, diezmadas si no caben sin solaparse."""
    n = len(labels)
    if not n:
        return ""
    step = max(1, round(n / 12))
    slot = plot_w / n
    y = H - PAD_B + 15
    return "".join(
        f'<text x="{PAD_L + slot * (i + 0.5):.1f}" y="{y}" class="tick" text-anchor="middle">{_esc(lab)}</text>'
        for i, lab in enumerate(labels) if i % step == 0
    )


def _legend(items) -> str:
    """Leyenda: obligatoria con 2+ series, innecesaria con una (el título basta)."""
    if len(items) < 2:
        return ""
    spans = "".join(
        f'<span class="lg"><i style="background:{color}"></i>{_esc(name)}</span>'
        for name, color in items
    )
    return f'<div class="legend">{spans}</div>'


def _frame(title: str, body: str, items=(), vb=None, note="", cls="") -> str:
    vb = vb or f"0 0 {W} {H}"
    klass = f"chart {cls}".strip()
    foot = f'<figcaption class="note">{_esc(note)}</figcaption>' if note else ""
    return (
        f'<figure class="{klass}"><figcaption>{_esc(title)}</figcaption>'
        f'{_legend(items)}'
        f'<svg viewBox="{vb}" role="img" aria-label="{_esc(title)}">{body}</svg>'
        f'{foot}</figure>'
    )


# ---------------------------------------------------------------------------
# Gráficas
# ---------------------------------------------------------------------------

def svg_line(title, labels, values, name, unit="", fmt=None, ylim=None,
             band: tuple[float, float] | None = None, band_label: str = "") -> str:
    """Una serie temporal. Escala ajustada a los datos (no forzada a cero).

    Si se proporciona `band=(lo_band, hi_band)`, se dibuja una franja sombreada
    con líneas de referencia que delimitan el pasillo normal de fluctuación.
    """
    fmt = fmt or (lambda v: f"{v:,.0f}".replace(",", "."))
    bound_vals = [v for v in values if v is not None]
    if band and band[0] is not None and band[1] is not None:
        bound_vals.extend([band[0], band[1]])
    lo, hi = _nice_bounds(bound_vals, from_zero=False, ylim=ylim)

    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py(v): return PAD_T + PLOT_H * (1 - (v - lo) / (hi - lo))

    parts = [_grid(lo, hi, fmt), _xlabels(labels)]

    if band and band[0] is not None and band[1] is not None:
        y_top = py(band[1])
        y_bot = py(band[0])
        band_h = max(y_bot - y_top, 2.0)
        parts.append(
            f'<rect x="{PAD_L}" y="{y_top:.1f}" width="{PLOT_W}" height="{band_h:.1f}" class="band-range"/>'
            f'<line x1="{PAD_L}" y1="{y_top:.1f}" x2="{W - PAD_R}" y2="{y_top:.1f}" class="band-line"/>'
            f'<line x1="{PAD_L}" y1="{y_bot:.1f}" x2="{W - PAD_R}" y2="{y_bot:.1f}" class="band-line"/>'
            f'<text x="{W - PAD_R - 4}" y="{y_top - 4:.1f}" class="tick" text-anchor="end">{round(band[1])}</text>'
            f'<text x="{W - PAD_R - 4}" y="{y_bot + 12:.1f}" class="tick" text-anchor="end">{round(band[0])}</text>'
        )

    # Cada tramo continuo es un path propio: un día sin dato deja hueco real,
    # no una recta inventada entre los dos días que lo rodean.
    run = []
    for i, v in enumerate(values):
        if v is None:
            if len(run) > 1:
                parts.append(f'<polyline points="{" ".join(run)}" class="line"/>')
            run = []
        else:
            run.append(f"{px(i):.1f},{py(v):.1f}")
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line"/>')

    for i, v in enumerate(values):
        if v is None:
            continue
        tip_text = f"{labels[i]}: {fmt(v)}{unit}"
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4" class="dot"'
            f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
            f'<title>{_esc(tip_text)}</title></circle>'
        )
    return _frame(title, "".join(parts), note=band_label)


def svg_sleep_timeline(title, labels, nights, fmt_dur, lang: str = "en") -> str:
    """Cada noche en su hora real: cuándo te acostaste, cuándo te levantaste.

    Una barra apilada por noche solo dice cuánto dormiste. Puesta sobre el reloj
    dice además a qué hora, que es justo lo que mide la regularidad — y la
    irregularidad se ve como un escalón, sin tener que leer ninguna columna.
    """
    rows = [(lab, n) for lab, n in zip(labels, nights)]
    if not any(n for _l, n in rows):
        return ""
    is_es = lang == "es"
    pad_l, pad_r, pad_t, row_h = 52, 52, 22, 24
    height = pad_t + len(rows) * row_h + 26
    plot_w = W - pad_l - pad_r

    def px(m): return pad_l + plot_w * min(max(m, 0), NIGHT_SPAN_MIN) / NIGHT_SPAN_MIN

    parts = []
    for m in range(0, NIGHT_SPAN_MIN + 1, 120):
        x = px(m)
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad_t - 6:.1f}" x2="{x:.1f}"'
            f' y2="{pad_t + len(rows) * row_h:.1f}" class="grid"/>'
            f'<text x="{x:.1f}" y="{height - 8}" class="tick" text-anchor="middle">'
            f'{(NIGHT_START_H + m // 60) % 24:02d}h</text>'
        )

    beds, wakes = [], []
    for i, (lab, n) in enumerate(rows):
        y = pad_t + i * row_h
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end"'
            f' class="tick" data-day-idx="{i}">{_esc(lab)}</text>'
        )
        start, end = _parse_ts(n.start_ts) if n else None, _parse_ts(n.end_ts) if n else None
        if not (n and start and end and end > start):
            continue
        anchor = start.replace(hour=NIGHT_START_H, minute=0, second=0, microsecond=0)
        if start.hour < NIGHT_START_H:
            anchor -= timedelta(days=1)
        bed_m = (start - anchor).total_seconds() / 60
        wake_m = (end - anchor).total_seconds() / 60
        beds.append(bed_m)
        wakes.append(wake_m)

        x0, x1 = px(bed_m), px(wake_m)
        bar_y, bar_h = y + 5, row_h - 11
        span = max(wake_m - bed_m, 1) * 60
        phases = [("deep", n.deep_s), ("rem", n.rem_s), ("light", n.light_s),
                  ("awake", n.awake_s)]
        tip = (f"{lab}: {start:%H:%M} → {end:%H:%M} · {fmt_dur(n.sleep_s)}"
               if n.sleep_s else f"{lab}: {start:%H:%M} → {end:%H:%M}")
        parts.append(f'<g data-day-idx="{i}" data-day="{_esc(lab)}" data-tip="{_esc(tip)}"><title>{_esc(tip)}</title>')
        cursor = x0
        for cls, secs in phases:
            if not secs:
                continue
            w = (x1 - x0) * min(secs / span, 1)
            if w <= 0:
                continue
            parts.append(
                f'<rect x="{cursor:.1f}" y="{bar_y:.1f}" width="{w:.1f}"'
                f' height="{bar_h}" class="ph-{cls}"/>'
            )
            cursor += w
        if cursor < x1 - 0.5:  # noche sin desglose de fases: barra lisa
            parts.append(
                f'<rect x="{cursor:.1f}" y="{bar_y:.1f}" width="{x1 - cursor:.1f}"'
                f' height="{bar_h}" class="ph-light"/>'
            )
        parts.append(
            f'<rect x="{x0:.1f}" y="{bar_y:.1f}" width="{max(x1 - x0, 1):.1f}"'
            f' height="{bar_h}" rx="4" class="night-outline"/></g>'
        )
        if n.sleep_s:
            short = " short" if n.sleep_s < 6 * 3600 else ""
            parts.append(
                f'<text x="{x1 + 6:.1f}" y="{y + row_h / 2 + 4:.1f}"'
                f' class="tick{short}">{_esc(fmt_dur(n.sleep_s))}</text>'
            )

    # Las medianas son la referencia de regularidad: cuanto más pegadas estén
    # las barras a ellas, más constante ha sido la semana.
    median_targets = (
        (beds, "acostarse" if is_es else "bedtime"),
        (wakes, "despertar" if is_es else "wake")
    )
    prefix = "mediana" if is_es else "median"
    for values, name in median_targets:
        med = _median(values)
        if med is None:
            continue
        x = px(med)
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad_t - 12:.1f}" x2="{x:.1f}"'
            f' y2="{pad_t + len(rows) * row_h:.1f}" class="median"/>'
            f'<text x="{x:.1f}" y="{pad_t - 15:.1f}" class="tick" text-anchor="middle">'
            f'{prefix} {_esc(name)}</text>'
        )

    if is_es:
        items = [("Profundo", "var(--ph-1)"), ("REM", "var(--ph-2)"),
                 ("Ligero", "var(--ph-3)"), ("Despierto", "var(--ph-4)")]
        note = "El ancho de cada fase es proporcional a su total, no su orden real dentro de la noche."
    else:
        items = [("Deep", "var(--ph-1)"), ("REM", "var(--ph-2)"),
                 ("Light", "var(--ph-3)"), ("Awake", "var(--ph-4)")]
        note = "Bar segment width reflects total stage duration, not sleep sequence."

    return _frame(title, "".join(parts), items, vb=f"0 0 {W} {height}", note=note)


def svg_recovery_map(title, labels, rhr, hrv, base_rhr, base_hrv, swc_low=None, swc_high=None, lang: str = "en") -> str:
    """FC en reposo contra HRV, unidas en orden cronológico.

    Las dos métricas cuentan la misma historia y siempre hay que cruzarlas a
    mano entre dos gráficas. Aquí cada noche es un punto y la semana es el
    recorrido: hacia la esquina de arriba a la izquierda, recuperando; hacia la
    de abajo a la derecha, acumulando fatiga.
    """
    idx = [i for i in range(len(labels)) if rhr[i] is not None and hrv[i] is not None]
    if len(idx) < 2 or not base_rhr or not base_hrv:
        return ""
    is_es = lang == "es"
    w, h = 720, 320
    pl, pr, pt, pb = 60, 40, 30, 42
    pw, ph = w - pl - pr, h - pt - pb
    xlo, xhi = _nice_bounds([rhr[i] for i in idx] + [base_rhr], from_zero=False)
    ylo, yhi = _nice_bounds([hrv[i] for i in idx] + [base_hrv] + ([swc_low, swc_high] if swc_low else []), from_zero=False)

    def px(v): return pl + pw * (v - xlo) / (xhi - xlo)
    def py(v): return pt + ph * (1 - (v - ylo) / (yhi - ylo))

    bx, by = px(base_rhr), py(base_hrv)
    parts = []

    # Banda SWC horizontal de HRV
    if swc_low is not None and swc_high is not None:
        y_top, y_bot = py(swc_high), py(swc_low)
        parts.append(
            f'<rect x="{pl}" y="{y_top:.1f}" width="{pw}" height="{max(y_bot - y_top, 2):.1f}" class="swc-band"/>'
            f'<line x1="{pl}" y1="{y_top:.1f}" x2="{pl + pw}" y2="{y_top:.1f}" class="band-line"/>'
            f'<line x1="{pl}" y1="{y_bot:.1f}" x2="{pl + pw}" y2="{y_bot:.1f}" class="band-line"/>'
            f'<text x="{pl + pw - 6}" y="{y_top - 4:.1f}" class="tick" text-anchor="end">SWC {round(swc_high)} ms</text>'
            f'<text x="{pl + pw - 6}" y="{y_bot + 12:.1f}" class="tick" text-anchor="end">SWC {round(swc_low)} ms</text>'
        )

    # Cuadrantes sombreados y etiquetas explicativas
    if is_es:
        lbl_good = "● RECUPERADO (FC baja / HRV alta)"
        lbl_bad = "● FATIGA / SOBRECARGA (FC alta / HRV baja)"
        lbl_warn = "● Fatiga parasimpática (FC baja / HRV baja)"
        lbl_info = "● Reactividad / Estrés (FC alta / HRV alta)"
        x_axis_lbl = "FC reposo (bpm) →"
        y_axis_lbl = "↑ HRV nocturna (ms)"
        today_tag = " (hoy)"
    else:
        lbl_good = "● RECOVERED (Low HR / High HRV)"
        lbl_bad = "● FATIGUE / OVERLOAD (High HR / Low HRV)"
        lbl_warn = "● Parasympathetic fatigue (Low HR / Low HRV)"
        lbl_info = "● Reactivity / Stress (High HR / High HRV)"
        x_axis_lbl = "Resting HR (bpm) →"
        y_axis_lbl = "↑ Overnight HRV (ms)"
        today_tag = " (today)"

    parts.extend([
        f'<rect x="{pl}" y="{pt}" width="{bx - pl:.1f}" height="{by - pt:.1f}" class="q-good"/>',
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{pl + pw - bx:.1f}" height="{pt + ph - by:.1f}" class="q-bad"/>',
        f'<text x="{pl + 12}" y="{pt + 18}" class="quad-label good">{lbl_good}</text>',
        f'<text x="{pl + pw - 12}" y="{pt + ph - 10}" class="quad-label bad" text-anchor="end">{lbl_bad}</text>',
        f'<text x="{pl + 12}" y="{pt + ph - 10}" class="quad-label warn">{lbl_warn}</text>',
        f'<text x="{pl + pw - 12}" y="{pt + 18}" class="quad-label info" text-anchor="end">{lbl_info}</text>',
    ])

    # Ejes de la cruz basal
    parts.extend([
        f'<line x1="{bx:.1f}" y1="{pt}" x2="{bx:.1f}" y2="{pt + ph}" class="median"/>',
        f'<line x1="{pl}" y1="{by:.1f}" x2="{pl + pw}" y2="{by:.1f}" class="median"/>',
        f'<text x="{pl - 8}" y="{by + 4:.1f}" class="tick strong" text-anchor="end">{round(base_hrv)} ms</text>',
        f'<text x="{bx:.1f}" y="{pt + ph + 16}" class="tick strong" text-anchor="middle">{round(base_rhr)} bpm</text>',
        f'<text x="{pl + pw}" y="{h - 8}" class="tick" text-anchor="end">{x_axis_lbl}</text>',
        f'<text x="{pl}" y="{pt - 10}" class="tick">{y_axis_lbl}</text>',
    ])

    # Línea de recorrido temporal
    parts.append(
        '<polyline points="' + " ".join(f"{px(rhr[i]):.1f},{py(hrv[i]):.1f}" for i in idx)
        + '" class="trail"/>'
    )

    # Puntos día a día con etiquetas
    for rank, i in enumerate(idx):
        last = (rank == len(idx) - 1)
        dot_r = 7 if last else 4.5
        cls_dot = "dot last" if last else "dot"
        lbl = f"{labels[i]}{today_tag}" if last else labels[i]
        lbl_cls = "tick strong" if last else "tick"
        tip_text = f"{labels[i]}: {round(rhr[i])} bpm · {round(hrv[i])} ms"
        parts.append(
            f'<circle cx="{px(rhr[i]):.1f}" cy="{py(hrv[i]):.1f}" r="{dot_r}" class="{cls_dot}"'
            f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
            f'<title>{_esc(tip_text)}</title></circle>'
            f'<text x="{px(rhr[i]):.1f}" y="{py(hrv[i]) - (10 if last else 7):.1f}" class="{lbl_cls}" text-anchor="middle" data-day-idx="{i}">{_esc(lbl)}</text>'
        )

    if is_es:
        swc_note = f" · Banda SWC HRV: {round(swc_low)}–{round(swc_high)} ms" if (swc_low and swc_high) else ""
        note = f"Cruz central: tus medias basales ({round(base_rhr)} bpm / {round(base_hrv)} ms){swc_note}."
    else:
        swc_note = f" · HRV SWC band: {round(swc_low)}–{round(swc_high)} ms" if (swc_low and swc_high) else ""
        note = f"Center cross: your baseline averages ({round(base_rhr)} bpm / {round(base_hrv)} ms){swc_note}."

    return _frame(title, "".join(parts), vb=f"0 0 {w} {h}", note=note)


def svg_week_wheel(title, labels, values, goal=None, unit="", lang: str = "en") -> str:
    """Los días en círculo: una semana no es una recta, es un ciclo que se repite.

    Cada radio es un día; el anillo de puntos, el objetivo.
    """
    vals = [v for v in values if v]
    if not vals:
        return ""
    is_es = lang == "es"
    size, cx, cy, r0, r1 = 320, 160, 158, 54, 138
    top = max(max(vals), goal or 0) * 1.02
    n = len(values)
    step = 360 / n
    gap = 2.6

    def pt(deg, r):
        rad = math.radians(deg - 90)
        return cx + r * math.cos(rad), cy + r * math.sin(rad)

    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r0}" class="wheel-hub"/>']
    if goal:
        rg = r0 + (r1 - r0) * min(goal / top, 1)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{rg:.1f}" class="wheel-goal"/>')
    for i, v in enumerate(values):
        a0, a1 = -90 + i * step + gap, -90 + (i + 1) * step - gap
        x0o, y0o = pt(a0 + 90, r0)
        x1o, y1o = pt(a1 + 90, r0)
        lx, ly = pt(a0 + 90 + (step - 2 * gap) / 2, r1 + 16)
        cls = "wheel-day"
        if v:
            r = r0 + (r1 - r0) * min(v / top, 1)
            xa, ya = pt(a0 + 90, r)
            xb, yb = pt(a1 + 90, r)
            good = " good" if goal and v >= goal else ""
            tip_text = f"{labels[i]}: {v:,.0f}{unit}".replace(",", ".")
            parts.append(
                f'<path d="M{x0o:.1f},{y0o:.1f} L{xa:.1f},{ya:.1f}'
                f' A{r:.1f},{r:.1f} 0 0 1 {xb:.1f},{yb:.1f} L{x1o:.1f},{y1o:.1f}'
                f' A{r0},{r0} 0 0 0 {x0o:.1f},{y0o:.1f} Z" class="wedge{good}"'
                f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
                f'<title>{_esc(tip_text)}</title></path>'
            )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" class="tick {cls}" text-anchor="middle"'
            f' data-day-idx="{i}">{_esc(labels[i])}</text>'
        )
    avg = sum(vals) / len(vals)
    avg_sub = "media/día" if is_es else "avg/day"
    parts.append(
        f'<text x="{cx}" y="{cy - 2}" class="wheel-val" text-anchor="middle">'
        f'{_esc(f"{avg:,.0f}".replace(",", "."))}</text>'
        f'<text x="{cx}" y="{cy + 16}" class="tick" text-anchor="middle">{avg_sub}</text>'
    )
    if is_es:
        note = f"Anillo punteado: {goal:,.0f} pasos.".replace(",", ".") if goal else ""
    else:
        note = f"Dotted ring: {goal:,.0f} steps.".replace(",", ".") if goal else ""
    return _frame(title, "".join(parts), vb=f"0 0 {size} {size}", cls="wheel", note=note)


def svg_battery_range(title, labels, lows, highs, stress, lang: str = "en") -> str:
    """Cuánta batería gastaste cada día (la barra) y con cuánto estrés (el punto).

    Body Battery no es un número, es un recorrido entre el mínimo y el máximo
    del día: dibujar solo la media escondería justo eso.
    """
    if not any(v is not None for v in stress) and not any(v is not None for v in highs):
        return ""
    is_es = lang == "es"
    lo, hi = 0.0, 100.0
    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py(v): return PAD_T + PLOT_H * (1 - (v - lo) / (hi - lo))

    parts = [_grid(lo, hi, lambda v: f"{v:.0f}"), _xlabels(labels)]
    bw = min(slot * 0.34, 18)
    for i, lab in enumerate(labels):
        if lows[i] is not None and highs[i] is not None:
            y0, y1 = py(highs[i]), py(lows[i])
            tip_text = f"{lab} · Body Battery {round(lows[i])}–{round(highs[i])}"
            parts.append(
                f'<rect x="{px(i) - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}"'
                f' height="{max(y1 - y0, 2):.1f}" rx="{bw / 2:.1f}" class="bb-range"'
                f' data-day-idx="{i}" data-day="{_esc(lab)}" data-tip="{_esc(tip_text)}">'
                f'<title>{_esc(tip_text)}</title>'
                f'</rect>'
            )
    run = [f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(stress) if v is not None]
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line stress"/>')
    for i, v in enumerate(stress):
        if v is None:
            continue
        stress_lbl = "Estrés" if is_es else "Stress"
        tip_text = f"{labels[i]} · {stress_lbl} {round(v)}"
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4" class="dot stress"'
            f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
            f'<title>{_esc(tip_text)}</title></circle>'
        )
    if is_es:
        items = [("Body Battery (mín–máx)", "var(--bb)"), ("Estrés medio", "var(--accent-warm)")]
    else:
        items = [("Body Battery (min–max)", "var(--bb)"), ("Average stress", "var(--accent-warm)")]
    return _frame(title, "".join(parts), items)


def svg_spo2_resp(title, labels, spo2_mins, spo2_avgs, resp_avgs, lang: str = "en") -> str:
    """SpO2 y respiración nocturnas, cada una con su propio eje.

    Dos escalas incompatibles (% y resp/min) en un solo dibujo solo se pueden
    leer si cada una tiene su propio eje: SpO2 a la izquierda, respiración a
    la derecha. Sin el eje derecho los puntos de respiración caen sobre una
    rejilla de porcentajes que no significa nada para ellos.
    """
    """SpO2 (rango mín–media en barra) y Frecuencia Respiratoria nocturna (línea)."""
    has_spo2 = any(v is not None for v in spo2_avgs)
    has_resp = any(v is not None for v in resp_avgs)
    if not has_spo2 and not has_resp:
        return ""
    is_es = lang == "es"
    pad_r = 52
    plot_w = W - PAD_L - pad_r
    lo_spo2, hi_spo2 = 85.0, 100.0
    slot = plot_w / len(labels) if labels else plot_w
    def px(i): return PAD_L + slot * (i + 0.5)
    def py_spo2(v): return PAD_T + PLOT_H * (1 - (v - lo_spo2) / (hi_spo2 - lo_spo2))

    resp_vals = [v for v in resp_avgs if v is not None]
    lo_resp, hi_resp = (min(resp_vals) - 1, max(resp_vals) + 1) if resp_vals else (10.0, 20.0)
    if hi_resp == lo_resp:
        hi_resp += 2
    def py_resp(v): return PAD_T + PLOT_H * (1 - (v - lo_resp) / (hi_resp - lo_resp))

    parts = [_grid(lo_spo2, hi_spo2, lambda v: f"{v:.0f}%", pad_r=pad_r),
             _xlabels(labels, plot_w)]

    if resp_vals:
        dec = 0 if hi_resp - lo_resp >= 4 else 1
        for frac in (0.0, 0.5, 1.0):
            v = lo_resp + (hi_resp - lo_resp) * frac
            # La unidad va pegada al tick de arriba; un rótulo aparte se solaparía.
            unit = (" resp/min" if is_es else " br/min") if frac == 1.0 else ""
            parts.append(
                f'<text x="{W - pad_r + 6}" y="{PAD_T + PLOT_H * (1 - frac):.1f}"'
                f' class="tick resp" text-anchor="start"'
                f' dominant-baseline="central">{v:.{dec}f}{unit}</text>'
            )

    y95 = py_spo2(95)
    parts.append(f'<line x1="{PAD_L}" y1="{y95:.1f}" x2="{W - pad_r}" y2="{y95:.1f}" class="band-line" stroke="var(--accent)" stroke-dasharray="3,3" opacity="0.4"/>')

    bw = min(slot * 0.34, 18)
    for i, lab in enumerate(labels):
        s_min = spo2_mins[i]
        s_avg = spo2_avgs[i]
        if s_min is not None and s_avg is not None:
            y0, y1 = py_spo2(s_avg), py_spo2(s_min)
            tip_text = f"{lab} · SpO2 {round(s_min)}%–{round(s_avg)}%"
            parts.append(
                f'<rect x="{px(i) - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}"'
                f' height="{max(y1 - y0, 3):.1f}" rx="{bw / 2:.1f}" class="spo2-bar"'
                f' data-day-idx="{i}" data-day="{_esc(lab)}" data-tip="{_esc(tip_text)}">'
                f'<title>{_esc(tip_text)}</title>'
                f'</rect>'
            )

    run = [f"{px(i):.1f},{py_resp(v):.1f}" for i, v in enumerate(resp_avgs) if v is not None]
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line resp"/>')
    for i, v in enumerate(resp_avgs):
        if v is None:
            continue
        resp_unit = "resp/min" if is_es else "br/min"
        resp_lbl = "Respiración" if is_es else "Respiration"
        tip_text = f"{labels[i]} · {resp_lbl} {v:.1f} {resp_unit}"
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py_resp(v):.1f}" r="4" class="dot resp"'
            f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
            f'<title>{_esc(tip_text)}</title></circle>'
        )

    if is_es:
        items = [("SpO2 mín–media (eje izq.)", "var(--accent)"),
                 ("Respiración media (eje der.)", "var(--ph-2)")]
        note = "Línea punteada: referencia 95% SpO2. Cada serie tiene su propio eje."
    else:
        items = [("SpO2 min–avg (left axis)", "var(--accent)"),
                 ("Avg. respiration (right axis)", "var(--ph-2)")]
        note = "Dotted line: 95% SpO2 reference. Dual independent axes."
    return _frame(title, "".join(parts), items, note=note)


def svg_intensity_bars(title, labels, values, goal=None, lang: str = "en") -> str:
    """Minutos de intensidad diarios en barras, con la línea del objetivo diario.

    Misma geometría que el resto de series temporales: dentro de un `.pair` las
    etiquetas del eje escalan a 19px, y en un lienzo de 320 px se apelotonan
    hasta ser ilegibles.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    is_es = lang == "es"
    lo, hi = _nice_bounds(vals + [goal or 0], from_zero=True)
    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py(v): return PAD_T + PLOT_H * (1 - (v - lo) / (hi - lo))

    parts = [_grid(lo, hi, lambda v: f"{round(v)}m"), _xlabels(labels)]
    if goal:
        yg = py(goal)
        parts.append(
            f'<line x1="{PAD_L}" y1="{yg:.1f}" x2="{W - PAD_R}" y2="{yg:.1f}"'
            f' class="band-line" stroke="var(--ring-good)" opacity="0.7"/>'
        )

    bw = min(slot * 0.52, 22)
    y_base = py(lo)
    for i, v in enumerate(values):
        if not v:
            continue
        y = py(v)
        good = " good" if goal and v >= goal else ""
        tip_text = f"{labels[i]}: {round(v)} min"
        parts.append(
            f'<rect x="{px(i) - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}"'
            f' height="{max(y_base - y, 2):.1f}" rx="3" class="int-bar{good}"'
            f' data-day-idx="{i}" data-day="{_esc(labels[i])}" data-tip="{_esc(tip_text)}">'
            f'<title>{_esc(tip_text)}</title></rect>'
        )

    tot = sum(v for v in values if v)
    if is_es:
        note = (f"Línea: objetivo {round(goal)} min/día. " if goal else "")
        note += f"Total del periodo: {round(tot)} min (objetivo OMS: 150–300 min/sem)."
    else:
        note = (f"Line: {round(goal)} min/day goal. " if goal else "")
        note += f"Period total: {round(tot)} min (WHO target: 150–300 min/wk)."
    return _frame(title, "".join(parts), note=note)


def fitness_cards_html(vo2max, race_pred, lang: str = "en") -> str:
    """Tarjetas visuales para VO2máx y ritmos previstos de carrera."""
    cards = []
    is_es = lang == "es"
    if vo2max:
        run_v, cyc_v, _vo2_date = vo2max
        if run_v:
            lbl = "VO2máx Carrera" if is_es else "VO2max Running"
            cards.append(
                f'<div class="fit-card"><span class="fit-label">{lbl}</span>'
                f'<span class="fit-val">{round(run_v)}</span>'
                f'<span class="fit-sub">ml/kg/min</span></div>'
            )
        if cyc_v:
            lbl = "VO2máx Ciclismo" if is_es else "VO2max Cycling"
            cards.append(
                f'<div class="fit-card"><span class="fit-label">{lbl}</span>'
                f'<span class="fit-val">{round(cyc_v)}</span>'
                f'<span class="fit-sub">ml/kg/min</span></div>'
            )

    if race_pred:
        _rp_date, t5, t10, thalf, tmar = race_pred
        def fmt_time(sec):
            if not sec:
                return "–"
            isec = int(round(float(sec)))
            h, m, s = isec // 3600, (isec % 3600) // 60, isec % 60
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        def fmt_p(sec, km):
            if not sec or not km:
                return ""
            spk = float(sec) / km
            return f"{int(spk // 60)}:{int(round(spk % 60)):02d}/km"

        half_lbl = "Media (21K)" if is_es else "Half (21K)"
        mar_lbl = "Maratón (42K)" if is_es else "Marathon (42K)"
        preds = [
            ("5K", fmt_time(t5), fmt_p(t5, 5.0)),
            ("10K", fmt_time(t10), fmt_p(t10, 10.0)),
            (half_lbl, fmt_time(thalf), fmt_p(thalf, 21.0975)),
            (mar_lbl, fmt_time(tmar), fmt_p(tmar, 42.195)),
        ]
        for dist, t_str, pace_str in preds:
            if t_str != "–":
                cards.append(
                    f'<div class="fit-card"><span class="fit-label">{dist}</span>'
                    f'<span class="fit-val">{t_str}</span>'
                    f'<span class="fit-sub">{pace_str}</span></div>'
                )

    if not cards:
        return ""
    return f'<div class="fit-grid">{"".join(cards)}</div>'


# ---------------------------------------------------------------------------
# Gráficas del informe
# ---------------------------------------------------------------------------

def build_charts(sleep_rows, stress_map, bb_map, steps_map, start: date, end: date,
                 baselines=None, intensity_map=None, vo2max=None, race_pred=None,
                 lang: str = "en", goals: dict | None = None) -> dict:
    """Devuelve {título de sección → svg}, alineado día a día con las tablas."""
    baselines = baselines or {}
    intensity_map = intensity_map or {}
    is_es = lang == "es"
    steps_goal = int((goals or {}).get("steps_daily_goal") or STEPS_GOAL)

    # Mismo desfase que generate_md: la noche se cuelga del día en que te acostaste.
    sleep_by_date = {
        (date.fromisoformat(n.calendar_date) - timedelta(days=1)).isoformat(): n
        for n in sleep_rows
    }
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    keys = [d.isoformat() for d in days]
    labels = [f"{d.day}/{d.month}" for d in days]
    nights = [sleep_by_date.get(k) for k in keys]

    def h_fmt(sec):
        if not sec:
            return "–"
        return f"{int(sec // 3600)}h{round(sec % 3600 / 60):02d}"

    charts = {}

    t_sleep = "Cada noche sobre el reloj" if is_es else "Each night on the clock"
    timeline = svg_sleep_timeline(t_sleep, labels, nights, h_fmt, lang=lang)
    if timeline:
        charts["Sueño"] = timeline
        charts["Sleep"] = timeline

    rhr = [n.rhr if n else None for n in nights]
    hrv = [n.hrv if n else None for n in nights]
    pair = []
    if any(v is not None for v in rhr):
        rhr_title = "FC en reposo" if is_es else "Resting Heart Rate"
        rhr_name = "FC reposo" if is_es else "Resting HR"
        pair.append(svg_line(rhr_title, labels, rhr, rhr_name, unit=" bpm"))
    if any(v is not None for v in hrv):
        hrv_title = "HRV nocturno" if is_es else "Overnight HRV"
        swc_lo = baselines.get("swc_low")
        swc_hi = baselines.get("swc_high")
        band = (swc_lo, swc_hi) if (swc_lo is not None and swc_hi is not None) else None
        if is_es:
            band_note = f"Banda sombreada: tu rango normal ({round(swc_lo)}–{round(swc_hi)} ms)." if band else ""
        else:
            band_note = f"Shaded band: your normal baseline range ({round(swc_lo)}–{round(swc_hi)} ms)." if band else ""
        pair.append(svg_line(hrv_title, labels, hrv, "HRV", unit=" ms",
                             band=band, band_label=band_note))
    rec_title = "Mapa de recuperación de la semana" if is_es else "Weekly recovery map"
    cardio = svg_recovery_map(
        rec_title, labels, rhr, hrv,
        baselines.get("rhr"), baselines.get("hrv"),
        baselines.get("swc_low"), baselines.get("swc_high"),
        lang=lang,
    )
    if pair:
        cardio += f'<div class="pair">{"".join(pair)}</div>'
    if cardio:
        charts["FC reposo + HRV nocturno"] = cardio
        charts["Resting HR + Overnight HRV"] = cardio

    # Respiración y SpO2
    spo2_mins = [n.spo2_min if n else None for n in nights]
    spo2_avgs = [n.spo2_avg if n else None for n in nights]
    resp_avgs = [n.resp_avg if n else None for n in nights]
    spo2_title = "SpO2 y Respiración nocturnas" if is_es else "Overnight SpO2 & Respiration"
    spo2_chart = svg_spo2_resp(spo2_title, labels, spo2_mins, spo2_avgs, resp_avgs, lang=lang)
    if spo2_chart:
        charts["Respiración y SpO2 nocturnos"] = spo2_chart
        charts["Overnight Respiration & SpO2"] = spo2_chart

    stress = [stress_map.get(k) for k in keys]
    bb_hi = [bb_map[k][0] if k in bb_map else None for k in keys]
    bb_lo = [bb_map[k][1] if k in bb_map else None for k in keys]
    bb_title = "Body Battery y estrés, día a día" if is_es else "Body Battery and stress, day by day"
    battery = svg_battery_range(bb_title, labels, bb_lo, bb_hi, stress, lang=lang)
    if battery:
        charts["Estrés y Body Battery"] = battery
        charts["Stress & Body Battery"] = battery

    steps = [steps_map.get(k) for k in keys]
    wheel_title = "Pasos por día" if is_es else "Steps per day"
    wheel = svg_week_wheel(wheel_title, labels, steps, goal=steps_goal, lang=lang)
    im_vals = [intensity_map.get(k, (None, None, None))[0] if intensity_map else None for k in keys]
    int_title = "Minutos de intensidad / día" if is_es else "Intensity minutes / day"
    int_bars = svg_intensity_bars(int_title, labels, im_vals, goal=150 / 7, lang=lang)
    if wheel and int_bars:
        charts["Actividad"] = f'<div class="pair">{wheel}{int_bars}</div>'
        charts["Activity"] = f'<div class="pair">{wheel}{int_bars}</div>'
    elif wheel:
        charts["Actividad"] = wheel
        charts["Activity"] = wheel

    fit_grid = fitness_cards_html(vo2max, race_pred, lang=lang)
    if fit_grid:
        charts["Forma física"] = fit_grid
        charts["Fitness"] = fit_grid

    return charts



# ---------------------------------------------------------------------------
# Glosario y Explicaciones Educativas de Métricas
# ---------------------------------------------------------------------------

METRIC_EXPLANATIONS = {
    "en": {
        "sri": {
            "title": "Sleep Regularity Index (SRI)",
            "category": "Sleep",
            "what": "Measures the probability of you being in the same state (asleep or awake) at the same time across two consecutive days (0–100 scale).",
            "why": "Research demonstrates that circadian schedule consistency lowers premature mortality and cardiovascular risk as much or more than sleep duration alone.",
            "range": ">80 is optimal, 70–80 adequate, <68 irregular."
        },
        "acwr": {
            "title": "Acute:Chronic Workload Ratio (ACWR)",
            "category": "Load & Performance",
            "what": "Ratio of training load over the past 7 days (acute) compared to the last 4 weeks (chronic) calculated with exponentially weighted moving averages (EWMA).",
            "why": "Defines the training 'sweet spot': maximizing aerobic fitness gains while minimizing injury and overtraining risks.",
            "range": "0.80 to 1.30 is optimal (safe zone); 1.30 to 1.50 high progressive overload; >1.50 injury danger zone."
        },
        "hrv": {
            "title": "Heart Rate Variability (HRV / RMSSD)",
            "category": "Cardiovascular",
            "what": "Measures millisecond variations between consecutive heartbeats during deep overnight sleep.",
            "why": "The most sensitive physiological marker of parasympathetic (vagal tone) recovery and cellular regeneration.",
            "range": "Elevated HRV relative to your baseline indicates freshness; a sustained drop indicates fatigue, illness, or stress."
        },
        "hrv_cv": {
            "title": "HRV Stability / Coefficient of Variation (CV)",
            "category": "Cardiovascular",
            "what": "Coefficient of variation (standard deviation divided by mean) of nightly HRV across the week.",
            "why": "Large day-to-day swings (>10%) indicate autonomic instability and accumulated fatigue.",
            "range": "<6.5% very stable, 6.5–10% normal, >10.5% unstable."
        },
        "rhr": {
            "title": "Resting Heart Rate (RHR)",
            "category": "Cardiovascular",
            "what": "Lowest beats per minute recorded during sleep or complete rest.",
            "why": "A persistent rise (+3 to +5 bpm over baseline) is an early warning of fatigue, dehydration, or impending infection.",
            "range": "A low, stable resting heart rate signals robust cardiovascular conditioning."
        },
        "swc": {
            "title": "Smallest Worthwhile Change (SWC)",
            "category": "Cardiovascular",
            "what": "Statistical threshold band (±0.5 standard deviations from baseline) defining your individual normal physiological fluctuation range.",
            "why": "Prevents overreacting to daily random noise and highlights meaningful physiological adaptations.",
            "range": "Inside shaded band = baseline equilibrium; below = fatigue alert; above = supercompensation."
        },
        "decoupling": {
            "title": "Aerobic Decoupling / Cardiac Drift",
            "category": "Load & Performance",
            "what": "Gradual rise in heart rate while pace or power remains constant during steady aerobic efforts (>25 min).",
            "why": "Measures aerobic endurance capacity and mitochondrial cellular efficiency.",
            "range": "<3.5% excellent aerobic fitness; 3.5–5% normal; >7.5% elevated drift due to aerobic fatigue, heat, or dehydration."
        },
        "gct": {
            "title": "Ground Contact Time & Asymmetry",
            "category": "Load & Performance",
            "what": "Milliseconds each foot spends on the ground per stride and left/right balance percentage during running.",
            "why": "Early detection of biomechanical compensations before tendonitis or joint strain develops.",
            "range": "Ideal symmetry between 49.5% and 50.5% per leg."
        },
        "bb": {
            "title": "Body Battery & Stress Level",
            "category": "Wellness",
            "what": "Real-time energy score (1 to 100) calculated from HRV, autonomic stress, sleep, and physical activity.",
            "why": "Helps pace your daily demands: waking up above 75 ensures physical and mental reserves.",
            "range": "Target overnight recharge >60 points; average daytime stress <30."
        },
        "spo2": {
            "title": "Overnight SpO2 & Respiration Rate",
            "category": "Wellness",
            "what": "Blood oxygen saturation (%) and breathing frequency (breaths/min) during overnight rest.",
            "why": "Indicative screening for sleep-disordered breathing (e.g. hypopneas/apneas) and systemic inflammation.",
            "range": "Average SpO2 >94% is normal; typical sleep respiration 12 to 18 br/min."
        },
        "vo2max": {
            "title": "Maximal Oxygen Uptake (VO2max)",
            "category": "Cardiovascular",
            "what": "Maximum rate of oxygen (ml/kg/min) your body can transport and utilize during maximal exertion.",
            "why": "The single clinical biomarker with the strongest scientific correlation to longevity and all-cause risk reduction.",
            "range": "Higher VO2max translates to greater life expectancy and functional healthspan."
        }
    },
    "es": {
        "sri": {
            "title": "Índice de Regularidad del Sueño (SRI)",
            "category": "Sueño",
            "what": "Mide la probabilidad de que estés en el mismo estado (dormido o despierto) a la misma hora en dos días consecutivos (escala 0–100).",
            "why": "Estudios científicos demuestran que un ritmo circadiano regular reduce la mortalidad prematura y el riesgo cardiovascular tanto o más que la propia duración del sueño.",
            "range": ">80 es óptimo, 70–80 adecuado, <68 irregular."
        },
        "acwr": {
            "title": "Ratio de Carga Aguda:Crónica (ACWR)",
            "category": "Carga y Rendimiento",
            "what": "Relación entre la carga de entrenamiento de los últimos 7 días (aguda) y las últimas 4 semanas (crónica) calculada mediante medias móviles ponderadas (EWMA).",
            "why": "Delimita el 'punto dulce' del entrenamiento: progresar en resistencia o fuerza minimizando el riesgo de lesiones y sobreentrenamiento.",
            "range": "0.80 a 1.30 es óptimo (zona segura); 1.30 a 1.50 sobrecarga progresiva alta; >1.50 zona de peligro de lesión."
        },
        "hrv": {
            "title": "Variabilidad de Frecuencia Cardíaca (HRV / RMSSD)",
            "category": "Cardiovascular",
            "what": "Mide las variaciones milisegundo a milisegundo entre latidos cardíacos sucesivos durante el descanso nocturno profundo.",
            "why": "Es el reflejo directo más sensible de la activación del sistema nervioso parasimpático (freno vagal y capacidad de regeneración).",
            "range": "Un HRV elevado respecto a tu línea base indica frescura y adaptación; una caída sostenida indica fatiga o estrés."
        },
        "hrv_cv": {
            "title": "Estabilidad / Dispersión de HRV (CV)",
            "category": "Cardiovascular",
            "what": "Coeficiente de variación (desviación típica dividida por la media) del HRV nocturno a lo largo de la semana.",
            "why": "Grandes oscilaciones diarias (>10%) señalan inestabilidad autonómica y cansancio acumulado no asimilado.",
            "range": "<6.5% muy estable, 6.5–10% normal, >10.5% inestable."
        },
        "rhr": {
            "title": "Frecuencia Cardíaca en Reposo (FC Reposo)",
            "category": "Cardiovascular",
            "what": "Pulsaciones por minuto más bajas registradas durante el sueño o en reposo absoluto.",
            "why": "Un incremento persistente (+3 a +5 bpm sobre tu media histórica) es un aviso temprano de fatiga, deshidratación o el inicio de una infección.",
            "range": "Una FC en reposo baja y estable es señal de excelente adaptación cardiovascular."
        },
        "swc": {
            "title": "Cambio Mínimo Significativo (SWC)",
            "category": "Cardiovascular",
            "what": "Banda estadística (±0.5 desviaciones típicas de tu histórico) que define tu ventana de fluctuación fisiológica normal.",
            "why": "Evita sobre-reaccionar a variaciones aleatorias de un solo día y resalta los cambios verdaderamente relevantes.",
            "range": "Dentro del pasillo sombreado = equilibrio; por debajo = alerta de fatiga; por encima = supercompensación."
        },
        "decoupling": {
            "title": "Desacoplamiento / Deriva Aeróbica",
            "category": "Carga y Rendimiento",
            "what": "Aumento progresivo de la frecuencia cardíaca mientras la velocidad o potencia se mantiene constante durante una actividad aeróbica (>25 min).",
            "why": "Mide la resistencia cardiovascular y la eficiencia metabólica celular.",
            "range": "<3.5% excelente adaptación aeróbica; 3.5–5% normal; >7.5% deriva elevada por fatiga, calor o deshidratación."
        },
        "gct": {
            "title": "Tiempo de Contacto con el Suelo y Asimetría",
            "category": "Carga y Rendimiento",
            "what": "Milisegundos que el pie permanece apoyado en cada zancada y el balance porcentual izquierdo/derecho durante la carrera.",
            "why": "Permite detectar descompensaciones biomecánicas tempranas antes de que originen una tendinopatía o lesión articular.",
            "range": "Simetría ideal entre 49.5% y 50.5% por pierna."
        },
        "bb": {
            "title": "Body Battery y Nivel de Estrés",
            "category": "Bienestar",
            "what": "Puntuación de energía corporal (1 a 100) calculada a partir de HRV, estrés, sueño y actividad.",
            "why": "Permite gestionar el ritmo de la jornada: empezar el día por encima de 75 puntos garantiza reservas para entrenar y trabajar.",
            "range": "Recarga nocturna deseada >60 puntos; estrés diurno medio <30."
        },
        "spo2": {
            "title": "SpO2 Nocturna y Frecuencia Respiratoria",
            "category": "Bienestar",
            "what": "Saturación de oxígeno en sangre (%) y respiraciones por minuto durante el descanso nocturno.",
            "why": "Cribado no diagnóstico de alteraciones respiratorias nocturnas (como hipopneas/apneas) o sobrecargas inflamatorias.",
            "range": "SpO2 media >94% es normal; frecuencia respiratoria habitual entre 12 y 18 resp/min."
        },
        "vo2max": {
            "title": "Consumo Máximo de Oxígeno (VO2máx)",
            "category": "Cardiovascular",
            "what": "Volumen máximo de oxígeno (ml/kg/min) que tu cuerpo puede transportar y utilizar en esfuerzo máximo.",
            "why": "El parámetro clínico con mayor evidencia científica sobre longevidad y reducción de riesgo por cualquier causa.",
            "range": "A mayor VO2máx, mayor esperanza de vida y reserva fisiológica."
        }
    }
}


def status_card_html(tl: dict | None, lang: str = "en") -> str:
    """Semáforo de salud y diagnóstico en lenguaje natural (Fase 1 Usabilidad)."""
    if not tl:
        return ""
    is_es = lang == "es"
    state = tl.get("state", "optimal")
    badge = tl.get("badge", "🟢")
    title = tl.get("title", "Optimal State" if not is_es else "Estado óptimo")
    sleep_diag = tl.get("sleep_diag", "")
    recovery_diag = tl.get("recovery_diag", "")
    recommendation = tl.get("recommendation", "")

    kicker = "Evaluación de Estado" if is_es else "Health Status Evaluation"
    lbl_sleep = "Sueño:" if is_es else "Sleep:"
    lbl_rec = "Recuperación y Estrés:" if is_es else "Recovery & Stress:"
    lbl_rec_tag = "Recomendación:" if is_es else "Recommendation:"

    return (
        f'<div class="status-card status-{_esc(state)}">'
        f'<div class="status-header">'
        f'<span class="status-badge" aria-hidden="true">{badge}</span>'
        f'<div class="status-title-group">'
        f'<span class="status-kicker">{kicker}</span>'
        f'<h3 class="status-title">{_esc(title)}</h3>'
        f'</div>'
        f'</div>'
        f'<div class="status-grid">'
        f'<div class="status-item">'
        f'<span class="status-icon" aria-hidden="true">🌙</span>'
        f'<div><strong>{lbl_sleep}</strong> {_esc(sleep_diag)}</div>'
        f'</div>'
        f'<div class="status-item">'
        f'<span class="status-icon" aria-hidden="true">⚡</span>'
        f'<div><strong>{lbl_rec}</strong> {_esc(recovery_diag)}</div>'
        f'</div>'
        f'<div class="status-item highlight">'
        f'<span class="status-icon" aria-hidden="true">🎯</span>'
        f'<div><strong>{lbl_rec_tag}</strong> {_esc(recommendation)}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def glossary_modal_html(lang: str = "en") -> str:
    """Modal interactivo con el glosario de términos de salud y longevidad."""
    is_es = lang == "es"
    glossary_data = METRIC_EXPLANATIONS.get(lang, METRIC_EXPLANATIONS["en"])
    cards = []
    for key, item in glossary_data.items():
        q_what = "¿Qué es?" if is_es else "What is it?"
        q_why = "¿Por qué importa?" if is_es else "Why it matters:"
        q_range = "Rango orientativo:" if is_es else "Reference range:"
        cards.append(
            f'<article class="glossary-card" data-category="{_esc(item["category"])}">'
            f'<div class="glossary-card-header">'
            f'<h4>{_esc(item["title"])}</h4>'
            f'<span class="glossary-badge">{_esc(item["category"])}</span>'
            f'</div>'
            f'<p><strong>{q_what}</strong> {_esc(item["what"])}</p>'
            f'<p><strong>{q_why}</strong> {_esc(item["why"])}</p>'
            f'<p class="glossary-range"><strong>{q_range}</strong> {_esc(item["range"])}</p>'
            f'</article>'
        )

    title_modal = _esc("📖 Glosario de Métricas y Salud" if is_es else "📖 Health & Metric Glossary")
    close_lbl = "Cerrar glosario" if is_es else "Close glossary"
    search_ph = "🔍 Buscar métrica o concepto..." if is_es else "🔍 Search metric or concept (e.g. SRI, HRV, ACWR)..."
    cat_all = "Todos" if is_es else "All"
    cat_sleep = "Sueño" if is_es else "Sleep"
    cat_cardio = "Cardiovascular"
    cat_load = "Carga" if is_es else "Load"
    cat_load_full = "Carga y Rendimiento" if is_es else "Load & Performance"
    cat_well = "Bienestar" if is_es else "Wellness"

    return (
        f'<div id="glossary-modal" class="modal-backdrop" aria-hidden="true" role="dialog" aria-label="{title_modal}">'
        '<div class="modal-dialog">'
        '<div class="modal-header">'
        f'<h3>{title_modal}</h3>'
        f'<button type="button" class="modal-close" id="glossary-close" aria-label="{close_lbl}">✕</button>'
        '</div>'
        '<div class="modal-filter-bar">'
        f'<input type="search" id="glossary-search" placeholder="{search_ph}" aria-label="Search glossary">'
        '<div class="glossary-categories">'
        f'<button type="button" class="cat-pill active" data-cat="all">{cat_all}</button>'
        f'<button type="button" class="cat-pill" data-cat="{cat_sleep}">{cat_sleep}</button>'
        f'<button type="button" class="cat-pill" data-cat="{cat_cardio}">{cat_cardio}</button>'
        f'<button type="button" class="cat-pill" data-cat="{cat_load_full}">{cat_load}</button>'
        f'<button type="button" class="cat-pill" data-cat="{cat_well}">{cat_well}</button>'
        '</div>'
        '</div>'
        f'<div class="glossary-grid">{"".join(cards)}</div>'
        '</div>'
        '</div>'
    )



def tooltip_html() -> str:
    """Contenedor flotante para tooltips enriquecidos e interactividad táctil."""
    return '<div id="biodelta-tooltip" class="tooltip-popover" aria-hidden="true"></div>'


# ---------------------------------------------------------------------------
# Bloques de cabecera
# ---------------------------------------------------------------------------

# Un anillo por métrica, cada uno en su ficha: el mismo radio para los tres
# (viewBox de 80x80) porque ninguno vale más que los otros. Concéntricos solo
# ahorran espacio, y a cambio obligan a comparar arcos de distinto tamaño.
RING_R = 34
RING_W = 8


def rings_html(rings) -> str:
    """Anillos de resumen: el vistazo de tres segundos antes de las cifras.

    rings: (etiqueta, fracción 0–1 o None, valor, detalle, estado), tal y como
    los arma generate_report — que es quien sabe qué es un buen dato. Aquí solo
    se pinta. Cada ficha lleva su etiqueta y el porcentaje del objetivo dentro
    del anillo, así que el color subraya el estado pero nunca es la única pista.
    """
    if not rings:
        return ""
    circ = 2 * math.pi * RING_R
    cards = []
    for label, frac, value, detail, state in rings:
        pct = min(max(frac or 0.0, 0.0), 1.0)
        color = f"var(--ring-{state})" if state else "var(--muted)"
        pct_txt = f"{round(pct * 100)}%" if frac is not None else "–"
        cards.append(
            f'<div class="ring-card">'
            f'<div class="ring-dial">'
            f'<svg viewBox="0 0 80 80" role="img"'
            f' aria-label="{_esc(f"{label}: {pct_txt} del objetivo")}">'
            f'<circle cx="40" cy="40" r="{RING_R}" class="ring-track"'
            f' stroke-width="{RING_W}"/>'
            f'<circle cx="40" cy="40" r="{RING_R}" fill="none" stroke="{color}"'
            f' stroke-width="{RING_W}" stroke-linecap="round"'
            f' stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ * (1 - pct):.1f}"'
            f' transform="rotate(-90 40 40)"/></svg>'
            f'<span class="ring-pct">{_esc(pct_txt)}</span></div>'
            f'<div class="ring-text"><span class="ring-name">{_esc(label)}</span>'
            f'<span class="ring-val {state}">{_esc(value)}</span></div>'
            f'<p class="ring-detail">{_esc(detail)}</p></div>'
        )
    return f'<section class="hero">{"".join(cards)}</section>'


def tiles_html(tiles) -> str:
    """Cabecera de un vistazo: una cifra por métrica del resumen.

    tiles: (etiqueta, valor, tendencia, estado) — el estado ("good"/"bad"/"")
    lo decide generate_report, que es quien sabe hacia qué lado es mejor cada
    métrica; aquí solo se pinta. La flecha va siempre, así que el color añade
    énfasis pero nunca es la única señal.
    """
    if not tiles:
        return ""
    cards = "".join(
        f'<div class="tile"><div class="k">{_esc(label)}</div>'
        f'<div class="v">{_esc(value)}</div>'
        f'<div class="t {state}">{_esc(trend)}</div></div>'
        for label, value, trend, state in tiles
    )
    return f'<div class="tiles">{cards}</div>'


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

# Conversor para NUESTRO md, no markdown general. Cubre justo lo que
# genera generate_md (encabezados, tablas, listas, negrita/cursiva, regla).
# Si el md gana sintaxis → pip install markdown, extensión 'tables'.

_ALIGN = {(True, True): "center", (False, True): "right"}

# Las señales del informe ya vienen marcadas con un emoji: sirve de icono y de
# clave para colorear la fila. Se conserva en el texto, así que el estado sigue
# siendo legible sin distinguir colores.
_SIGNALS = {"⚠️": "warn", "✅": "good", "ℹ️": "info"}

# El reparto por zonas de FC viene como "14/39/34/10/2" (porcentajes, z1→z5).
# Cinco números seguidos no se leen; cinco colores de calma a máximo, sí.
_ZONES = re.compile(r"(\d{1,3})/(\d{1,3})/(\d{1,3})/(\d{1,3})/(\d{1,3})")


def _signal_class(text: str) -> str:
    for mark, cls in _SIGNALS.items():
        if text.startswith(mark):
            return cls
    return ""


def _slug(text: str) -> str:
    """Ancla estable para el índice: 'FC reposo + HRV' → 'fc-reposo-hrv'."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "seccion"


def _inline(text: str) -> str:
    out = _esc(text.strip())
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", out)
    return out


def _cell(text: str) -> str:
    """Contenido de una celda: barra de zonas si lo es, texto si no."""
    m = _ZONES.fullmatch(text.strip())
    if not m:
        return _inline(text)
    pcts = [int(g) for g in m.groups()]
    total = sum(pcts) or 1
    bars = "".join(
        f'<i class="z{i + 1}" style="width:{p / total * 100:.1f}%"></i>'
        for i, p in enumerate(pcts) if p
    )
    return (f'<span class="zones" title="Zonas 1-5: {_esc(text.strip())}">{bars}</span>'
            f'<span class="zt">{_esc(text.strip())}</span>')


def _cells(row: str) -> list[str]:
    return [c for c in row.strip().strip("|").split("|")]


def _is_sep(row: str) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in _cells(row) if c.strip())


def _table(rows: list[str]) -> str:
    head, rest = rows[0], rows[1:]
    # La fila de guiones lleva la alineación de cada columna y no es un dato.
    aligns = []
    if rest and _is_sep(rest[0]):
        aligns = [_ALIGN.get((c.strip().startswith(":"), c.strip().endswith(":")), "left")
                  for c in _cells(rest[0])]
        rest = rest[1:]
    body = rest

    def style(i):
        a = aligns[i] if i < len(aligns) else "left"
        return f' style="text-align:{a}"' if a != "left" else ""

    out = ["<div class='tw'><table><thead><tr>"]
    out += [f"<th{style(i)}>{_inline(c)}</th>" for i, c in enumerate(_cells(head))]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>")
        out += [f"<td{style(i)}>{_cell(c)}</td>" for i, c in enumerate(_cells(row))]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def md_to_html(md: str, charts: dict | None = None, lang: str = "en") -> str:
    """Convierte el markdown del informe en HTML gráfico y editorial.

    - Inyecta las gráficas SVG al inicio de cada sección `##`.
    - En la sección `Resumen`, enseña únicamente las Señales destacadas (las métricas
      ya están en los anillos de portada y tarjetas de cabecera).
    - Agrupa las tablas y notas contextuales detalladas en bloques `<details class="collapsible">`
      desplegables, manteniendo las cifras clave y gráficas inmediatamente a la vista.
    """
    charts = charts or {}
    is_es = lang == "es"
    out = []
    sections = re.split(r'(?m)^## ', md)

    if sections:
        lead = sections[0].strip()
        if lead:
            for line in lead.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("# "):
                    out.append(f"<h1>{_inline(line[2:])}</h1>")
                elif re.fullmatch(r"-{3,}", line):
                    out.append("<hr>")
                else:
                    out.append(f"<p>{_inline(line)}</p>")

    sec_num = 1
    for sec_text in sections[1:]:
        lines = sec_text.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        content_lines = lines[1:]

        out.append(
            f'<section class="sec" id="{_slug(title)}">'
            f'<div class="sec-rail"><span class="sec-n">{sec_num:02d}</span>'
            f'<h2>{_inline(title)}</h2></div><div class="sec-body">'
        )
        sec_num += 1

        if title in charts:
            out.append(charts[title])

        if title in ("Resumen", "Summary"):
            bullets, res_table = [], []
            for l in content_lines:
                s = l.strip()
                if s.startswith("- "):
                    bullets.append(s[2:])
                elif s.startswith("|"):
                    res_table.append(s)
            if bullets:
                classes = [_signal_class(b) for b in bullets]
                ul = ' class="signals"' if any(classes) else ""
                items = "".join(
                    f'<li class="{c}">{_inline(b)}</li>' if c else f"<li>{_inline(b)}</li>"
                    for b, c in zip(bullets, classes)
                )
                out.append(f"<ul{ul}>{items}</ul>")
            if res_table:
                # Las tarjetas de cabecera solo cubren la semana actual: en un informe
                # multi-semana esta tabla es la única evolución que hay, y perderla
                # dejaría el HTML contando menos que el markdown.
                sum_title = "Métricas en detalle" if is_es else "Detailed metrics"
                out.append(
                    f'<details class="collapsible"><summary>{sum_title}</summary>'
                    f'<div class="coll-body">{_table(res_table)}</div></details>'
                )
            out.append("</div></section>")
            continue

        if title in ("Forma física", "Fitness"):
            notes = []
            for l in content_lines:
                s = l.strip()
                if s.startswith("- "):
                    notes.append(s[2:])
                elif s and not re.fullmatch(r"-{3,}", s):
                    notes.append(s)
            if notes:
                fit_sum_title = "Notas sobre VO2máx y ritmos previstos" if is_es else "Notes on VO2max & predicted race times"
                out.append(
                    f'<details class="collapsible"><summary>{fit_sum_title}</summary>'
                    '<div class="coll-body">'
                )
                for n in notes:
                    out.append(f"<p>{_inline(n)}</p>")
                out.append("</div></details>")
            out.append("</div></section>")
            continue

        key_lines = []
        detail_items = []
        table_buf = []
        bullets_buf = []

        def flush_bullets():
            if bullets_buf:
                classes = [_signal_class(b) for b in bullets_buf]
                ul = ' class="signals"' if any(classes) else ""
                items = "".join(
                    f'<li class="{c}">{_inline(b)}</li>' if c else f"<li>{_inline(b)}</li>"
                    for b, c in zip(bullets_buf, classes)
                )
                detail_items.append(f"<ul{ul}>{items}</ul>")
                bullets_buf.clear()

        def flush_table():
            if table_buf:
                detail_items.append(_table(table_buf))
                table_buf.clear()

        for l in content_lines:
            s = l.strip()
            if not s:
                continue
            if s.startswith("|"):
                flush_bullets()
                table_buf.append(s)
                continue
            flush_table()

            if s.startswith("- "):
                bullets_buf.append(s[2:])
                continue
            flush_bullets()

            if s.startswith("### "):
                sub_title = s[4:].strip()
                detail_items.append(f"<h3>{_inline(sub_title)}</h3>")
            elif (s.startswith("**Media") or s.startswith("**Average") or
                  s.startswith("**Intensidad") or s.startswith("**Intensity")):
                key_lines.append(f"<p class='key-metric'>{_inline(s)}</p>")
            elif re.fullmatch(r"-{3,}", s):
                pass
            else:
                detail_items.append(f"<p>{_inline(s)}</p>")
        flush_table()
        flush_bullets()

        for kl in key_lines:
            out.append(kl)

        if detail_items:
            if is_es:
                summary_label = {
                    "Sueño": "Desglose diario y contexto de sueño",
                    "FC reposo + HRV nocturno": "Desglose diario de FC y HRV",
                    "Respiración y SpO2 nocturnos": "Desglose diario y notas clínicas",
                    "Estrés y Body Battery": "Desglose diario de estrés y Body Battery",
                    "Actividad": "Desglose diario de actividad y sesiones",
                }.get(title, "Ver desglose diario y detalles")
            else:
                summary_label = {
                    "Sleep": "Daily sleep breakdown and context",
                    "Resting HR + Overnight HRV": "Daily resting HR and HRV breakdown",
                    "Overnight Respiration & SpO2": "Daily respiration and SpO2 breakdown",
                    "Stress & Body Battery": "Daily stress and Body Battery breakdown",
                    "Activity": "Daily activity and session breakdown",
                }.get(title, "View daily breakdown and details")

            out.append(
                f'<details class="collapsible"><summary>{summary_label}</summary>'
                f'<div class="coll-body">{"".join(detail_items)}</div></details>'
            )

        out.append("</div></section>")

    return "\n".join(out)



# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

CSS = """
/* Negro sobre blanco, mucho aire y tipografía apretada: el informe se lee como
   una página de producto, no como un panel de control. El color aparece solo
   donde significa algo (estado de un anillo, dirección de una tendencia,
   gravedad de una señal); el resto es tinta. El tema oscuro es el mismo
   documento con la tinta y el papel intercambiados. */
:root {
  color-scheme: light;
  --paper: #ffffff; --surface: #f5f5f7; --ink: #1d1d1f; --ink2: #6e6e73;
  --muted: #86868b; --hairline: #d2d2d7; --grid: #e8e8ed;
  --accent: #0066cc; --accent-warm: #b25000;
  --good: #248a3d; --warn: #9a5b00; --bad: #d70015;
  --ring-good: #30a14e; --ring-warn: #e08600; --ring-bad: #e0342b;
  --ph-1: #1d1d1f; --ph-2: #6e6e73; --ph-3: #c7c7cc; --ph-4: #e8e8ed;
  --bb: #0066cc;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #000000; --surface: #1d1d1f; --ink: #f5f5f7; --ink2: #a1a1a6;
  --muted: #86868b; --hairline: #424245; --grid: #2a2a2c;
  --accent: #2997ff; --accent-warm: #ff9f0a;
  --good: #30d158; --warn: #ffb340; --bad: #ff453a;
  --ring-good: #30d158; --ring-warn: #ff9f0a; --ring-bad: #ff453a;
  --ph-1: #f5f5f7; --ph-2: #a1a1a6; --ph-3: #48484a; --ph-4: #2a2a2c;
  --bb: #2997ff;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; padding: 0 0 6rem; background: var(--paper); color: var(--ink);
  font-family: "SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont,
               "Helvetica Neue", Helvetica, "Segoe UI", Arial, sans-serif;
  font-size: 17px; line-height: 1.5; letter-spacing: -.012em;
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
}
.wrap { max-width: 68rem; margin: 0 auto; padding: 0 1.5rem; }
td, th, .num { font-variant-numeric: tabular-nums; }

/* Barra superior: 44 px, translúcida, sin peso visual */
.topbar { position: sticky; top: 0; z-index: 20; height: 3rem;
          background: var(--paper);
          background: color-mix(in srgb, var(--paper) 82%, transparent);
          backdrop-filter: saturate(180%) blur(20px);
          -webkit-backdrop-filter: saturate(180%) blur(20px);
          border-bottom: 1px solid var(--hairline); }
.topbar-in { max-width: 68rem; margin: 0 auto; height: 100%; padding: 0 1.5rem;
             display: flex; align-items: center; gap: 0.75rem; }
.brand { font-size: .8rem; font-weight: 600; letter-spacing: -.01em; white-space: nowrap; flex-shrink: 0; }
.navlinks { display: flex; gap: .85rem; overflow-x: auto; scrollbar-width: none;
            flex: 1; min-width: 0; }
.navlinks::-webkit-scrollbar { display: none; }
.navlinks a { color: var(--ink2); text-decoration: none; font-size: .76rem;
              white-space: nowrap; flex-shrink: 0; }
.navlinks a:hover { color: var(--ink); }

/* Botones de navegación y utilidades */
.nav-btn {
  border: 1px solid var(--hairline); background: none;
  color: var(--ink); border-radius: 980px; padding: .2rem .65rem;
  font: inherit; font-size: .74rem; cursor: pointer; white-space: nowrap; flex-shrink: 0;
  display: inline-flex; align-items: center; gap: .3rem;
}
.nav-btn:hover { background: var(--surface); }
.theme-btn { margin-left: auto; border: 1px solid var(--hairline); background: none;
             color: var(--ink); border-radius: 980px; padding: .2rem .7rem;
             font: inherit; font-size: .74rem; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.theme-btn:hover { background: var(--surface); }

/* Portada */
.lede { padding: 3rem 0 2.25rem; max-width: 46rem; }
h1 { display: flex; align-items: center; gap: .55rem;
     font-size: clamp(1.5rem, 2.6vw, 1.95rem); line-height: 1.15; letter-spacing: -.025em;
     font-weight: 650; margin: 0 0 .6rem; }
.logo { width: 1.45em; height: 1.45em; flex-shrink: 0; }
.lede p { font-size: 1rem; line-height: 1.45; color: var(--ink2); margin: .3rem 0; }
.lede em { font-size: 1rem; color: var(--muted); font-style: normal; }
.lede strong { color: var(--ink); }

/* Semáforo de Estado y Resumen Ejecutivo en Lenguaje Natural */
.status-card {
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 1.25rem 1.4rem;
  margin: 1.25rem 0 1.75rem;
  background: color-mix(in srgb, var(--paper) 85%, var(--grid));
  position: relative;
  overflow: hidden;
}
.status-card::before {
  content: "";
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: 5px;
}
.status-card.status-optimal::before { background: var(--good); }
.status-card.status-warning::before { background: var(--warn); }
.status-card.status-recovery::before { background: var(--bad); }

.status-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.status-badge {
  font-size: 1.45rem;
  line-height: 1;
}
.status-title-group { display: flex; flex-direction: column; }
.status-kicker {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.status-title {
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0.1rem 0 0;
  text-transform: none;
}
.status-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.55rem;
}
.status-item {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  font-size: 0.92rem;
  line-height: 1.45;
  color: var(--ink2);
}
.status-item strong { color: var(--ink); }
.status-item.highlight {
  margin-top: 0.25rem;
  padding-top: 0.65rem;
  border-top: 1px solid color-mix(in srgb, var(--hairline) 60%, transparent);
  color: var(--ink);
}
.status-icon {
  font-size: 1.05rem;
  line-height: 1.35;
  flex-shrink: 0;
}

/* Secciones: título en un raíl fijo a la izquierda, contenido a la derecha */
.sec { display: grid; grid-template-columns: 11rem 1fr; gap: 3rem;
       border-top: 1px solid var(--hairline); padding: 3.5rem 0 1rem; }
.sec-rail { position: sticky; top: 4.5rem; align-self: start; }
.sec-n { display: block; font-size: .72rem; color: var(--muted); letter-spacing: .1em; }
.sec-rail h2 { font-size: 1.45rem; letter-spacing: -.028em; line-height: 1.15;
               margin: .35rem 0 0; font-weight: 650; }
.sec-body { min-width: 0; }
@media (max-width: 62rem) {
  .sec { grid-template-columns: 1fr; gap: .75rem; padding-top: 2.5rem; }
  .sec-rail { position: static; }
}
h3 { font-size: .74rem; font-weight: 700; text-transform: uppercase;
     letter-spacing: .08em; color: var(--muted); margin: 2.5rem 0 .75rem; }
p { margin: .7rem 0; }
em { color: var(--ink2); font-style: normal; font-size: .88rem; }
hr { display: none; }
ul { margin: .7rem 0; padding-left: 1.1rem; }
li { margin: .35rem 0; }
a { color: var(--accent); }
.key-metric { font-size: 1.05rem; font-weight: 600; color: var(--ink); margin: 1.25rem 0 .75rem; }

/* Anillos: uno por métrica, en fila. Cada ficha se lee sola. */
.hero { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 2.5rem;
        border-top: 1px solid var(--hairline); margin: 1.25rem 0 0; }
.ring-card { display: grid; grid-template-columns: auto 1fr; gap: 0 1rem;
             align-items: center; padding: 1.4rem 0;
             border-bottom: 1px solid var(--hairline); }
.ring-dial { position: relative; width: 76px; height: 76px; }
.ring-dial svg { width: 100%; height: 100%; display: block; }
.ring-track { fill: none; stroke: var(--grid); }
.ring-pct { position: absolute; inset: 0; display: grid; place-items: center;
            font-size: .8rem; font-weight: 650; letter-spacing: -.02em;
            font-variant-numeric: tabular-nums; }
.ring-text { min-width: 0; }
.ring-name { display: block; font-size: .72rem; color: var(--muted);
             letter-spacing: .02em; }
.ring-val { display: block; font-size: 1.75rem; font-weight: 650;
            letter-spacing: -.04em; line-height: 1.15; }
.ring-val.good { color: var(--good); }
.ring-val.warn { color: var(--warn); }
.ring-val.bad { color: var(--bad); }
.ring-detail { grid-column: 1 / -1; font-size: .78rem; color: var(--muted);
               margin: .75rem 0 0; }
@media (max-width: 62rem) { .hero { grid-template-columns: 1fr; gap: 0; } }

/* Cifras: hoja de especificaciones a dos columnas, sin cajas. */
.tiles { columns: 2; column-gap: 3rem; margin: 2.5rem 0 2rem; }
.tile { break-inside: avoid; display: grid; column-gap: 1rem;
        grid-template-columns: 1fr auto minmax(4.5rem, auto);
        align-items: baseline; padding: .75rem 0;
        border-bottom: 1px solid var(--hairline); }
.tile .k { font-size: .82rem; color: var(--ink2); }
.tile .v { font-size: 1.35rem; font-weight: 650; letter-spacing: -.03em;
           text-align: right; }
.tile .t { font-size: .78rem; color: var(--muted); text-align: right; }
.tile .t.good { color: var(--good); }
.tile .t.bad { color: var(--bad); }
@media (max-width: 46rem) { .tiles { columns: 1; } }

/* Señales: dos columnas, filete de color y nada más */
ul.signals { list-style: none; padding: 0; margin: 1.25rem 0 2rem;
             columns: 2; column-gap: 2.5rem; }
ul.signals li { break-inside: avoid; margin: 0 0 .9rem; padding: .1rem 0 .1rem 1rem;
                border-left: 2px solid var(--hairline); font-size: .95rem;
                line-height: 1.45; }
ul.signals li.warn { border-left-color: var(--ring-warn); }
ul.signals li.good { border-left-color: var(--ring-good); }
ul.signals li.info { border-left-color: var(--accent); }
@media (max-width: 46rem) { ul.signals { columns: 1; } }

/* Desplegables de detalle */
details.collapsible {
  margin: 1.25rem 0 1.75rem;
  border: 1px solid var(--hairline);
  border-radius: 10px;
  background: color-mix(in srgb, var(--paper) 65%, var(--grid));
  overflow: hidden;
}
details.collapsible summary {
  padding: .75rem 1.1rem;
  font-size: .82rem;
  font-weight: 600;
  color: var(--ink2);
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: .5rem;
  list-style: none;
}
details.collapsible summary::-webkit-details-marker { display: none; }
details.collapsible summary::before {
  content: "▸";
  font-size: .9rem;
  display: inline-block;
  transition: transform .15s ease;
  color: var(--muted);
}
details.collapsible[open] summary::before {
  transform: rotate(90deg);
}
details.collapsible summary:hover {
  color: var(--ink);
  background: color-mix(in srgb, var(--ink) 4%, transparent);
}
details.collapsible[open] summary {
  border-bottom: 1px solid var(--hairline);
}
details.collapsible .coll-body {
  padding: .75rem 1.1rem 1rem;
}
details.collapsible .coll-body .tw {
  margin: .5rem 0 1rem;
}

/* Tarjetas de Forma física */
.fit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 1rem;
  margin: 1.25rem 0 1.75rem;
}
.fit-card {
  border: 1px solid var(--hairline);
  border-radius: 10px;
  padding: .9rem 1rem;
  background: color-mix(in srgb, var(--paper) 80%, var(--grid));
  display: flex;
  flex-direction: column;
  gap: .25rem;
}
.fit-label {
  font-size: .72rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: .04em;
}
.fit-val {
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -.03em;
  color: var(--ink);
  line-height: 1.15;
}
.fit-sub {
  font-size: .76rem;
  color: var(--ink2);
}

/* Tablas */
.tw { overflow-x: auto; margin: 1.25rem 0 2rem; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; }
th, td { padding: .6rem .9rem .6rem 0; white-space: nowrap;
         border-bottom: 1px solid var(--grid); }
th { text-align: left; color: var(--muted); font-weight: 600; font-size: .68rem;
     text-transform: uppercase; letter-spacing: .06em;
     border-bottom: 1px solid var(--hairline); }
tbody tr:last-child td { border-bottom: 1px solid var(--hairline); }
.zones { display: flex; gap: 1px; width: 5rem; height: 5px; border-radius: 980px;
         overflow: hidden; background: var(--grid); }
.zones i { display: block; }
.z1 { background: var(--ph-3); } .z2 { background: var(--accent); }
.z3 { background: var(--ring-good); } .z4 { background: var(--ring-warn); }
.z5 { background: var(--ring-bad); }
.zt { display: block; font-size: .68rem; color: var(--muted); margin-top: 3px; }

/* Gráficas */
.chart { margin: 1.5rem 0 2.5rem; }
.pair { display: grid; gap: 1.5rem 2.5rem;
        grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr)); }
.pair .tick { font-size: 19px; }
.pair .dot { r: 5; }
.chart.square { max-width: 24rem; }
.chart.wheel { max-width: 20rem; }
figcaption { font-size: 1.05rem; font-weight: 600; letter-spacing: -.02em;
             margin-bottom: .35rem; }
figcaption.note { font-size: .76rem; font-weight: 400; color: var(--muted);
                  margin: .5rem 0 0; letter-spacing: 0; }
.chart svg { width: 100%; height: auto; display: block; overflow: visible; }
.legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: .76rem;
          color: var(--ink2); margin-bottom: .7rem; }
.lg { display: inline-flex; align-items: center; gap: .4rem; }
.lg i { width: .7rem; height: .7rem; border-radius: 2px; }
.grid { stroke: var(--grid); stroke-width: 1; }
.median { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 3 3; }
.tick { fill: var(--muted); font-size: 11px; font-family: inherit; }
.tick.strong { fill: var(--ink); font-weight: 600; }
.tick.short { fill: var(--bad); font-weight: 600; }
.line { fill: none; stroke: var(--ink); stroke-width: 2;
        stroke-linejoin: round; stroke-linecap: round; }
.line.stress { stroke: var(--accent-warm); stroke-width: 1.5; }
.dot { fill: var(--ink); stroke: var(--paper); stroke-width: 2; cursor: pointer; }
.dot.stress { fill: var(--accent-warm); }
.dot.last { fill: var(--accent); }
.trail { fill: none; stroke: var(--muted); stroke-width: 1.5; opacity: .55;
         stroke-linejoin: round; }
.q-good { fill: var(--ring-good); opacity: .07; }
.q-bad { fill: var(--ring-bad); opacity: .07; }
.quad-label { font-size: 11px; font-weight: 600; font-family: inherit; }
.quad-label.good { fill: var(--good); }
.quad-label.bad { fill: var(--bad); }
.quad-label.warn { fill: var(--warn); }
.quad-label.info { fill: var(--accent); }
.band-range { fill: var(--ring-good); opacity: .12; }
.band-line { stroke: var(--ring-good); stroke-width: 1; stroke-dasharray: 4 3; opacity: .65; }
.swc-band { fill: var(--ring-good); opacity: .10; }
.spo2-bar { fill: var(--accent); opacity: .45; }
.line.resp { fill: none; stroke: var(--ph-2); stroke-width: 1.8; }
.tick.resp { fill: var(--ph-2); }
.dot.resp { fill: var(--ph-2); stroke: var(--paper); stroke-width: 1.5; }
.int-bar { fill: var(--ink); opacity: .65; }
.int-bar.good { fill: var(--ring-good); opacity: .85; }
.ph-deep { fill: var(--ph-1); } .ph-rem { fill: var(--ph-2); }
.ph-light { fill: var(--ph-3); } .ph-awake { fill: var(--ph-4); }
.night-outline { fill: none; stroke: var(--paper); stroke-width: 1.5; }
.bb-range { fill: var(--bb); opacity: .3; }
.wheel-hub { fill: none; stroke: var(--grid); stroke-width: 1; }
.wheel-goal { fill: none; stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; }
.wedge { fill: var(--ink); }
.wedge.good { fill: var(--ring-good); }
.wheel-val { fill: var(--ink); font-size: 20px; font-weight: 700;
             letter-spacing: -.03em; font-family: inherit; }

/* Sincronización entre gráficas */
.is-synced-active {
  stroke-width: 3.5 !important;
  stroke: var(--accent) !important;
  fill: var(--accent) !important;
  filter: drop-shadow(0 0 4px var(--accent));
  transition: all 0.15s ease;
}
rect.is-synced-active {
  stroke-width: 2 !important;
  stroke: var(--ink) !important;
  opacity: 1 !important;
}

/* Tooltip flotante enriquecido */
.tooltip-popover {
  position: fixed; z-index: 90;
  pointer-events: none;
  background: var(--ink); color: var(--paper);
  padding: 0.45rem 0.75rem; border-radius: 6px;
  font-size: 0.76rem; line-height: 1.35;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
  opacity: 0; transform: translateY(4px);
  transition: opacity 0.12s ease, transform 0.12s ease;
  white-space: pre-line; max-width: 18rem;
}
.tooltip-popover.is-visible {
  opacity: 1; transform: translateY(0);
}

/* Modal de Glosario */
.modal-backdrop {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: none;
  align-items: center; justify-content: center;
  padding: 1.5rem;
}
.modal-backdrop.is-open { display: flex; }
.modal-dialog {
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: 14px;
  width: 100%; max-width: 48rem;
  max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}
.modal-header {
  padding: 1.2rem 1.5rem;
  border-bottom: 1px solid var(--hairline);
  display: flex; align-items: center; justify-content: space-between;
}
.modal-header h3 { margin: 0; font-size: 1.1rem; text-transform: none; color: var(--ink); }
.modal-close {
  background: none; border: none; font-size: 1.2rem;
  color: var(--muted); cursor: pointer; padding: 0.2rem 0.5rem; border-radius: 6px;
}
.modal-close:hover { color: var(--ink); background: var(--surface); }
.modal-filter-bar {
  padding: 0.9rem 1.5rem;
  border-bottom: 1px solid var(--grid);
  display: flex; flex-direction: column; gap: 0.75rem;
}
#glossary-search {
  width: 100%; padding: 0.55rem 0.85rem;
  border: 1px solid var(--hairline); border-radius: 8px;
  font-size: 0.88rem; background: var(--surface); color: var(--ink);
  outline: none;
}
#glossary-search:focus { border-color: var(--accent); }
.glossary-categories { display: flex; gap: 0.45rem; flex-wrap: wrap; }
.cat-pill {
  border: 1px solid var(--hairline); background: var(--paper);
  color: var(--ink2); border-radius: 980px; padding: 0.2rem 0.65rem;
  font-size: 0.74rem; cursor: pointer;
}
.cat-pill.active { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.glossary-grid {
  padding: 1.5rem;
  overflow-y: auto;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
  gap: 1rem;
}
.glossary-card {
  border: 1px solid var(--hairline); border-radius: 10px;
  padding: 1rem 1.1rem; background: var(--surface);
  display: flex; flex-direction: column; gap: 0.4rem;
}
.glossary-card-header {
  display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem;
  margin-bottom: 0.2rem;
}
.glossary-card h4 { margin: 0; font-size: 0.92rem; font-weight: 700; color: var(--ink); }
.glossary-badge {
  font-size: 0.68rem; font-weight: 600; text-transform: uppercase;
  color: var(--muted); letter-spacing: 0.04em;
}
.glossary-card p { margin: 0.15rem 0; font-size: 0.82rem; line-height: 1.4; color: var(--ink2); }
.glossary-card p strong { color: var(--ink); }
.glossary-range {
  margin-top: 0.35rem; padding-top: 0.35rem;
  border-top: 1px dashed var(--hairline); font-size: 0.78rem; color: var(--accent);
}

/* Modo Impresión / PDF */
@media print {
  body {
    background: #ffffff !important;
    color: #000000 !important;
    padding: 0 !important;
    font-size: 11pt !important;
  }
  .topbar, .theme-btn, .nav-btn, .modal-backdrop, .tooltip-popover, #theme-btn, #glossary-btn, #print-btn {
    display: none !important;
  }
  .wrap { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
  .lede { padding: 1rem 0 !important; }
  .sec {
    display: block !important;
    padding: 1.25rem 0 0.5rem !important;
    page-break-inside: avoid;
    break-inside: avoid;
  }
  .sec-rail { position: static !important; margin-bottom: 0.5rem !important; }
  .sec-rail h2 { font-size: 1.2rem !important; margin: 0 0 0.5rem !important; }
  .hero, .tiles, .chart, .pair, .status-card, .fit-grid {
    page-break-inside: avoid;
    break-inside: avoid;
  }
  details.collapsible {
    border: 1px solid #d2d2d7 !important;
    page-break-inside: auto;
  }
  details.collapsible summary::before { display: none !important; }
  details.collapsible summary { background: #f5f5f7 !important; color: #000 !important; }
  .chart svg { max-width: 100% !important; height: auto !important; }
}
"""

THEME_JS = """
(function () {
  var root = document.documentElement, key = 'biodelta-theme';
  var btn = document.getElementById('theme-btn');
  var isEs = (document.documentElement.lang || 'en') === 'es';
  function paint(t) {
    root.dataset.theme = t;
    if (btn) {
      btn.textContent = t === 'dark'
        ? (isEs ? '☀ Claro' : '☀ Light')
        : (isEs ? '☾ Oscuro' : '☾ Dark');
      btn.setAttribute('aria-pressed', t === 'dark');
    }
  }
  paint(root.dataset.theme === 'dark' ? 'dark' : 'light');
  if (btn) {
    btn.addEventListener('click', function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      paint(next);
      try { localStorage.setItem(key, next); } catch (e) {}
    });
  }

  // 1. Sincronización de días entre gráficas y Tooltips
  var tip = document.getElementById('biodelta-tooltip');
  function showTip(text, x, y) {
    if (!tip || !text) return;
    tip.textContent = text;
    tip.classList.add('is-visible');
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var px = Math.min(Math.max(x - tw / 2, 10), window.innerWidth - tw - 10);
    var py = (y - th - 12 < 10) ? y + 20 : y - th - 12;
    tip.style.left = px + 'px';
    tip.style.top = py + 'px';
  }
  function hideTip() {
    if (tip) tip.classList.remove('is-visible');
  }

  document.addEventListener('mouseover', function (e) {
    var target = e.target.closest('[data-day-idx]');
    if (!target) return;
    var idx = target.getAttribute('data-day-idx');
    var dayText = target.getAttribute('data-day') || '';
    var tipText = target.getAttribute('data-tip') || (target.querySelector('title') ? target.querySelector('title').textContent : dayText);
    
    document.querySelectorAll('[data-day-idx="' + idx + '"]').forEach(function (el) {
      el.classList.add('is-synced-active');
    });
    var rect = target.getBoundingClientRect();
    showTip(tipText, rect.left + rect.width / 2, rect.top);
  });

  document.addEventListener('mouseout', function (e) {
    var target = e.target.closest('[data-day-idx]');
    if (!target) return;
    var idx = target.getAttribute('data-day-idx');
    document.querySelectorAll('[data-day-idx="' + idx + '"]').forEach(function (el) {
      el.classList.remove('is-synced-active');
    });
    hideTip();
  });

  // 2. Glosario Modal
  var gModal = document.getElementById('glossary-modal');
  var gBtn = document.getElementById('glossary-btn');
  var gClose = document.getElementById('glossary-close');
  var gSearch = document.getElementById('glossary-search');
  var gPills = document.querySelectorAll('.cat-pill');

  function openGlossary() {
    if (!gModal) return;
    gModal.classList.add('is-open');
    gModal.setAttribute('aria-hidden', 'false');
    if (gSearch) { gSearch.value = ''; gSearch.focus(); filterCards(); }
  }
  function closeGlossary() {
    if (!gModal) return;
    gModal.classList.remove('is-open');
    gModal.setAttribute('aria-hidden', 'true');
  }
  if (gBtn) gBtn.addEventListener('click', openGlossary);
  if (gClose) gClose.addEventListener('click', closeGlossary);
  if (gModal) {
    gModal.addEventListener('click', function (e) {
      if (e.target === gModal) closeGlossary();
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeGlossary();
  });

  var currentCat = 'all';
  function filterCards() {
    var query = (gSearch ? gSearch.value : '').toLowerCase().trim();
    document.querySelectorAll('.glossary-card').forEach(function (card) {
      var cat = card.getAttribute('data-category');
      var matchCat = (currentCat === 'all' || cat === currentCat);
      var matchText = !query || card.textContent.toLowerCase().includes(query);
      card.style.display = (matchCat && matchText) ? 'flex' : 'none';
    });
  }

  if (gSearch) gSearch.addEventListener('input', filterCards);
  gPills.forEach(function (pill) {
    pill.addEventListener('click', function () {
      gPills.forEach(function (p) { p.classList.remove('active'); });
      pill.classList.add('active');
      currentCat = pill.getAttribute('data-cat') || 'all';
      filterCards();
    });
  });

})();
"""

# Se ejecuta antes de pintar nada: si el tema guardado es el oscuro, entra ya
# oscuro en vez de parpadear en blanco. El claro es el de serie.
THEME_BOOT = ("try{var t=localStorage.getItem('biodelta-theme')||localStorage.getItem('garmin-report-theme');"
              "if(t==='dark')document.documentElement.dataset.theme='dark'}catch(e){}")


def logo_svg() -> str:
    """El logo en línea: sin xmlns y con trazo en currentColor."""
    try:
        svg = (LOGO_DIR / "logo.svg").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    svg = re.sub(r'\s*xmlns="[^"]*"', "", svg)
    return svg.replace("<svg", '<svg class="logo" aria-hidden="true"', 1)


def favicon_link() -> str:
    """Favicon incrustado en base64: un `data:` no sale a la red."""
    try:
        png = (LOGO_DIR / "favicon-64.png").read_bytes()
    except OSError:
        return ""
    b64 = base64.b64encode(png).decode("ascii")
    return f'<link rel="icon" type="image/png" href="data:image/png;base64,{b64}">\n'


def _navbar(title: str, body: str, lang: str = "en") -> str:
    """Índice construido con las secciones que ya haya generado el md."""
    is_es = lang == "es"
    _NAV_LABELS = {
        "FC reposo + HRV nocturno": "FC reposo + HRV",
        "Respiración y SpO2 nocturnos": "Respiración y SpO2",
        "Resting HR + Overnight HRV": "Resting HR + HRV",
        "Overnight Respiration & SpO2": "Respiration & SpO2",
        "Session Breakdown": "Sessions",
        "Detalle de sesiones": "Sesiones",
    }
    links = "".join(
        f'<a href="#{sid}">{_NAV_LABELS.get(name, name)}</a>'
        for sid, name in re.findall(
            r'<section class="sec" id="([^"]+)">.*?<h2>(.*?)</h2>', body)
    )
    glossary_lbl = "📖 Glosario" if is_es else "📖 Glossary"
    print_lbl = "🖨️ Imprimir" if is_es else "🖨️ Print"
    theme_lbl = "☾ Oscuro" if is_es else "☾ Dark"

    return (
        '<nav class="topbar"><div class="topbar-in">'
        f'<span class="brand">{_esc(title)}</span>'
        f'<div class="navlinks">{links}</div>'
        f'<button id="glossary-btn" class="nav-btn" type="button" aria-label="{glossary_lbl}">{glossary_lbl}</button>'
        f'<button id="print-btn" class="nav-btn" type="button" onclick="window.print()" aria-label="{print_lbl}">{print_lbl}</button>'
        f'<button id="theme-btn" class="theme-btn" type="button" aria-pressed="false">{theme_lbl}</button>'
        '</div></nav>'
    )


def render(md: str, sleep_rows, stress_map, bb_map, steps_map, start: date, end: date,
           tiles=(), rings=(), baselines=None, intensity_map=None, vo2max=None, race_pred=None,
           traffic_light=None, lang: str = "en", goals: dict | None = None,
           standalone: bool = True) -> str:
    """Informe HTML completo.

    `standalone=False` deja fuera la barra superior y el glosario: el panel web
    monta el informe dentro de un iframe y ya pone los suyos. Sigue siendo un
    documento entero — así su CSS y sus IDs no se mezclan con los del panel.
    """
    charts = build_charts(sleep_rows, stress_map, bb_map, steps_map, start, end,
                          baselines, intensity_map=intensity_map, vo2max=vo2max,
                          race_pred=race_pred, lang=lang, goals=goals)
    # Semáforo de estado, anillos y cifras se inyectan bajo el `## Resumen` o `## Summary`
    resumen_parts = []
    if traffic_light:
        resumen_parts.append(status_card_html(traffic_light, lang=lang))
    if rings:
        resumen_parts.append(rings_html(rings))
    if tiles:
        resumen_parts.append(tiles_html(tiles))
    if resumen_parts:
        summary_html = "".join(resumen_parts)
        charts["Resumen"] = summary_html
        charts["Summary"] = summary_html

    title = f"Garmin log {start.isoformat()} – {end.isoformat()}"
    body = md_to_html(md, charts, lang=lang)
    body = body.replace("<h1>", f"<h1>{logo_svg()}", 1)
    head, _, rest = body.partition('<section class="sec"')
    body = (f'<header class="lede">{head}</header><section class="sec"{rest}'
            if rest else f'<header class="lede">{head}</header>')
    return (
        f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{_esc(title)}</title>\n'
        + favicon_link()
        + f'<style>{CSS}</style>\n'
        f'<script>{THEME_BOOT}</script>\n</head>\n<body>\n'
        + (_navbar(title, body, lang=lang) if standalone else "")
        + '<main class="wrap">\n' + body + '\n</main>\n'
        + (glossary_modal_html(lang=lang) if standalone else "")
        + tooltip_html()
        + f'<script>{THEME_JS}</script>\n</body>\n</html>\n'
    )
