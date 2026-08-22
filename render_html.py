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


def _xlabels(labels) -> str:
    """Etiquetas del eje X, diezmadas si no caben sin solaparse."""
    n = len(labels)
    if not n:
        return ""
    step = max(1, round(n / 12))
    slot = PLOT_W / n
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
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4" class="dot">'
            f'<title>{_esc(f"{labels[i]}: {fmt(v)}{unit}")}</title></circle>'
        )
    return _frame(title, "".join(parts), note=band_label)


def svg_sleep_timeline(title, labels, nights, fmt_dur) -> str:
    """Cada noche en su hora real: cuándo te acostaste, cuándo te levantaste.

    Una barra apilada por noche solo dice cuánto dormiste. Puesta sobre el reloj
    dice además a qué hora, que es justo lo que mide la regularidad — y la
    irregularidad se ve como un escalón, sin tener que leer ninguna columna.
    """
    rows = [(lab, n) for lab, n in zip(labels, nights)]
    if not any(n for _l, n in rows):
        return ""
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
            f' class="tick">{_esc(lab)}</text>'
        )
        start, end = _parse_ts(n.start_ts) if n else None, _parse_ts(n.end_ts) if n else None
        if not (n and start and end and end > start):
            continue
        # Ancla: las 18:00 del día en que te acostaste (si te acuestas de
        # madrugada, el ancla es el día anterior).
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
        parts.append(f'<g><title>{_esc(tip)}</title>')
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
    for values, name in ((beds, "acostarse"), (wakes, "despertar")):
        med = _median(values)
        if med is None:
            continue
        x = px(med)
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad_t - 12:.1f}" x2="{x:.1f}"'
            f' y2="{pad_t + len(rows) * row_h:.1f}" class="median"/>'
            f'<text x="{x:.1f}" y="{pad_t - 15:.1f}" class="tick" text-anchor="middle">'
            f'mediana {_esc(name)}</text>'
        )

    items = [("Profundo", "var(--ph-1)"), ("REM", "var(--ph-2)"),
             ("Ligero", "var(--ph-3)"), ("Despierto", "var(--ph-4)")]
    return _frame(
        title, "".join(parts), items, vb=f"0 0 {W} {height}",
        note="El ancho de cada fase es proporcional a su total, no su orden real "
             "dentro de la noche.",
    )


