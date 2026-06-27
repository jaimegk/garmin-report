# Garmin Weekly Report

Extrae tus datos de [Garmin Connect](https://connect.garmin.com) a una base de datos
SQLite local y genera un informe semanal en Markdown con sueño, frecuencia cardíaca en
reposo, HRV nocturno, estrés, Body Battery, actividades y pasos.

Además compara cada semana con tu **media de las ~4 semanas previas** y resalta
**señales** automáticas (FC reposo elevada varios días, HRV por debajo de lo habitual,
noches cortas, estrés alto…), para que el informe no sea solo un registro sino que te
diga qué merece atención.

Todo corre en local: tus credenciales y tus datos de salud nunca salen de tu máquina.

```
garmin extract (incremental)  →  garmin_data.db (SQLite)  →  output/garmin_log.md
```

## Ejemplo de salida

```markdown
# Garmin log — semana 2026-W25 (16 jun – 22 jun 2026)

_Generado el 2026-06-23 · Garmin Forerunner 165_

## Resumen

| Métrica | Esta semana | Tu media (~4 sem) | Tendencia |
|---------|------------:|------------------:|:---------:|
| Sueño | 7h34 | 7h52 | ▼ 18 min |
| FC reposo | 49 bpm | 46 bpm | ▲ 3 bpm |
| HRV nocturno | 56 ms | 63 ms | ▼ 7 ms |
| ... |   |   |   |

### Señales

- ⚠️ FC reposo elevada 3 días seguidos respecto a tu media — posible fatiga.
- ⚠️ HRV nocturno un 11% por debajo de tu media — prioriza descanso.
```

Ver [`docs/ejemplo_garmin_log.md`](docs/ejemplo_garmin_log.md) para un informe completo de ejemplo.

## Requisitos

- Python 3.10+ (probado con 3.12)
- Una cuenta de Garmin Connect

## Instalación

```bash
git clone https://github.com/<tu-usuario>/garmin-weekly-report.git
cd garmin-weekly-report

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuración

Copia el fichero de ejemplo y rellena tus credenciales de Garmin Connect:

```bash
cp .env.example .env
# edita .env con tu email y contraseña
```

```ini
GARMIN_EMAIL=tu@email.com
GARMIN_PASSWORD=tu_contraseña
```

El `.env` está en `.gitignore` y nunca se sube al repositorio.

### Primer uso: autenticación

La primera vez tienes que autenticarte (puede pedir verificación en dos pasos):

```bash
.venv/bin/garmin auth
```

Esto crea la sesión que reutilizarán las siguientes sincronizaciones.

## Uso

```bash
# Semana ISO anterior (lun–dom) + sincroniza con Garmin
python generate_report.py

# Misma semana pero sin sincronizar (BD ya actualizada)
python generate_report.py --no-sync

# Desde una fecha hasta hoy
python generate_report.py --start-date 2026-05-28

# Rango concreto (genera etiquetas de día con fecha en rangos largos)
python generate_report.py --start-date 2026-05-01 --end-date 2026-05-31

# Inspeccionar el esquema de la BD (tablas y columnas)
python generate_report.py --inspect-schema
```

El informe se escribe en `output/garmin_log.md`.

## Qué incluye el informe

| Sección | Métricas |
|---------|----------|
| **Resumen** | Comparación de cada métrica con tu media de ~4 semanas + señales automáticas |
| **Sueño** | Horas totales, fases (deep / REM / light), score, medias |
| **FC reposo + HRV** | Frecuencia cardíaca en reposo y HRV nocturno (RMSSD aprox.) |
| **Estrés y Body Battery** | Estrés medio diario, máximo y mínimo de Body Battery |
| **Actividad** | Sesiones (tipo y duración), FC media, delta de Body Battery, pasos |

Las noches de sueño se etiquetan por el día en que te acostaste (no por el de
despertar), y las lecturas inválidas de estrés/Body Battery (`value < 0`) se descartan.

## Privacidad

Este proyecto **no incluye datos personales**. Los siguientes ficheros se generan en
local y están excluidos por `.gitignore`:

- `.env` — tus credenciales
- `garmin_data.db` — base de datos SQLite con tu historial
- `garmin_files/` — ficheros `.fit` y JSON descargados de Garmin
- `output/` — informes generados

## Licencia

[MIT](LICENSE)
