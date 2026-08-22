# Factores de mortalidad prematura y su medición con un Garmin Forerunner 165

_Estudio y conclusiones · Elaborado el 2026-06-28_

> **Aviso.** Este documento resume evidencia epidemiológica (estudios observacionales y
> metaanálisis) y la cruza con las capacidades reales de un reloj de gama media. **No es
> consejo médico.** Las asociaciones descritas son estadísticas y poblacionales; en un
> individuo concreto no predicen un desenlace, y varias de ellas reflejan tanto causa
> (factor modificable) como consecuencia (marcador de enfermedad ya presente). El reloj es
> un dispositivo de **bienestar**, no de diagnóstico.

---

## Resumen ejecutivo

1. **El predictor individual más potente de muerte prematura por cualquier causa es la
   capacidad cardiorrespiratoria (VO₂máx).** Su poder predictivo supera al del tabaquismo,
   la hipertensión o el colesterol en varios análisis. **El Forerunner 165 estima el
   VO₂máx**, así que el reloj captura, de forma gratuita, la métrica más importante.

2. **De los ~14 factores con mayor respaldo científico, el FR165 mide directamente 7,
   parcialmente 1 y deja fuera 6** (más dieta y alcohol). Los que **sí** cubre son:
   VO₂máx, actividad física/pasos, frecuencia cardíaca en reposo, variabilidad de la
   frecuencia cardíaca (HRV), sueño, SpO₂ y frecuencia respiratoria. **Parcialmente**: la
   velocidad de la marcha.

3. **Lo que el reloj no ve es justamente el eje clínico-bioquímico y el conductual:**
   presión arterial, analítica de sangre (glucosa, lípidos), fuerza de prensión,
   composición corporal (perímetro de cintura), tabaquismo, calidad de la dieta, consumo de
   alcohol y aislamiento social. Varios de ellos están entre los factores de riesgo de
   muerte más importantes del mundo.

4. **El reloj brilla en el eje "fitness / fisiológico / conductual" y es ciego al eje
   "clínico / bioquímico / psicosocial".** Su mayor valor no es la precisión absoluta de
   cada lectura (es de grado bienestar, con márgenes de error relevantes), sino el
   **seguimiento de tendencias** de métricas que de otro modo no medirías a diario.

5. **Nota para este proyecto:** el informe semanal ya capta los marcadores más
   predictivos que el reloj registra: VO₂máx (con sus ritmos de carrera previstos),
   minutos de intensidad frente a la guía 150–300, regularidad del sueño (hora de
   acostarse/despertar), SpO₂ y frecuencia respiratoria nocturnas, además de sueño, HRV,
   FC en reposo, estrés, Body Battery y pasos. El gran ausente es estructural, no del
   pipeline: el VO₂máx solo aparece si haces **salidas al aire libre con GPS** (las
   sesiones indoor/cinta/natación no lo generan). Ver §7.

---

## 1. Metodología y advertencias de interpretación

Se han revisado metaanálisis y grandes estudios de cohortes que relacionan distintos
factores con la **mortalidad por cualquier causa** (_all-cause mortality_), que es el
desenlace más robusto para hablar de "muerte prematura". Para cada factor se reporta el
tamaño de efecto tal y como lo publican las fuentes (cociente de riesgos HR/RR, _odds
ratio_ OR, o años de vida perdidos), con su referencia.

Tres cautelas imprescindibles:

- **Asociación ≠ causalidad.** Son estudios observacionales. Se ajustan por factores de
  confusión, pero nunca por todos.
- **Causalidad inversa.** Marcadores como una FC en reposo alta, una HRV baja, poca fuerza
  de prensión o una marcha lenta pueden ser **consecuencia** de una enfermedad subclínica,
  no solo causa de mal pronóstico. Mejorarlos no siempre "deshace" el riesgo.
- **Tamaños de efecto modestos por unidad.** Un HR de 1,10 por unidad parece poco, pero a
  lo largo de un rango fisiológico amplio (p. ej. 30 ms de HRV o 30 cm de cintura) se
  acumula.

---

## 2. Los factores que más se correlacionan con la mortalidad prematura

Ordenados, a grandes rasgos, de mayor a menor solidez/replicación de la evidencia.

### 2.1. Capacidad cardiorrespiratoria — VO₂máx _(el factor número uno)_