def svg_recovery_map(title, labels, rhr, hrv, base_rhr, base_hrv, swc_low=None, swc_high=None) -> str:
    """FC en reposo contra HRV, unidas en orden cronológico.

    Las dos métricas cuentan la misma historia y siempre hay que cruzarlas a
    mano entre dos gráficas. Aquí cada noche es un punto y la semana es el
    recorrido: hacia la esquina de arriba a la izquierda, recuperando; hacia la
    de abajo a la derecha, acumulando fatiga.
    """
    idx = [i for i in range(len(labels)) if rhr[i] is not None and hrv[i] is not None]
    if len(idx) < 2 or not base_rhr or not base_hrv:
        return ""
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
    parts.extend([
        f'<rect x="{pl}" y="{pt}" width="{bx - pl:.1f}" height="{by - pt:.1f}" class="q-good"/>',
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{pl + pw - bx:.1f}" height="{pt + ph - by:.1f}" class="q-bad"/>',
        f'<text x="{pl + 12}" y="{pt + 18}" class="quad-label good">● RECUPERADO (FC baja / HRV alta)</text>',
        f'<text x="{pl + pw - 12}" y="{pt + ph - 10}" class="quad-label bad" text-anchor="end">● FATIGA / SOBRECARGA (FC alta / HRV baja)</text>',
        f'<text x="{pl + 12}" y="{pt + ph - 10}" class="quad-label warn">● Fatiga parasimpática (FC baja / HRV baja)</text>',
        f'<text x="{pl + pw - 12}" y="{pt + 18}" class="quad-label info" text-anchor="end">● Reactividad / Estrés (FC alta / HRV alta)</text>',
    ])

    # Ejes de la cruz basal
    parts.extend([
        f'<line x1="{bx:.1f}" y1="{pt}" x2="{bx:.1f}" y2="{pt + ph}" class="median"/>',
        f'<line x1="{pl}" y1="{by:.1f}" x2="{pl + pw}" y2="{by:.1f}" class="median"/>',
        f'<text x="{pl - 8}" y="{by + 4:.1f}" class="tick strong" text-anchor="end">{round(base_hrv)} ms</text>',
        f'<text x="{bx:.1f}" y="{pt + ph + 16}" class="tick strong" text-anchor="middle">{round(base_rhr)} bpm</text>',
        f'<text x="{pl + pw}" y="{h - 8}" class="tick" text-anchor="end">FC reposo (bpm) →</text>',
        f'<text x="{pl}" y="{pt - 10}" class="tick">↑ HRV nocturna (ms)</text>',
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
        lbl = f"{labels[i]} (hoy)" if last else labels[i]
        lbl_cls = "tick strong" if last else "tick"
        parts.append(
            f'<circle cx="{px(rhr[i]):.1f}" cy="{py(hrv[i]):.1f}" r="{dot_r}" class="{cls_dot}">'
            f'<title>{_esc(f"{labels[i]}: {round(rhr[i])} bpm · {round(hrv[i])} ms")}</title></circle>'
            f'<text x="{px(rhr[i]):.1f}" y="{py(hrv[i]) - (10 if last else 7):.1f}" class="{lbl_cls}" text-anchor="middle">{_esc(lbl)}</text>'
        )

    swc_note = f" · Banda SWC HRV: {round(swc_low)}–{round(swc_high)} ms" if (swc_low and swc_high) else ""
    return _frame(title, "".join(parts), vb=f"0 0 {w} {h}",
                  note=f"Cruz central: tus medias basales ({round(base_rhr)} bpm / {round(base_hrv)} ms){swc_note}.")


def svg_week_wheel(title, labels, values, goal=None, unit="") -> str:
    """Los días en círculo: una semana no es una recta, es un ciclo que se repite.

    Cada radio es un día; el anillo de puntos, el objetivo.
    """
    vals = [v for v in values if v]
    if not vals:
        return ""
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
            parts.append(
                f'<path d="M{x0o:.1f},{y0o:.1f} L{xa:.1f},{ya:.1f}'
                f' A{r:.1f},{r:.1f} 0 0 1 {xb:.1f},{yb:.1f} L{x1o:.1f},{y1o:.1f}'
                f' A{r0},{r0} 0 0 0 {x0o:.1f},{y0o:.1f} Z" class="wedge{good}">'
                f'<title>{_esc(f"{labels[i]}: {v:,.0f}{unit}".replace(",", "."))}</title></path>'
            )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" class="tick {cls}" text-anchor="middle">'
            f'{_esc(labels[i])}</text>'
        )
    avg = sum(vals) / len(vals)
    parts.append(
        f'<text x="{cx}" y="{cy - 2}" class="wheel-val" text-anchor="middle">'
        f'{_esc(f"{avg:,.0f}".replace(",", "."))}</text>'
        f'<text x="{cx}" y="{cy + 16}" class="tick" text-anchor="middle">media/día</text>'
    )
    note = f"Anillo punteado: {goal:,.0f} pasos.".replace(",", ".") if goal else ""
    return _frame(title, "".join(parts), vb=f"0 0 {size} {size}", cls="wheel", note=note)


def svg_battery_range(title, labels, lows, highs, stress) -> str:
    """Cuánta batería gastaste cada día (la barra) y con cuánto estrés (el punto).

    Body Battery no es un número, es un recorrido entre el mínimo y el máximo
    del día: dibujar solo la media escondería justo eso.
    """
    if not any(v is not None for v in stress) and not any(v is not None for v in highs):
        return ""
    lo, hi = 0.0, 100.0
    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py(v): return PAD_T + PLOT_H * (1 - (v - lo) / (hi - lo))

    parts = [_grid(lo, hi, lambda v: f"{v:.0f}"), _xlabels(labels)]
    bw = min(slot * 0.34, 18)
    for i, lab in enumerate(labels):
        if lows[i] is not None and highs[i] is not None:
            y0, y1 = py(highs[i]), py(lows[i])
            parts.append(
                f'<rect x="{px(i) - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}"'
                f' height="{max(y1 - y0, 2):.1f}" rx="{bw / 2:.1f}" class="bb-range">'
                f'<title>{_esc(f"{lab} · Body Battery {round(lows[i])}–{round(highs[i])}")}</title>'
                f'</rect>'
            )
    run = [f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(stress) if v is not None]
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line stress"/>')
    for i, v in enumerate(stress):
        if v is None:
            continue
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4" class="dot stress">'
            f'<title>{_esc(f"{labels[i]} · Estrés {round(v)}")}</title></circle>'
        )
    items = [("Body Battery (mín–máx)", "var(--bb)"), ("Estrés medio", "var(--accent-warm)")]
    return _frame(title, "".join(parts), items)


