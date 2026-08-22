# Development notes

Notes for anyone touching this repo, including future me. Everything here is the
kind of thing that is expensive to rediscover.

## Setup and tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python test_report.py
```

No test framework on purpose: plain `assert` and a loop over `test_*` at the bottom
of the file. Adding pytest would mean a dependency for twelve assertions.

Most tests are pure functions. The one that matters is
`test_demo_pipeline_end_to_end`: it builds the synthetic database and runs the whole
pipeline, which is the only thing that exercises the ~20 `query_*` functions and the
395-line `generate_md`. If you change SQL, that is the test that will catch you.

## Regenerating the published example

`docs/index.html` and `docs/ejemplo_garmin_log.md` are the output of the demo mode.
They do **not** regenerate themselves, so after any change to the report, run:

```bash
.venv/bin/python generate_report.py --demo
cp output/garmin_log_2026-06-15_2026-06-21.html docs/index.html
cp output/garmin_log_2026-06-15_2026-06-21.md   docs/ejemplo_garmin_log.md
```

The demo is deterministic — fixed seed, fixed dates, fixed "generated on" date — so a
clean checkout reproduces those files byte for byte. If a diff shows up that you did
not expect, something changed in the report. That is the point.

`docs/screenshot.png` (light), `docs/screenshot-dark.png` (the same view with the
theme switched) and `docs/screenshot-charts.png` are manual captures of that same
HTML. Retake them when the layout changes visibly, not on every data tweak — and
retake the pair together, or the README's light/dark `<picture>` shows two
different reports.

## Before publishing: the clean-checkout check

The repo once shipped broken because `render_html.py` was imported but never
`git add`ed — everything worked locally and nothing worked for anyone else. What
catches that class of bug is exporting the index and running it somewhere else:

```bash
git checkout-index -a -f --prefix=/tmp/check/
cd /tmp/check
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python test_report.py
.venv/bin/python generate_report.py --demo
```

Also worth a glance: `git ls-files` should never list a `.db`, a `.env`, anything
under `garmin_files/`, or a real report from `output/`.

## Garmin data model: the parts that bite

The schema comes from the `garmin-health-data` package, not from this repo. Run
`python generate_report.py --inspect-schema` against a real database to explore it,
and read the SQLAlchemy models directly for column types.

- **Sleep is indexed by wake-up day.** Garmin's `calendar_date` is the day you woke
  up; the report labels each night by the day you went to bed, so queries shift by a
  day in both directions. Get this wrong and every night lands on the wrong row.
- **Timestamps are UTC, and only some tables carry the offset.** `tz_offset_minutes`
  takes it from the most recent `sleep` (then `activity`) row and assumes it is
  stable across the period. A DST change inside a report would skew the daily
  aggregation by an hour.
- **Negative values are not measurements.** In `stress` and `body_battery`, `-1`
  means no reading and `-2` means "during an activity". Averaging them in silently
  drags every number down.
- **Intensity minutes live in `training_load`**, not in the `intensity_minutes`
  table, and Garmin already counts a vigorous minute twice — same as the WHO
  guideline the report compares against.
- **There is no per-lap minimum heart rate.** Garmin stores average and max only, so
  `add_min_hr` reconstructs it from the 1 Hz series in `activity_ts_metric`. Lap
  boundaries come from accumulating `total_elapsed_time` (wall clock, includes
  pauses), *not* `total_timer_time` — using the latter drifts further out of sync
  with every pause.
- **`garmin extract --end-date` is exclusive**, except when it equals `--start-date`.
  Hence the `+1 day` in `sync()`.
- **VO2max has two sources**: the `vo2_max` series and, as a fallback, the
  `user_profile` snapshot. Only outdoor GPS runs/walks (or cycling with a power
  meter) produce an estimate at all.

## Working on the demo data

`demo_data.py` creates its tables from `garmin_health_data.models.Base`, so the
schema never drifts from what `garmin extract` actually writes. Only the rows are
invented.

Two rules keep the example honest:

**It must be internally consistent.** Synthetic data gives itself away through
impossible combinations, and every one of these was a real bug in it: minimum lap
heart rate above the lap average, running cadence reported on a bike, identical HR
zone splits across every sport, 16,000 steps on a rest day, a week of intensity
minutes far outside the WHO range. The end-to-end test asserts min ≤ avg ≤ max for
every lap; the rest is judgement.

**It must trigger the signals.** The last week is deliberately bad — resting HR rises
and holds for three days before receding, HRV mirrors it, two nights fall under six
hours, bedtimes scatter. A demo where nothing happens demonstrates nothing. If you
retune the thresholds in `compute_flags`, re-check that the example still lights up.

## Conventions

- The generated report is in Spanish; code, comments and docs are in English.
  `README.es.md` mirrors `README.md`.
- The `.md` output is written to be pasted into an AI chat; the `.html` is written to
  be read by a human. When adding a section, ask which one it serves.
- The HTML must stay self-contained: no external requests, inline SVG and CSS.
  The end-to-end test asserts no `http://` or `https://` survives in it. The only
  script is the light/dark toggle.
- The logo in `assets/logo/` is embedded, never linked: `logo.svg` goes inline in
  the topbar (xmlns stripped — a namespace URL would trip the no-URL assertion —
  and `currentColor`, so one file serves both themes), `favicon-64.png` goes in as
  a base64 `data:` URI. Ship `assets/` or the report loses both, silently.
- `SUMMARY_SPECS` is the single source for the summary metrics — the weekly table,
  the multi-week table, the no-history table and the HTML cards all read from it.