Es el predictor fisiológico más fuerte y consistente. Una **revisión general de
metaanálisis** que agrupa más de **20,9 millones de observaciones de 199 cohortes**
encontró que, comparando fitness alto frente a bajo, el riesgo de muerte por cualquier
causa cae a la mitad (**HR ≈ 0,47**); las personas con baja capacidad cardiorrespiratoria
tienen un **70 % más de mortalidad total** y un 56 % más de mortalidad cardiovascular. Cada
**1 MET** (≈ 3,5 ml/kg/min) más de fitness reduce la mortalidad un **11–17 %**.

El estudio de **Mandsager et al. (JAMA, 2018)**, sobre 122 007 personas en prueba de
esfuerzo, no halló un límite superior de beneficio: pasar del cuartil de **peor forma** al
inmediatamente superior se asoció a ~**50 % menos** mortalidad a 10 años, y la diferencia
entre el grupo de baja forma y el de élite fue de **5 veces**. Es, posiblemente, la única
métrica de esta lista que combina ser **muy predictiva** y **muy modificable** con
entrenamiento.

### 2.2. Actividad física: pasos diarios e intensidad

- **Pasos:** el metaanálisis de **Paluch et al. (Lancet Public Health, 2022)**, 15 cohortes
  internacionales, mostró que el riesgo de muerte baja al aumentar los pasos y se
  **estabiliza en 6 000–8 000 pasos/día en mayores** y **8 000–10 000 en adultos jóvenes**.
  El mítico "10 000" no es un umbral mágico; el grueso del beneficio llega antes.
- **Intensidad (MVPA):** cumplir las guías de **150–300 min/semana** de actividad moderada
  se asocia a **~20–21 % menos** mortalidad total; por cada hora semanal extra, RR ≈ 0,96
  (moderada) y ≈ 0,91 (vigorosa). Comparando los más activos con los más sedentarios, el
  riesgo cae hasta **RR ≈ 0,65**.

### 2.3. Frecuencia cardíaca en reposo (FC reposo)

Metaanálisis de población general (**46 estudios, 1,25 millones de personas**): por cada
**+10 lpm** de FC en reposo, la mortalidad por cualquier causa sube **~9 %** (RR ≈ 1,09).
Una FC en reposo baja suele reflejar buen tono vagal y buena forma física.

### 2.4. Variabilidad de la frecuencia cardíaca (HRV)

Una HRV **baja** se asocia a más mortalidad de forma consistente entre poblaciones. En
cohortes con enfermedad cardiovascular, la HRV baja se asoció a **HR ≈ 2,12** de muerte por
cualquier causa; revisiones que agrupan ~38 000 personas confirman que los índices bajos de
HRV predicen mayor mortalidad en distintas edades, sexos y continentes. Es un marcador del
equilibrio del sistema nervioso autónomo y de la carga/estrés acumulados.

### 2.5. Sueño: duración y calidad

Relación en **forma de U**: tanto dormir poco como dormir mucho se asocian a más
mortalidad, con el mínimo en torno a **7 horas**. Metaanálisis recientes: **sueño corto
(<7 h)** HR ≈ 1,12–1,14; **sueño largo (≥9 h)** HR ≈ 1,30–1,34. El sueño largo suele ser
marcador de enfermedad subyacente más que causa directa.

### 2.6. Fuerza muscular — fuerza de prensión (_grip strength_)

Marcador potente de salud global y de masa/función muscular. En el estudio **PURE (Leong et
al., Lancet, 2015)** y en metaanálisis de **>3 millones** de personas, **cada 5 kg menos**
de fuerza de prensión se asoció a **~16 % más** mortalidad total (HR ≈ 1,16). Notablemente,
**predijo la mortalidad mejor que la presión arterial sistólica**.

### 2.7. Velocidad de la marcha (_gait speed_)

En el _pooled analysis_ de **Studenski et al. (JAMA, 2011)** sobre 34 485 mayores, cada
**+0,1 m/s** de velocidad al caminar se asoció a **12 % menos** mortalidad (HR ≈ 0,88).
Comparando los más lentos con los más rápidos, RR ≈ 1,89. Es un "signo vital" funcional muy
usado en geriatría.

### 2.8. Presión arterial (hipertensión)