def svg_spo2_resp(title, labels, spo2_mins, spo2_avgs, resp_avgs) -> str:
    """SpO2 (rango mín–media en barra) y Frecuencia Respiratoria nocturna (línea)."""
    has_spo2 = any(v is not None for v in spo2_avgs)
    has_resp = any(v is not None for v in resp_avgs)
    if not has_spo2 and not has_resp:
        return ""

    lo_spo2, hi_spo2 = 85.0, 100.0
    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py_spo2(v): return PAD_T + PLOT_H * (1 - (v - lo_spo2) / (hi_spo2 - lo_spo2))

    resp_vals = [v for v in resp_avgs if v is not None]
    lo_resp, hi_resp = (min(resp_vals) - 1, max(resp_vals) + 1) if resp_vals else (10.0, 20.0)
    if hi_resp == lo_resp:
        hi_resp += 2
    def py_resp(v): return PAD_T + PLOT_H * (1 - (v - lo_resp) / (hi_resp - lo_resp))

    parts = [_grid(lo_spo2, hi_spo2, lambda v: f"{v:.0f}%"), _xlabels(labels)]

    y95 = py_spo2(95)
    parts.append(f'<line x1="{PAD_L}" y1="{y95:.1f}" x2="{W - PAD_R}" y2="{y95:.1f}" class="band-line" stroke="var(--accent)" stroke-dasharray="3,3" opacity="0.4"/>')

    bw = min(slot * 0.34, 18)
    for i, lab in enumerate(labels):
        s_min = spo2_mins[i]
        s_avg = spo2_avgs[i]
        if s_min is not None and s_avg is not None:
            y0, y1 = py_spo2(s_avg), py_spo2(s_min)
            parts.append(
                f'<rect x="{px(i) - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}"'
                f' height="{max(y1 - y0, 3):.1f}" rx="{bw / 2:.1f}" class="spo2-bar">'
                f'<title>{_esc(f"{lab} · SpO2 {round(s_min)}%–{round(s_avg)}%")}</title>'
                f'</rect>'
            )

    run = [f"{px(i):.1f},{py_resp(v):.1f}" for i, v in enumerate(resp_avgs) if v is not None]
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line resp"/>')
    for i, v in enumerate(resp_avgs):
        if v is None:
            continue
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py_resp(v):.1f}" r="4" class="dot resp">'
            f'<title>{_esc(f"{labels[i]} · Respiración {v:.1f} resp/min")}</title></circle>'
        )

    items = [("SpO2 mín–media", "var(--accent)"), ("Respiración media", "var(--ph-2)")]
    return _frame(title, "".join(parts), items, note="Línea punteada: referencia 95% SpO2.")


