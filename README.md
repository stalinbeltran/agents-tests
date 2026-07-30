# Demo: subagentes de Claude, con mini app web

Demostración práctica de **para qué sirven los subagentes**: la misma tarea se
resuelve de dos formas, las dos se ejecutan **a la vez**, y la app web muestra
lado a lado cuánto tarda cada una y cuánto contexto y cuántos tokens consume.

| | Modo A | Modo B |
|---|---|---|
| Diseño | Un solo agente generalista | Orquestador + 3 subagentes especializados |
| Ejecución | 4 turnos **secuenciales** en una sola conversación | 3 subagentes **en paralelo** + 1 consolidación |
| Contexto | Uno solo, que **crece** en cada turno | Uno **limpio y mínimo** por subagente |
| Prompt | Uno genérico que hace todos los papeles | Uno por especialidad (seguridad, rendimiento, estilo) |

La tarea es revisar un fragmento de código Python desde tres ángulos. El código
de ejemplo que trae la app tiene, a propósito, una inyección SQL, un bucle
O(n×m) y un fichero que nunca se cierra: un hallazgo claro para cada
especialista.

## Requisitos

- **Python 3.10 o superior** (verificado con 3.14.6).
- Ninguna dependencia para el **modo demo**: sólo biblioteca estándar.
- Para el **modo real**, el paquete `anthropic` y credenciales de la API.

## Comandos

Todos los comandos se ejecutan desde la raíz del repositorio (`c:\Desarrollo\agents-tests`)
en PowerShell.

### 1. Comprobar la instalación

```powershell
python --version
```

### 2. Ejecutar las comprobaciones automáticas (sin navegador, sin clave de API)

```powershell
python -m demo.selftest
```

Ejecuta la comparación completa en modo demo y verifica que las ventajas que la
interfaz afirma se cumplen en los números medidos (paralelismo, menos tokens de
entrada, menos contexto máximo, contexto creciente en el modo secuencial).
Tarda unos 11 s por las latencias simuladas y termina con
`7 comprobaciones correctas.`

### 3. Arrancar la app web (modo demo)

```powershell
python -m demo.server
```

Y abrir <http://127.0.0.1:8000> en el navegador. Pulsa **Ejecutar comparación**:
las dos columnas avanzan en tiempo real y la de subagentes termina claramente
antes. `Ctrl+C` para parar.

Si el puerto 8000 está ocupado:

```powershell
python -m demo.server --port 8791
```

### 4. Modo real (llamadas de verdad a la API de Claude)

```powershell
python -m pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-tu-clave"
python -m demo.server
```

La cabecera de la app pasa de `modo demo` a `modo real`. Los dos modos usan el
mismo modelo (`claude-opus-5`) y el mismo `effort` (`low`), para que la
comparación sea justa; los tokens que se muestran son los que devuelve la propia
API en `usage`.

Para volver al modo demo sin borrar la clave:

```powershell
$env:DEMO_MODE = "1"
python -m demo.server
```

## Qué mirar en la app

- **Tiempo total.** El agente único encadena turnos: su latencia es la *suma*.
  Los subagentes corren a la vez: es el *máximo* más la consolidación.
- **Tokens de entrada.** La API no tiene estado: cada turno del agente único
  reenvía todo el historial, así que el gasto de entrada crece turno a turno.
  Cada subagente arranca con un contexto limpio.
- **Contexto máximo.** Los tokens de la llamada más grande. Es el número que
  decide cuándo chocas con la ventana de contexto.
- **Especialización.** Cada subagente tiene su propio *system prompt* y podría
  tener su propio modelo o `effort`; el agente único hace todos los papeles con
  un prompt y arrastra las conclusiones previas.
- **Cuándo NO usarlos.** Añaden una llamada de coordinación y no comparten
  contexto: para tareas cortas o donde cada paso depende del anterior, el agente
  único es más simple y más barato.

## Estructura

```
demo/
  agents.py            definición de los agentes, prompts y respuestas simuladas
  runner.py            los dos modos, medición de métricas y stream de eventos
  server.py            servidor web (biblioteca estándar) + stream NDJSON
  selftest.py          comprobaciones automáticas sin navegador
  static/index.html    la interfaz (HTML/CSS/JS sin dependencias)
requirements.txt       sólo para el modo real
```

## Avisos del entorno

- **Modo demo vs. modo real.** Sin `ANTHROPIC_API_KEY` (o `ANTHROPIC_AUTH_TOKEN`)
  la app arranca en modo demo: respuestas fijas con latencias simuladas. La
  mecánica, el reparto de contexto y el cálculo de métricas son los mismos que
  en modo real, pero los tiempos y los tokens no son medidas de la API.
- **Puertos ocupados en Windows.** Windows permite que dos procesos escuchen en
  el mismo puerto local, y el que responde puede ser un servidor viejo que
  quedó abierto. Si ves contenido que no corresponde al código actual, cambia de
  puerto con `--port` o cierra el proceso anterior
  (`netstat -ano | Select-String 8000` para encontrar el PID).
- **Coste.** En modo real cada comparación son 8 llamadas al modelo (4 por
  modo), con respuestas limitadas a menos de 200 palabras. El coste estimado que
  muestra la app usa las tarifas de `claude-opus-5` ($5 / $25 por millón de
  tokens de entrada / salida).