Uno de los principales factores de riesgo de muerte del mundo. La relación es **lineal**
hasta cifras tan bajas como 115/75 mmHg: por cada **+20 mmHg** de presión sistólica, la
mortalidad total sube ~1,2× y la cardiovascular (cardiopatía isquémica e ictus)
aproximadamente **se duplica**.

### 2.9. Composición corporal: perímetro de cintura / obesidad central

La grasa **central** predice mejor que el IMC. Metaanálisis de **72 cohortes**: por cada
**+10 cm** de perímetro de cintura, **~11 % más** mortalidad (HR ≈ 1,11); la obesidad
central se asocia a HR ≈ 1,39 incluso con IMC "normal".

### 2.10. Tabaquismo

El principal factor de riesgo **conductual** de muerte a nivel global. Un fumador pierde de
media **12–13 años de vida**; los fumadores actuales tienen HR ≈ 2,7–2,8 frente a quienes
nunca fumaron. Dejarlo antes de los ~40 recupera casi toda la esperanza de vida perdida.

### 2.11. Aislamiento social y soledad

El metaanálisis de **Holt-Lunstad et al. (2015)** cuantificó el efecto: aislamiento social
OR ≈ 1,29, soledad OR ≈ 1,26, vivir solo OR ≈ 1,32 (un **26–32 % más** de probabilidad de
morir). De magnitud comparable a factores de riesgo físicos clásicos.

### 2.12. Factores metabólico-bioquímicos (glucosa, lípidos), dieta y alcohol

La glucemia elevada, el colesterol LDL alto, una dieta de baja calidad y el consumo de
alcohol figuran sistemáticamente entre los principales factores de riesgo de muerte en los
análisis de carga global de enfermedad. Requieren analítica de sangre o registro de
conducta: **nada de esto lo mide un reloj**.

### 2.13. Marcadores secundarios que el reloj sí toca

- **SpO₂ (oxigenación sanguínea):** no es un predictor de primer nivel en población sana,
  pero una saturación nocturna baja es señal útil de **apnea del sueño** o de problema
  respiratorio, ambos asociados a peor pronóstico.
- **Frecuencia respiratoria:** signo vital clínico; sus desviaciones son más un marcador
  agudo (infección, estrés) que un predictor de longevidad por sí solo.

---

## 3. Qué puede medir un Garmin Forerunner 165

El FR165 monta el sensor óptico **Garmin Elevate V4**: luz **verde** para frecuencia
cardíaca y luz **roja** para SpO₂ (_Pulse Ox_). Incluye altímetro barométrico,
acelerómetro, brújula de 3 ejes, sensor de luz ambiental y GPS/GNSS. **No** lleva
electrodos para **ECG** (eso es el Elevate V5 de modelos superiores), **ni termómetro**
(sin temperatura de la piel), **ni giroscopio**.

A partir de ese hardware, el reloj y Garmin Connect derivan:

| Métrica del reloj | ¿De dónde sale? |
|---|---|
| **VO₂máx estimado** | Algoritmo Firstbeat a partir de FC + ritmo/GPS en carreras o caminatas |
| **FC en reposo** | FC óptica continua (mínimos nocturnos) |
| **HRV nocturna (HRV Status)** | FC óptica durante el sueño (basada en RMSSD) |
| **Sueño** (duración, fases deep/REM/light, _score_) | FC + acelerómetro + respiración |
| **Estrés** y **Body Battery** | Derivados de la HRV (proxies de carga autonómica) |
| **SpO₂ / Pulse Ox** | Luz roja del sensor óptico (puntual o todo el día) |
| **Frecuencia respiratoria** | Modulación de la señal óptica de FC |
| **Pasos / minutos de intensidad** | Acelerómetro (+ FC para la intensidad) |
| **Actividades** (FC media, ritmo, distancia, velocidad) | FC + GPS/GNSS |

**Importante distinguir dos cosas:**

- **Peso / IMC:** el reloj **no** los mide. Solo aparecen si los introduces a mano o usas
  una **báscula Garmin Index** (accesorio aparte). El **perímetro de cintura** —que es lo
  que de verdad correlaciona— no lo da ni la báscula.