def svg_intensity_bars(title, labels, values, goal=None) -> str:
    """Minutos de intensidad diarios en barras, con la línea del objetivo diario.

    Misma geometría que el resto de series temporales: dentro de un `.pair` las
    etiquetas del eje escalan a 19px, y en un lienzo de 320 px se apelotonan
    hasta ser ilegibles.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
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
        parts.append(
            f'<rect x="{px(i) - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}"'
            f' height="{max(y_base - y, 2):.1f}" rx="3" class="int-bar{good}">'
            f'<title>{_esc(f"{labels[i]}: {round(v)} min")}</title></rect>'
        )

    tot = sum(v for v in values if v)
    note = (f"Línea: objetivo {round(goal)} min/día. " if goal else "")
    note += f"Total del periodo: {round(tot)} min (objetivo OMS: 150–300 min/sem)."
    return _frame(title, "".join(parts), note=note)


def fitness_cards_html(vo2max, race_pred) -> str:
    """Tarjetas visuales para VO2máx y ritmos previstos de carrera."""
    cards = []
    if vo2max:
        run_v, cyc_v, _vo2_date = vo2max
        if run_v:
            cards.append(
                f'<div class="fit-card"><span class="fit-label">VO2máx Carrera</span>'
                f'<span class="fit-val">{round(run_v)}</span>'
                f'<span class="fit-sub">ml/kg/min</span></div>'
            )
        if cyc_v:
            cards.append(
                f'<div class="fit-card"><span class="fit-label">VO2máx Ciclismo</span>'
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

        preds = [
            ("5K", fmt_time(t5), fmt_p(t5, 5.0)),
            ("10K", fmt_time(t10), fmt_p(t10, 10.0)),
            ("Media (21K)", fmt_time(thalf), fmt_p(thalf, 21.0975)),
            ("Maratón (42K)", fmt_time(tmar), fmt_p(tmar, 42.195)),
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
                 baselines=None, intensity_map=None, vo2max=None, race_pred=None) -> dict:
    """Devuelve {título de sección → svg}, alineado día a día con las tablas."""
    baselines = baselines or {}
    intensity_map = intensity_map or {}
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

    timeline = svg_sleep_timeline("Cada noche sobre el reloj", labels, nights, h_fmt)
    if timeline:
        charts["Sueño"] = timeline

    rhr = [n.rhr if n else None for n in nights]
    hrv = [n.hrv if n else None for n in nights]
    pair = []
    if any(v is not None for v in rhr):
        pair.append(svg_line("FC en reposo", labels, rhr, "FC reposo", unit=" bpm"))
    if any(v is not None for v in hrv):
        swc_lo = baselines.get("swc_low")
        swc_hi = baselines.get("swc_high")
        band = (swc_lo, swc_hi) if (swc_lo is not None and swc_hi is not None) else None
        band_note = f"Banda sombreada: tu rango normal ({round(swc_lo)}–{round(swc_hi)} ms)." if band else ""
        pair.append(svg_line("HRV nocturno", labels, hrv, "HRV", unit=" ms",
                             band=band, band_label=band_note))
    cardio = svg_recovery_map(
        "Mapa de recuperación de la semana", labels, rhr, hrv,
        baselines.get("rhr"), baselines.get("hrv"),
        baselines.get("swc_low"), baselines.get("swc_high"),
    )
    if pair:
        cardio += f'<div class="pair">{"".join(pair)}</div>'
    if cardio:
        charts["FC reposo + HRV nocturno"] = cardio

    # Respiración y SpO2 nocturnas
    spo2_mins = [n.spo2_min if n else None for n in nights]
    spo2_avgs = [n.spo2_avg if n else None for n in nights]
    resp_avgs = [n.resp_avg if n else None for n in nights]
    spo2_chart = svg_spo2_resp("SpO2 y Respiración nocturnas", labels, spo2_mins, spo2_avgs, resp_avgs)
    if spo2_chart:
        charts["Respiración y SpO2 nocturnos"] = spo2_chart

    stress = [stress_map.get(k) for k in keys]
    bb_hi = [bb_map[k][0] if k in bb_map else None for k in keys]
    bb_lo = [bb_map[k][1] if k in bb_map else None for k in keys]
    battery = svg_battery_range(
        "Body Battery y estrés, día a día", labels, bb_lo, bb_hi, stress)
    if battery:
        charts["Estrés y Body Battery"] = battery

    steps = [steps_map.get(k) for k in keys]
    wheel = svg_week_wheel("Pasos por día", labels, steps, goal=STEPS_GOAL)
    im_vals = [intensity_map.get(k, (None, None, None))[0] if intensity_map else None for k in keys]
    int_bars = svg_intensity_bars("Minutos de intensidad / día", labels, im_vals, goal=150 / 7)
    if wheel and int_bars:
        charts["Actividad"] = f'<div class="pair">{wheel}{int_bars}</div>'
    elif wheel:
        charts["Actividad"] = wheel

    fit_grid = fitness_cards_html(vo2max, race_pred)
    if fit_grid:
        charts["Forma física"] = fit_grid

    return charts


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


def md_to_html(md: str, charts: dict | None = None) -> str:
    """Convierte el markdown del informe en HTML gráfico y editorial.

    - Inyecta las gráficas SVG al inicio de cada sección `##`.
    - En la sección `Resumen`, enseña únicamente las Señales destacadas (las métricas
      ya están en los anillos de portada y tarjetas de cabecera).
    - Agrupa las tablas y notas contextuales detalladas en bloques `<details class="collapsible">`
      desplegables, manteniendo las cifras clave y gráficas inmediatamente a la vista.
    """
    charts = charts or {}
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

        if title == "Resumen":
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
            # Las tarjetas de cabecera solo cubren la semana actual: en un informe
            # multi-semana esta tabla es la única evolución que hay, y perderla
            # dejaría el HTML contando menos que el markdown.
            if res_table:
                out.append(
                    '<details class="collapsible"><summary>Métricas en detalle</summary>'
                    f'<div class="coll-body">{_table(res_table)}</div></details>'
                )
            out.append("</div></section>")
            continue

        if title == "Forma física":
            notes = []
            for l in content_lines:
                s = l.strip()
                if s.startswith("- "):
                    notes.append(s[2:])
                elif s and not re.fullmatch(r"-{3,}", s):
                    notes.append(s)
            if notes:
                out.append(
                    '<details class="collapsible"><summary>Notas sobre VO2máx y ritmos previstos</summary>'
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
            elif s.startswith("**Media") or s.startswith("**Intensidad"):
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
            summary_label = {
                "Sueño": "Desglose diario y contexto de sueño",
                "FC reposo + HRV nocturno": "Desglose diario de FC y HRV",
                "Respiración y SpO2 nocturnos": "Desglose diario y notas clínicas",
                "Estrés y Body Battery": "Desglose diario de estrés y Body Battery",
                "Actividad": "Desglose diario de actividad y sesiones",
            }.get(title, "Ver desglose diario y detalles")

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
             display: flex; align-items: center; gap: 1.25rem; }
.brand { font-size: .8rem; font-weight: 600; letter-spacing: -.01em; white-space: nowrap; }
.navlinks { display: flex; gap: 1.1rem; overflow-x: auto; scrollbar-width: none;
            flex: 1; }
.navlinks::-webkit-scrollbar { display: none; }
.navlinks a { color: var(--ink2); text-decoration: none; font-size: .76rem;
              white-space: nowrap; }
.navlinks a:hover { color: var(--ink); }
.theme-btn { margin-left: auto; border: 1px solid var(--hairline); background: none;
             color: var(--ink); border-radius: 980px; padding: .2rem .7rem;
             font: inherit; font-size: .74rem; cursor: pointer; white-space: nowrap; }
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

/* Cifras: hoja de especificaciones a dos columnas, sin cajas. En columnas
   (no en rejilla) porque las métricas son las que sean: una lista partida por
   la mitad nunca deja un hueco a media fila. */
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

/* Tablas: filetes, sin cajas ni cebra */
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
/* Al ir a media anchura el SVG se reduce casi a la mitad: sin compensar el
   tamaño, las etiquetas de los ejes quedan en 6 px y no se leen. */
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
.dot { fill: var(--ink); stroke: var(--paper); stroke-width: 2; }
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
"""

