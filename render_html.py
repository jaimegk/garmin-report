"""Vista HTML del informe: las tablas del markdown más gráficas SVG.

El .md lo genera generate_report.generate_md() y está pensado para una IA; este
módulo produce la versión legible por un humano a partir de ese mismo texto,
insertando gráficas construidas desde las series diarias originales.

Sin dependencias: solo stdlib, SVG inline y CSS. El fichero resultante se abre
con doble clic y funciona offline.
"""

import html as _html
import re
from datetime import date, timedelta

# Paleta categórica validada para fondo claro y oscuro (contraste, banda de
# luminosidad y separación para daltonismo). Las gráficas la referencian por
# variable CSS, así que el tema oscuro solo cambia la definición de arriba.
SERIES = ("var(--series-1)", "var(--series-2)", "var(--series-3)")

# Geometría común de todas las gráficas. viewBox fijo + width:100% => escalan
# con el contenedor sin recalcular nada.
W, H = 720, 170
PAD_L, PAD_R, PAD_T, PAD_B = 46, 10, 14, 26
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B


# ---------------------------------------------------------------------------
# Helpers de SVG
# ---------------------------------------------------------------------------

def _esc(s) -> str:
    return _html.escape(str(s), quote=True)


def _nice_bounds(values, from_zero: bool, ylim=None):
    """Rango del eje Y: bonito, con margen, y nunca degenerado.

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


def _grid(lo: float, hi: float, fmt) -> str:
    """Tres líneas horizontales con su etiqueta. Recesivas, por detrás."""
    out = []
    for frac in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * frac
        y = PAD_T + PLOT_H * (1 - frac)
        out.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{PAD_L - 6}" y="{y + 3.5:.1f}" class="tick" text-anchor="end">{_esc(fmt(v))}</text>'
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


def _legend(names, colors) -> str:
    """Leyenda: obligatoria con 2+ series, innecesaria con una (el título basta)."""
    if len(names) < 2:
        return ""
    items = "".join(
        f'<span class="lg"><i style="background:{colors[i]}"></i>{_esc(name)}</span>'
        for i, name in enumerate(names)
    )
    return f'<div class="legend">{items}</div>'


def _frame(title: str, body: str, names=(), colors=()) -> str:
    return (
        f'<figure class="chart"><figcaption>{_esc(title)}</figcaption>'
        f'{_legend(names, colors)}'
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(title)}">{body}</svg>'
        f'</figure>'
    )


def svg_bars(title, labels, stacks, names, unit="", fmt=None) -> str:
    """Barras (apiladas si hay varias series). Siempre desde cero.

    stacks: una lista de valores por serie, todas de la longitud de labels.
    Un None es un día sin dato: no dibuja segmento.
    """
    fmt = fmt or (lambda v: f"{v:,.0f}".replace(",", "."))
    totals = [
        sum(s[i] for s in stacks if s[i] is not None) or None
        if any(s[i] is not None for s in stacks) else None
        for i in range(len(labels))
    ]
    lo, hi = _nice_bounds(totals, from_zero=True)
    colors = SERIES[:len(stacks)]

    slot = PLOT_W / len(labels) if labels else PLOT_W
    bw = min(slot * 0.62, 46)
    parts = [_grid(lo, hi, fmt), _xlabels(labels)]

    for i, lab in enumerate(labels):
        cx = PAD_L + slot * (i + 0.5)
        base = PAD_T + PLOT_H  # apilamos hacia arriba desde la línea de cero
        for j, serie in enumerate(stacks):
            v = serie[i]
            if not v:
                continue
            h = PLOT_H * (v / (hi - lo))
            if h < 1:
                continue
            top = base - h
            tip = f"{lab} · {names[j]}: {fmt(v)}{unit}" if len(stacks) > 1 else f"{lab}: {fmt(v)}{unit}"
            parts.append(
                f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}"'
                f' rx="3" fill="{colors[j]}"><title>{_esc(tip)}</title></rect>'
            )
            base = top - 2  # 2px de fondo entre segmentos apilados
    return _frame(title, "".join(parts), names, colors)


def svg_line(title, labels, values, name, unit="", fmt=None, band=None, band_name="", ylim=None) -> str:
    """Una serie temporal. Escala ajustada a los datos (no forzada a cero).

    band: (bajos, altos) opcional para dibujar un rango sombreado detrás,
    en la misma escala y unidad que la serie.
    ylim: rango físico de la métrica, si lo tiene (p. ej. (0, 100)).
    """
    fmt = fmt or (lambda v: f"{v:,.0f}".replace(",", "."))
    pool = list(values)
    if band:
        pool += list(band[0]) + list(band[1])
    lo, hi = _nice_bounds(pool, from_zero=False, ylim=ylim)

    slot = PLOT_W / len(labels) if labels else PLOT_W
    def px(i): return PAD_L + slot * (i + 0.5)
    def py(v): return PAD_T + PLOT_H * (1 - (v - lo) / (hi - lo))

    parts = [_grid(lo, hi, fmt), _xlabels(labels)]

    if band:
        lows, highs = band
        idx = [i for i in range(len(labels)) if lows[i] is not None and highs[i] is not None]
        if idx:
            top = " ".join(f"{px(i):.1f},{py(highs[i]):.1f}" for i in idx)
            bottom = " ".join(f"{px(i):.1f},{py(lows[i]):.1f}" for i in reversed(idx))
            parts.append(f'<polygon points="{top} {bottom}" fill="{SERIES[0]}" opacity="0.16"/>')

    # Cada tramo continuo es un path propio: un día sin dato deja hueco real,
    # no una recta inventada entre los dos días que lo rodean.
    run = []
    for i, v in enumerate(values):
        if v is None:
            if len(run) > 1:
                parts.append(f'<polyline points="{" ".join(run)}" class="line" stroke="{SERIES[1]}"/>')
            run = []
        else:
            run.append(f"{px(i):.1f},{py(v):.1f}")
    if len(run) > 1:
        parts.append(f'<polyline points="{" ".join(run)}" class="line" stroke="{SERIES[1]}"/>')

    for i, v in enumerate(values):
        if v is None:
            continue
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4.5" fill="{SERIES[1]}" class="dot">'
            f'<title>{_esc(f"{labels[i]}: {fmt(v)}{unit}")}</title></circle>'
        )
    names = (name, band_name) if band and band_name else (name,)
    return _frame(title, "".join(parts), names, (SERIES[1], SERIES[0]))


# ---------------------------------------------------------------------------
# Gráficas del informe
# ---------------------------------------------------------------------------

def build_charts(sleep_rows, stress_map, bb_map, steps_map, start: date, end: date) -> dict:
    """Devuelve {título de sección → svg}, alineado día a día con las tablas."""
    # Mismo desfase que generate_md: la noche se cuelga del día en que te acostaste.
    sleep_by_date = {
        (date.fromisoformat(n.calendar_date) - timedelta(days=1)).isoformat(): n
        for n in sleep_rows
    }
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    keys = [d.isoformat() for d in days]
    labels = [f"{d.day}/{d.month}" for d in days]
    nights = [sleep_by_date.get(k) for k in keys]

    def hours(sec): return round(sec / 3600, 2) if sec else None
    def h_fmt(v): return f"{int(v)}h{round((v - int(v)) * 60):02d}"

    charts = {}

    deep = [hours(n.deep_s) if n else None for n in nights]
    rem = [hours(n.rem_s) if n else None for n in nights]
    light = [hours(n.light_s) if n else None for n in nights]
    if any(v is not None for v in deep + rem + light):
        charts["Sueño"] = svg_bars(
            "Fases del sueño por noche", labels, [deep, rem, light],
            ("Profundo", "REM", "Ligero"), fmt=h_fmt,
        )

    rhr = [n.rhr if n else None for n in nights]
    hrv = [n.hrv if n else None for n in nights]
    # Dos gráficas y no dos líneas: bpm y ms son escalas distintas, superponerlas
    # en un eje compartido haría parecer que se cruzan cuando no significan nada.
    pair = []
    if any(v is not None for v in rhr):
        pair.append(svg_line("FC en reposo", labels, rhr, "FC reposo", unit=" bpm"))
    if any(v is not None for v in hrv):
        pair.append(svg_line("HRV nocturno", labels, hrv, "HRV", unit=" ms"))
    if pair:
        charts["FC reposo + HRV nocturno"] = "".join(pair)

    stress = [stress_map.get(k) for k in keys]
    bb_hi = [bb_map[k][0] if k in bb_map else None for k in keys]
    bb_lo = [bb_map[k][1] if k in bb_map else None for k in keys]
    if any(v is not None for v in stress):
        charts["Estrés y Body Battery"] = svg_line(
            "Estrés medio, sobre el rango diario de Body Battery",
            labels, stress, "Estrés",
            band=(bb_lo, bb_hi), band_name="Body Battery (mín–máx)",
            ylim=(0, 100),  # ambas métricas son porcentajes por definición
        )

    steps = [steps_map.get(k) for k in keys]
    if any(v is not None for v in steps):
        charts["Actividad"] = svg_bars("Pasos por día", labels, [steps], ("Pasos",))

    return charts


def tiles_html(tiles) -> str:
    """Cabecera de un vistazo: una tarjeta por métrica del resumen.

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