- **Lo que el reloj mide ≈ lo que tu pipeline ya ingiere.** Tu `generate_report.py`
  capta sueño (con horas de acostarse/despertar y regularidad), HRV, FC reposo, estrés,
  Body Battery, SpO₂ y respiración nocturnas, actividad, pasos, minutos de intensidad y
  VO₂máx + ritmos de carrera previstos. Lo único que el reloj registra y el informe deja
  fuera por bajo valor es marginal (escaleras, eventos de disrupción respiratoria); el
  VO₂máx aparecerá en cuanto haya una salida al aire libre con GPS.

---

## 4. Cruce: factores de mortalidad × medibles con el FR165

| # | Factor | Solidez de la evidencia | Tamaño de efecto (referencia) | ¿Mide el FR165? | Métrica concreta / matiz |
|--:|--------|:----------------------:|-------------------------------|:---------------:|--------------------------|
| 1 | **Capacidad cardiorrespiratoria (VO₂máx)** | ★★★★★ | HR ≈ 0,47 alto vs bajo; +1 MET → −11–17 % | **Sí** (estimado) | VO₂máx (necesita salidas con GPS para calibrar) |
| 2 | **Actividad física / pasos** | ★★★★★ | Meseta 6–8 k pasos; 150–300 min MVPA → −20 % | **Sí** | Pasos, minutos de intensidad, actividades |
| 3 | **FC en reposo** | ★★★★ | +10 lpm → +9 % (RR 1,09) | **Sí** | FC reposo diaria |
| 4 | **Variabilidad FC (HRV)** | ★★★★ | HRV baja → HR ≈ 2,12 | **Sí** | HRV nocturna (RMSSD aprox.) |
| 5 | **Sueño (duración/calidad)** | ★★★★ | U: <7 h HR 1,12; ≥9 h HR 1,34 | **Sí** | Horas, fases, _score_ |
| 6 | **SpO₂ / oxigenación** | ★★ (cribado) | Marcador de apnea / respiratorio | **Sí** | Pulse Ox puntual o nocturno |
| 7 | **Frecuencia respiratoria** | ★★ | Signo vital (más agudo que crónico) | **Sí** | Respiraciones/min día y noche |
| 8 | **Velocidad de la marcha** | ★★★★ | +0,1 m/s → −12 % (HR 0,88) | **Parcial** | Derivable del ritmo GPS al caminar (no es un test estandarizado) |
| 9 | **Fuerza de prensión / muscular** | ★★★★ | −5 kg → +16 % (HR 1,16) | **No** | Necesita dinamómetro |
| 10 | **Presión arterial** | ★★★★★ | +20 mmHg → ×1,2 total, ×2 CV | **No** | Necesita tensiómetro |
| 11 | **Composición corporal (cintura)** | ★★★★ | +10 cm cintura → +11 % (HR 1,11) | **No** | Cinta métrica; peso/IMC solo manual o báscula |
| 12 | **Tabaquismo** | ★★★★★ | −12–13 años de vida; HR ≈ 2,7 | **No** | Conducta (autorregistro) |
| 13 | **Aislamiento social / soledad** | ★★★★ | OR ≈ 1,26–1,32 | **No** | Psicosocial |
| 14 | **Metabólico-bioquímico (glucosa, lípidos)** | ★★★★★ | Factores de riesgo de primer orden | **No** | Analítica de sangre |
| — | _Dieta y alcohol_ | ★★★★ | Riesgo de primer orden | **No** | Conducta |

★ = solidez/replicación de la evidencia para mortalidad por cualquier causa (valoración cualitativa).

---

## 5. El recuento: ¿cuántos de estos factores mide el FR165?

Tomando los **14 factores** de mayor respaldo de la tabla anterior:

- **Mide directamente: 7** → VO₂máx, actividad/pasos, FC en reposo, HRV, sueño, SpO₂ y
  frecuencia respiratoria.
- **Mide parcialmente: 1** → velocidad de la marcha (se puede derivar del ritmo con GPS,
  pero no como test clínico estandarizado).
- **No mide: 6** → fuerza de prensión, presión arterial, composición corporal (cintura),
  tabaquismo, aislamiento social y analítica de sangre (glucosa/lípidos). _(Sumando dieta y
  alcohol, 8 factores conductuales/clínicos fuera de alcance.)_

**La lectura cualitativa importa más que el número:** entre esos 7 medibles está el
**predictor más potente de todos (VO₂máx)** y el segundo (**actividad física**). Es decir,
el reloj acierta donde más pesa la evidencia. Pero es **ciego al eje clínico** (presión
arterial, sangre) y al **conductual/psicosocial** (tabaco, dieta, alcohol, vínculos
sociales), donde residen otros factores de riesgo de primerísimo orden.