THEME_JS = """
(function () {
  var root = document.documentElement, key = 'garmin-report-theme';
  var btn = document.getElementById('theme-btn');
  function paint(t) {
    root.dataset.theme = t;
    btn.textContent = t === 'dark' ? '☀ Claro' : '☾ Oscuro';
    btn.setAttribute('aria-pressed', t === 'dark');
  }
  paint(root.dataset.theme === 'dark' ? 'dark' : 'light');
  btn.addEventListener('click', function () {
    var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    paint(next);
    try { localStorage.setItem(key, next); } catch (e) {}
  });
})();
"""

# Se ejecuta antes de pintar nada: si el tema guardado es el oscuro, entra ya
# oscuro en vez de parpadear en blanco. El claro es el de serie.
THEME_BOOT = ("try{var t=localStorage.getItem('garmin-report-theme');"
              "if(t==='dark')document.documentElement.dataset.theme='dark'}catch(e){}")


def logo_svg() -> str:
    """El logo en línea: sin xmlns (el parser de HTML ya lo asume, y una URL de
    espacio de nombres rompería la promesa de que aquí no hay ninguna URL) y con
    el trazo en currentColor, así hereda la tinta del tema en vez de necesitar
    una copia del fichero por cada color. Sin el fichero, no hay logo."""
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