def _inline(text: str) -> str:
    out = _esc(text.strip())
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", out)
    return out


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
        out += [f"<td{style(i)}>{_inline(c)}</td>" for i, c in enumerate(_cells(row))]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def md_to_html(md: str, charts: dict | None = None) -> str:
    """Convierte el markdown del informe, inyectando cada gráfica tras su `##`."""
    charts = charts or {}
    out, table, bullets = [], [], []

    def flush():
        if table:
            out.append(_table(table))
            table.clear()
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_inline(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|"):
            if not (table and _is_sep(stripped) and len(table) > 1):
                table.append(stripped)
            continue
        flush()

        if not stripped:
            continue
        if re.fullmatch(r"-{3,}", stripped):
            out.append("<hr>")
        elif stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            title = stripped[3:].strip()
            out.append(f"<h2>{_inline(title)}</h2>")
            if title in charts:
                out.append(charts[title])
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            bullets.append(stripped[2:])
        else:
            out.append(f"<p>{_inline(stripped)}</p>")

    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

CSS = """
:root {
  color-scheme: light;
  --bg: #fcfcfb; --card: #ffffff; --ink: #0b0b0b; --ink2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --good: #10794f; --bad: #b8420f;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #1a1a19; --card: #222221; --ink: #ffffff; --ink2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --good: #35b487; --bad: #f0794a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 2rem 1.25rem 4rem; max-width: 60rem;
  background: var(--bg); color: var(--ink);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 .25rem; }
h2 { font-size: 1.25rem; margin: 2.5rem 0 .75rem; padding-bottom: .3rem; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.05rem; margin: 1.75rem 0 .5rem; color: var(--ink2); }
p { margin: .6rem 0; }
em { color: var(--ink2); font-style: normal; font-size: .9rem; }
hr { border: 0; border-top: 1px solid var(--border); margin: 1.5rem 0; }
ul { margin: .6rem 0; padding-left: 1.2rem; }
li { margin: .3rem 0; }

.tw { overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { padding: .4rem .6rem; white-space: nowrap; border-bottom: 1px solid var(--border); }
th { text-align: left; color: var(--ink2); font-weight: 600; }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--ink) 4%, transparent); }

.tiles { display: grid; gap: .6rem; margin: 1.25rem 0 1.75rem;
         grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr)); }
.tile { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
        padding: .7rem .85rem; }
.tile .k { font-size: .72rem; color: var(--muted); text-transform: uppercase;
           letter-spacing: .04em; line-height: 1.25; min-height: 2.5em; }
.tile .v { font-size: 1.5rem; font-weight: 650; line-height: 1.2; margin: .15rem 0 .1rem; }
.tile .t { font-size: .85rem; color: var(--ink2); min-height: 1.2em; }
.tile .t.good { color: var(--good); font-weight: 600; }
.tile .t.bad { color: var(--bad); font-weight: 600; }

.chart { margin: 1.25rem 0 1.75rem; padding: .9rem 1rem 1rem; background: var(--card);
         border: 1px solid var(--border); border-radius: 10px; }
.chart + .chart { margin-top: -.5rem; }
figcaption { font-size: .85rem; font-weight: 600; color: var(--ink2); margin-bottom: .3rem; }
.chart svg { width: 100%; height: auto; display: block; overflow: visible; }
.legend { display: flex; flex-wrap: wrap; gap: .9rem; font-size: .8rem; color: var(--ink2); margin-bottom: .5rem; }
.lg { display: inline-flex; align-items: center; gap: .35rem; }
.lg i { width: .7rem; height: .7rem; border-radius: 2px; }
.grid { stroke: var(--grid); stroke-width: 1; }
.tick { fill: var(--muted); font-size: 11px; font-family: inherit; }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.dot { stroke: var(--card); stroke-width: 2; }
"""


def render(md: str, sleep_rows, stress_map, bb_map, steps_map, start: date, end: date,
           tiles=()) -> str:
    charts = build_charts(sleep_rows, stress_map, bb_map, steps_map, start, end)
    # Las tarjetas se inyectan como el resto: justo debajo del `## Resumen`.
    if tiles:
        charts["Resumen"] = tiles_html(tiles)
    title = f"Garmin log {start.isoformat()} – {end.isoformat()}"
    return (
        "<!doctype html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{_esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        + md_to_html(md, charts)
        + "\n</body>\n</html>\n"
    )