---

## 6. Fiabilidad: hasta dónde fiarse de cada lectura

El FR165 es de **grado bienestar**. Sus números sirven para **tendencias y cribado**, no
para diagnóstico. Por métrica:

- **VO₂máx:** error típico **±5 %** en el mejor caso (corredor entrenado, salidas al aire
  libre, banda de pecho) y **10–15 %** solo con muñeca. Úsalo para ver la **dirección** del
  cambio, no como cifra de laboratorio.
- **SpO₂ de muñeca:** sensiblemente menos fiable que un pulsioxímetro médico; empeora con
  movimiento, mala fijación y tonos de piel oscuros. Garmin la marca como no médica. Útil
  como **señal de alerta**, no como medida exacta.
- **HRV nocturna:** razonable para seguir tu propia línea base; no equivale a la HRV de un
  ECG clínico. Compárala **contigo mismo**, no con otras personas.
- **FC en reposo y pasos:** de las medidas más fiables del reloj.
- **Fases del sueño:** la **duración** total es bastante buena; el reparto exacto
  deep/REM/light es la parte más floja de cualquier _wearable_.

A esto se suma la cautela general de §1: muchos de estos marcadores también empeoran
**como consecuencia** de una enfermedad ya presente.

---

## 7. Conclusiones y recomendaciones accionables

**Conclusión central.** Un Forerunner 165 captura una parte sorprendentemente relevante de
los marcadores más predictivos de mortalidad —incluido el número uno, el VO₂máx— pero deja
fuera todo el bloque clínico-bioquímico y conductual. Como herramienta de longevidad, es un
**excelente seguidor de tendencias del eje fitness/fisiológico** y debe **complementarse**
con lo que no puede ver.

**Para aprovechar lo que el reloj sí mide:**

1. **Prioriza el VO₂máx.** Es el de mayor retorno. Para que el reloj lo estime y lo
   actualice, haz **salidas al aire libre con GPS** (correr o caminar rápido) con
   regularidad; vigila la **tendencia**, no el valor absoluto.
2. **Muévete:** apunta a **~8 000 pasos/día** y **150–300 min/semana** de intensidad
   moderada-vigorosa.
3. **Duerme ~7 h** y cuida la regularidad; vigila que la **HRV no caiga** y la **FC en
   reposo no suba** de forma sostenida frente a tu línea base (justo las señales que tu
   informe semanal ya detecta).

**Para cubrir lo que el reloj no mide** (igual o más importante):

4. **Tensiómetro de brazo en casa** (presión arterial: factor de primer orden).
5. **Analítica anual** con glucosa/HbA1c y perfil lipídico.
6. **Cinta métrica:** perímetro de cintura (mejor que el peso/IMC).
7. **Fuerza:** un dinamómetro de mano barato, o seguimiento de fuerza en el gimnasio.
8. **Conducta y vínculos:** no fumar, alcohol bajo o nulo, dieta de calidad y **relaciones
   sociales** —cuyo efecto sobre la mortalidad es comparable al de factores físicos.

**Para este proyecto (estado del informe).** El `generate_report.py` ya incorpora las
métricas más predictivas que el reloj registra:

- **(Hecho) VO₂máx** en el Resumen y sección "Forma física", con aviso si falta y ritmos
  de carrera previstos como proxy de forma mientras tanto.
- **(Hecho) Minutos de intensidad** semanales frente al objetivo 150–300, con señal.
- **(Hecho) SpO₂ y respiración nocturnas** como sección de cribado (alerta si la SpO₂
  media baja sostenidamente → posible apnea).
- **(Hecho) Regularidad del sueño** (hora de acostarse/despertar y su dispersión).
- **(Pendiente, opcional) Apnea**: eventos de disrupción respiratoria nocturna
  (`breathing_disruption`) como señal complementaria al cribado de SpO₂.
- **(Fuera de alcance) Peso/IMC**: necesita báscula Garmin Index y, aun así, **no**
  sustituye al perímetro de cintura.

---

## Fuentes