def _navbar(title: str, body: str) -> str:
    """Índice construido con las secciones que ya haya generado el md."""
    links = "".join(
        f'<a href="#{sid}">{name}</a>'
        for sid, name in re.findall(
            r'<section class="sec" id="([^"]+)">.*?<h2>(.*?)</h2>', body)
    )
    return (
        '<nav class="topbar"><div class="topbar-in">'
        f'<span class="brand">{_esc(title)}</span>'
        f'<div class="navlinks">{links}</div>'
        '<button id="theme-btn" class="theme-btn" type="button" aria-pressed="false">'
        '☾ Oscuro</button>'
        '</div></nav>'
    )


def render(md: str, sleep_rows, stress_map, bb_map, steps_map, start: date, end: date,
           tiles=(), rings=(), baselines=None, intensity_map=None, vo2max=None, race_pred=None) -> str:
    charts = build_charts(sleep_rows, stress_map, bb_map, steps_map, start, end,
                          baselines, intensity_map=intensity_map, vo2max=vo2max, race_pred=race_pred)
    if rings or tiles:
        charts["Resumen"] = rings_html(rings) + tiles_html(tiles)
    title = f"Garmin log {start.isoformat()} – {end.isoformat()}"
    body = md_to_html(md, charts)
    body = body.replace("<h1>", f"<h1>{logo_svg()}", 1)
    head, _, rest = body.partition('<section class="sec"')
    body = (f'<header class="lede">{head}</header><section class="sec"{rest}'
            if rest else f'<header class="lede">{head}</header>')
    return (
        '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{_esc(title)}</title>\n'
        + favicon_link()
        + f'<style>{CSS}</style>\n'
        f'<script>{THEME_BOOT}</script>\n</head>\n<body>\n'
        + _navbar(title, body)
        + '<main class="wrap">\n' + body + '\n</main>\n'
        + f'<script>{THEME_JS}</script>\n</body>\n</html>\n'
    )
