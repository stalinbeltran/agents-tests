"""Definición de los agentes de la demo y de sus prompts.

La demo compara dos formas de resolver la MISMA tarea (revisar un fragmento de
código desde tres ángulos distintos):

  A) Un solo agente generalista, en una conversación secuencial.
  B) Un orquestador que lanza tres subagentes especializados en paralelo.
"""

MODEL = "claude-opus-5"
EFFORT = "low"          # mismo esfuerzo en ambos modos: la comparación debe ser justa
MAX_TOKENS = 4000

# Precios de claude-opus-5, USD por token.
PRICE_IN = 5.0 / 1_000_000
PRICE_OUT = 25.0 / 1_000_000

BREVEDAD = (
    "Responde en español, en menos de 200 palabras. Usa este formato exacto:\n"
    "VEREDICTO: <una línea>\n"
    "HALLAZGOS:\n- <hallazgo>: <por qué importa y cómo se arregla>\n"
)

# --- Modo B: subagentes especializados -------------------------------------
# Cada uno tiene su propio system prompt y su propio contexto: sólo ve el código
# y su especialidad. No ve las conversaciones de los demás.

SPECIALISTS = [
    {
        "key": "seguridad",
        "label": "Subagente · Seguridad",
        "system": (
            "Eres un auditor de seguridad de aplicaciones. Sólo te interesan "
            "vulnerabilidades explotables: inyección, validación de entrada, "
            "manejo de secretos y permisos. Ignora estilo y rendimiento.\n" + BREVEDAD
        ),
        "ask": "Audita la seguridad de este código:\n\n```python\n{code}\n```",
        "mock_seconds": 3.1,
    },
    {
        "key": "rendimiento",
        "label": "Subagente · Rendimiento",
        "system": (
            "Eres un especialista en rendimiento. Sólo te interesan complejidad "
            "algorítmica, consultas ineficientes y uso de memoria o recursos. "
            "Ignora seguridad y estilo.\n" + BREVEDAD
        ),
        "ask": "Analiza el rendimiento de este código:\n\n```python\n{code}\n```",
        "mock_seconds": 3.6,
    },
    {
        "key": "estilo",
        "label": "Subagente · Estilo",
        "system": (
            "Eres un revisor de legibilidad y mantenibilidad. Sólo te interesan "
            "nombres, estructura, manejo de recursos y claridad. Ignora seguridad "
            "y rendimiento.\n" + BREVEDAD
        ),
        "ask": "Revisa el estilo y la mantenibilidad de este código:\n\n```python\n{code}\n```",
        "mock_seconds": 2.9,
    },
]

ORCHESTRATOR = {
    "key": "orquestador",
    "label": "Orquestador · Consolidación",
    "system": (
        "Eres el coordinador de un equipo de revisión. Recibes los informes de "
        "tus especialistas y produces una lista de prioridades para el "
        "desarrollador.\n"
        "Responde en español, en menos de 150 palabras, como lista numerada "
        "ordenada por gravedad."
    ),
    "ask": "Informes del equipo:\n\n{reports}\n\nConsolida las prioridades.",
    "mock_seconds": 1.4,
}

# --- Modo A: un solo agente, tres turnos secuenciales ----------------------
# El contexto es uno solo y crece en cada turno: cada llamada reenvía todo el
# historial anterior.

SINGLE_SYSTEM = (
    "Eres un revisor de código senior. Vas a analizar un fragmento desde varios "
    "ángulos, uno por turno.\n" + BREVEDAD
)

SINGLE_TURNS = [
    {
        "key": "seguridad",
        "label": "Turno 1 · Seguridad",
        "ask": "Audita la SEGURIDAD de este código:\n\n```python\n{code}\n```",
        "mock_seconds": 3.1,
    },
    {
        "key": "rendimiento",
        "label": "Turno 2 · Rendimiento",
        "ask": "Ahora analiza el RENDIMIENTO del mismo código.",
        "mock_seconds": 3.6,
    },
    {
        "key": "estilo",
        "label": "Turno 3 · Estilo",
        "ask": "Ahora revisa el ESTILO y la mantenibilidad del mismo código.",
        "mock_seconds": 2.9,
    },
    {
        "key": "consolidacion",
        "label": "Turno 4 · Consolidación",
        "ask": (
            "Consolida todo lo anterior en una lista numerada de prioridades "
            "para el desarrollador, en menos de 150 palabras."
        ),
        "mock_seconds": 1.8,
    },
]

SAMPLE_CODE = '''import sqlite3

def obtener_pedidos(conn, user_input):
    cur = conn.cursor()
    cur.execute("SELECT * FROM pedidos WHERE cliente = '" + user_input + "'")
    return cur.fetchall()

def total_por_cliente(pedidos, clientes):
    r = []
    for c in clientes:
        t = 0
        for p in pedidos:
            if p[1] == c:
                t = t + p[3]
        r.append((c, t))
    return r

def guardar(pedidos):
    f = open("dump.txt", "w")
    for p in pedidos:
        f.write(str(p) + "\\n")
'''

# --- Respuestas simuladas (modo demo, sin clave de API) --------------------
# Los mismos textos se usan en los dos modos: así el modo demo compara sólo la
# mecánica (latencia y contexto), no la calidad de las respuestas.

MOCK_REPLIES = {
    "seguridad": (
        "VEREDICTO: Inyección SQL explotable en obtener_pedidos.\n"
        "HALLAZGOS:\n"
        "- Concatenación de user_input en el SELECT: cualquier cliente puede leer o "
        "borrar la tabla completa. Usa parámetros: cur.execute(\"... WHERE cliente = ?\", (user_input,)).\n"
        "- Sin validación de tipo ni longitud de user_input: valida antes de consultar.\n"
        "- guardar() escribe rutas fijas sin control de permisos: el fichero puede "
        "sobrescribirse desde otro proceso."
    ),
    "rendimiento": (
        "VEREDICTO: total_por_cliente es O(clientes × pedidos); debería ser O(pedidos).\n"
        "HALLAZGOS:\n"
        "- Doble bucle anidado: con 1.000 clientes y 50.000 pedidos son 50 millones de "
        "comparaciones. Agrupa una sola vez con collections.defaultdict(int).\n"
        "- SELECT * trae columnas que no se usan: pide sólo cliente y total.\n"
        "- fetchall() carga todo en memoria: itera el cursor si el resultado es grande."
    ),
    "estilo": (
        "VEREDICTO: Nombres opacos y un fichero que nunca se cierra.\n"
        "HALLAZGOS:\n"
        "- open() sin with en guardar(): el fichero queda abierto si falla la escritura. "
        "Usa 'with open(...) as f'.\n"
        "- Variables r, t, c, p y accesos por índice p[1], p[3]: usa nombres explícitos "
        "o una dataclass/namedtuple.\n"
        "- Falta type hints y docstrings en las tres funciones públicas."
    ),
    "consolidacion": (
        "1. Corregir la inyección SQL en obtener_pedidos con consulta parametrizada "
        "(riesgo crítico, explotable desde la entrada del usuario).\n"
        "2. Cerrar el fichero en guardar() con 'with' (fuga de recurso, fallo silencioso).\n"
        "3. Reescribir total_por_cliente con un diccionario de agregación: O(n) en vez "
        "de O(n×m).\n"
        "4. Limitar el SELECT a las columnas usadas y evitar fetchall() en resultados grandes.\n"
        "5. Renombrar variables y añadir type hints antes de seguir ampliando el módulo."
    ),
}
MOCK_REPLIES["orquestador"] = MOCK_REPLIES["consolidacion"]