**Capacidad cardiorrespiratoria (VO₂máx)**
- [Cardiorespiratory fitness… overview of meta-analyses (20.9M obs, 199 cohorts) — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11103301/)
- [Cardiorespiratory fitness, BMI and mortality: systematic review and meta-analysis — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11874340/)
- [Mandsager et al., CRF and long-term mortality (JAMA, 2018) — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6324439/)

**Actividad física y pasos**
- [Paluch et al., Daily steps and all-cause mortality: 15 international cohorts (Lancet Public Health, 2022) — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9289978/)
- [Daily step count and all-cause mortality: dose-response meta-analysis — PubMed](https://pubmed.ncbi.nlm.nih.gov/34417979/)
- [Lowest risk of death at 150–600 min/week of activity — American Heart Association](https://newsroom.heart.org/news/new-study-finds-lowest-risk-of-death-was-among-adults-who-exercised-150-600-minutesweek)

**Frecuencia cardíaca en reposo**
- [Resting heart rate and all-cause/CV mortality: meta-analysis (CMAJ, 2016)](https://www.cmaj.ca/content/188/3/E53)
- [Resting heart rate and mortality — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4754196/)

**Variabilidad de la frecuencia cardíaca (HRV)**
- [HRV in the prediction of mortality: systematic review and meta-analysis — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0149763422003967)
- [HRV and risk of all-cause death in CVD: meta-analysis (HR 2.12) — SAGE](https://journals.sagepub.com/doi/10.1177/1099800419877442)

**Sueño**
- [Imbalanced sleep increases mortality risk 14–34%: meta-analysis — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12181477/)
- [Sleep duration with all-cause mortality and CV events: dose-response meta-analysis (JAHA)](https://www.ahajournals.org/doi/10.1161/JAHA.117.005947)

**Fuerza de prensión**
- [Leong et al., Prognostic value of grip strength: PURE study (Lancet, 2015)](https://www.thelancet.com/journals/lancet/article/PIIS0140-6736%2814%2962000-6/abstract)
- [Grip strength and all-cause mortality, CVD and cancer: meta-analysis — PubMed](https://pubmed.ncbi.nlm.nih.gov/28549705/)

**Velocidad de la marcha**
- [Studenski et al., Gait speed and survival in older adults (JAMA, 2011) — PDF](https://dividat.com/assets/main/papers/2011-Studenski.pdf)
- [Gait speed and mortality, CVD and cancer: meta-analysis — JAMDA](https://www.jamda.com/article/S1525-8610%2818%2930327-X/abstract)

**Presión arterial**
- [Blood pressure trajectories and CV mortality: Rancho Bernardo Study (J Hum Hypertens)](https://www.nature.com/articles/jhh201720)
- [Systolic blood pressure and all-cause mortality: prospective cohort — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5756411/)

**Composición corporal / obesidad central**
- [Central fatness and all-cause mortality: meta-analysis of 72 cohorts — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7509947/)

**Tabaquismo**
- [Smoking cessation and short/longer-term mortality (NEJM Evidence)](https://evidence.nejm.org/doi/full/10.1056/EVIDoa2300272)
- [21st-century hazards of smoking and benefits of cessation (NEJM)](https://www.nejm.org/doi/full/10.1056/NEJMsa1211128)

**Aislamiento social y soledad**
- [Holt-Lunstad et al., Loneliness and social isolation as risk factors for mortality (2015) — SAGE](https://journals.sagepub.com/doi/full/10.1177/1745691614568352)

**Garmin Forerunner 165 — capacidades y fiabilidad**
- [Garmin Forerunner 165 In-Depth Review — DC Rainmaker](https://www.dcrainmaker.com/2024/02/garmin-forerunner-165-depth-review.html)
- [Forerunner 165 — Garmin Wiki (sensores)](https://wiki.garminrumors.com/Forerunner_165)
- [Forerunner 165 Owner's Manual — Pulse Oximeter (Garmin)](https://www8.garmin.com/manuals/webhelp/GUID-607F08F6-33FC-40BF-9727-84E54043D82D/EN-US/GUID-4D425925-D4EE-4C26-B974-5375D0670860.html)
- [Validity of wrist-worn trackers for estimating VO₂máx — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6747132/)
- [Validity of VO₂máx estimates from a Garmin Forerunner (Eur J Appl Physiol, 2025)](https://link.springer.com/article/10.1007/s00421-025-05923-x)
