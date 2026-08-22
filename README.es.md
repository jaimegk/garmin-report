<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo/logo-white.png">
  <img src="assets/logo/logo-256.png" alt="" width="72">
</picture>

# BioDelta

_[English](README.md) · **Español**_

Convierte tus datos de [Garmin Connect](https://connect.garmin.com) en un informe semanal y un
panel interactivo que te dicen **qué merece atención**, no solo qué pasó.

Cada métrica se compara con **tu propia media de las ~4 semanas previas** — no con la media
de la población — y de ahí salen **señales y diagnósticos automáticos**: semáforo de estado,
FC en reposo elevada varios días seguidos, HRV fuera de tu rango normal, noches cortas,
horarios irregulares y estrés alto.

Todo corre 100% en local: tus credenciales y tus datos de salud nunca salen de tu ordenador.
El informe se genera en español o en inglés (`--lang es|en`, o la bandera del panel).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-dark.png">
  <img src="docs/screenshot.png" alt="Cabecera del informe: semáforo de estado, anillos de resumen, cifras y señales automáticas">
</picture>

**[▶ Ver un informe de ejemplo interactivo](https://jaimegk.github.io/biodelta/)** ·
[versión Markdown](docs/ejemplo_garmin_log.md)

## 🚀 Inicio Rápido en 1-Clic

Puedes usar BioDelta sin escribir código ni configurar entornos manualmente:

- **Linux / macOS:** Haz doble clic en `iniciar.command` o ejecuta en tu terminal:
  ```bash
  ./iniciar.sh
  ```
- **Windows:** Haz doble clic en `iniciar.bat`.

El lanzador prepara el entorno virtual la primera vez y abre BioDelta en tu navegador en
`http://localhost:8000`.

### Probar en 30 segundos (sin cuenta de Garmin)

```bash
git clone https://github.com/jaimegk/biodelta.git
cd biodelta
./iniciar.sh
```

Al abrir la aplicación, pulsa **✨ Demo** para explorar un informe completo de seis semanas con
datos sintéticos y todas las señales activas. Sin cuenta, sin credenciales y sin conexión.

## Qué lo hace distinto

**Semáforo de estado y diagnóstico en lenguaje llano.** El informe abre con una evaluación
(🟢 Óptimo / 🟡 Atención requerida / 🔴 Descanso necesario) y tres frases: duración y
regularidad del sueño, recuperación autonómica y estrés, y qué hacer hoy.

**Panel web local y viaje en el tiempo.** Navega entre semanas (`◀` / `▶`), arrastra un
`garmin_data.db` o sincroniza con tu cuenta de Garmin, con **verificación en dos pasos
(2FA/MFA)**. El servidor escucha en `127.0.0.1` y solo atiende peticiones nacidas en él.

**Glosario integrado.** Un botón `📖 Glosario` con una explicación clara y basada en
evidencia de cada métrica (SRI, ACWR, RMSSD, desacoplamiento aeróbico, VO2máx…).

**Gráficas sincronizadas.** Pasa el ratón sobre cualquier día para ver sus valores exactos y
resaltar ese mismo día en todas las gráficas de la semana a la vez.

**Tu línea base, no la de la población.** «49 bpm» no significa nada por sí solo; «49 bpm
cuando lo tuyo son 46, tres días seguidos» sí.

**Las dos gráficas cuentan la misma historia.** Cuando la FC en reposo sube, el HRV baja: el
informe lo enseña en paralelo en vez de dejarte cruzar tablas.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-charts-dark.png">
  <img src="docs/screenshot-charts.png" alt="FC en reposo y HRV nocturno: el pico de fatiga y su espejo">
</picture>

**Las métricas que de verdad importan.** El VO2máx es el predictor de mortalidad por
cualquier causa más potente que existe, y un reloj de gama media cubre 7 de los ~14 factores
con más respaldo científico. El análisis completo está en
[`docs/mortalidad_prematura_y_forerunner165.md`](docs/mortalidad_prematura_y_forerunner165.md).

**Dos formatos, dos lectores.** El `.md` está pensado para pasárselo a una IA; el `.html`,
para leerlo tú: un solo fichero autocontenido, sin red, con interruptor de tema claro/oscuro.

```
garmin extract (incremental)  →  garmin_data.db (SQLite)  →  output/garmin_log_<inicio>_<fin>.md
                                                          └→  output/garmin_log_<inicio>_<fin>.html
```

## Requisitos

- Python 3.10+ (probado con 3.12)
- Una cuenta de Garmin Connect (salvo para `--demo`)

## Configuración

`garmin auth` lee `GARMIN_EMAIL` y `GARMIN_PASSWORD` del entorno; si no están, te las pide
por teclado. Si prefieres tenerlas en un fichero:

```bash
cp .env.example .env          # y rellénalo con tus credenciales
set -a; source .env; set +a   # exporta las variables a esta shell
.venv/bin/garmin auth         # puede pedir verificación en dos pasos
```

Esto crea la sesión que reutilizarán las siguientes sincronizaciones. El `.env` está en
`.gitignore` y los tokens se guardan en `~/.garminconnect/`, fuera del repositorio.

## Uso

```bash
# Semana ISO anterior (lun–dom) + sincroniza con Garmin
python generate_report.py

# Misma semana pero sin sincronizar (BD ya actualizada)
python generate_report.py --no-sync

# Desde una fecha hasta hoy
python generate_report.py --start-date 2026-05-28

# Rango concreto: en periodos de más de una semana, el Resumen se trocea en
# semanas ISO y muestra la evolución y la tendencia (última semana vs anteriores)
python generate_report.py --start-date 2026-05-01 --end-date 2026-05-31

# Informe de ejemplo con datos sintéticos
python generate_report.py --demo

# Informe en español (por defecto sale en inglés)
python generate_report.py --lang es

# Inspeccionar el esquema de la BD (tablas y columnas)
python generate_report.py --inspect-schema
```

O levanta el panel local, que hace todo lo anterior desde el navegador:

```bash
python app.py                 # http://localhost:8000, abre el navegador
python app.py --port 9000 --no-browser
```

### Versión HTML

Cada ejecución escribe además un `.html` con el mismo nombre: las tablas ya formateadas, la
cabecera de tarjetas y **gráficas de fases del sueño, FC en reposo, HRV, estrés sobre Body
Battery y pasos diarios**.

Se abre con doble clic: es un fichero autocontenido, sin recursos externos (el único
JavaScript es el del tema, el glosario y los tooltips de las gráficas), así
que funciona offline y también sirve para mandártelo al móvil. Se adapta al tema claro/oscuro
del sistema, y al pasar el ratón sobre una barra o un punto se ve su valor exacto.

## Qué incluye el informe

| Sección | Métricas |
|---------|----------|
| **Resumen** | Señales automáticas primero, y luego cada métrica frente a tu media de ~4 semanas. En informes de **más de una semana** pasa a una **tabla de evolución semana a semana** con tendencia |
| **Sueño** | Horas, fases (deep / REM / light), score, **hora de acostarse/despertar + regularidad**, desvelo medio, **siestas**, despertares, estrés durante el sueño y Body Battery recuperada |
| **FC reposo + HRV** | Frecuencia cardíaca en reposo, HRV nocturno (RMSSD aprox.) y estado de HRV |
| **Respiración y SpO2** | SpO2 nocturna (media / mínima) y frecuencia respiratoria — orientativo, cribado |
| **Estrés y Body Battery** | Estrés medio diario, máximo y mínimo de Body Battery |
| **Actividad** | Sesiones (tipo y duración), FC media, **minutos de intensidad**, delta de Body Battery, pasos y pisos |
| **Detalle de sesiones** | Por sesión: distancia, ritmo, FC media/máx, reparto en zonas de FC, efecto aeróbico/anaeróbico, kcal y métricas propias del deporte (cadencia, zancada, GCT, potencia, D+; SWOLF y largos en natación) |
| **Vueltas** | Tabla por sesión con tiempo, distancia, ritmo, FC mín/med/máx, cadencia y desnivel (subida / bajada) de cada vuelta |
| **Forma física** | VO2máx y ritmos de carrera previstos |

Las noches de sueño se etiquetan por el día en que te acostaste (no por el de despertar), y
las lecturas inválidas de estrés/Body Battery (`value < 0`) se descartan.

> **Nota sobre el VO2máx:** el Forerunner 165 solo lo estima a partir de **carreras o
> caminatas al aire libre con GPS** (o ciclismo con potenciómetro). Las sesiones indoor, en
> cinta o de natación no generan estimación; si no aparece, haz alguna salida al aire libre.

## Tests

```bash
python test_report.py     # sin framework: solo asserts
```

Cubren los formateadores, el cálculo de regularidad, las reglas de señales, el conversor de
Markdown y las gráficas SVG. El test de punta a punta monta la base de datos del modo demo y
ejecuta el pipeline completo, que es lo que ejercita las consultas SQL.

## Privacidad

Este repositorio **no incluye datos personales**. Lo siguiente se genera en local y está
excluido por `.gitignore`:

- `.env` — tus credenciales
- `garmin_data.db` — base de datos SQLite con tu historial
- `garmin_files/` — ficheros `.fit` y JSON descargados de Garmin
- `output/` — informes generados (`.md` y `.html`)

El informe de ejemplo publicado en `docs/` está generado con `--demo`: datos sintéticos que no
corresponden a ninguna persona real.

## Aviso

Esto es un proyecto de bienestar personal, no un dispositivo médico. Las métricas ópticas de
muñeca son orientativas y las asociaciones que se citan son poblacionales: no diagnostican
nada en una persona concreta.

Notas de desarrollo: [CONTRIBUTING.md](CONTRIBUTING.md) — cómo regenerar el ejemplo
y las trampas del modelo de datos de Garmin que conviene conocer antes de tocar una
consulta.

## Licencia

[MIT](LICENSE)
