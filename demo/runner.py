"""Ejecuta los dos modos (agente único vs. subagentes) y mide la diferencia.

Los dos modos se lanzan a la vez, en hilos distintos, y van emitiendo eventos a
una cola compartida. El servidor los reenvía al navegador tal cual, así que en
la interfaz se ve cuál de los dos termina antes.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import agents


# --------------------------------------------------------------------------
# Backends: real (API de Claude) y simulado (sin clave, para probar la app)
# --------------------------------------------------------------------------

@dataclass
class Reply:
    text: str
    content: Any                 # se reenvía tal cual al historial del agente único
    input_tokens: int
    output_tokens: int
    ms: float


def _estimate_tokens(obj: Any) -> int:
    """Aproximación barata (~4 caracteres por token). Sólo para el modo demo."""
    return max(1, len(str(obj)) // 4)


class RealBackend:
    """Llamadas reales a la API de Claude."""

    name = "real"

    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic()

    def call(self, system: str, messages: list, mock_key: str, mock_seconds: float) -> Reply:
        t0 = time.perf_counter()
        response = self.client.messages.create(
            model=agents.MODEL,
            max_tokens=agents.MAX_TOKENS,
            system=system,
            messages=messages,
            output_config={"effort": agents.EFFORT},
        )
        ms = (time.perf_counter() - t0) * 1000

        if response.stop_reason == "refusal":
            raise RuntimeError("La petición fue rechazada por los filtros de seguridad.")

        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return Reply(
            text=text or "(sin texto en la respuesta)",
            content=response.content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            ms=ms,
        )


class MockBackend:
    """Respuestas fijas con latencia simulada: la app funciona sin clave de API."""

    name = "demo"

    def call(self, system: str, messages: list, mock_key: str, mock_seconds: float) -> Reply:
        t0 = time.perf_counter()
        time.sleep(mock_seconds)
        ms = (time.perf_counter() - t0) * 1000

        text = agents.MOCK_REPLIES[mock_key]
        input_tokens = _estimate_tokens(system) + sum(_estimate_tokens(m) for m in messages)
        return Reply(
            text=text,
            content=[{"type": "text", "text": text}],
            input_tokens=input_tokens,
            output_tokens=_estimate_tokens(text),
            ms=ms,
        )


def backend_mode() -> str:
    """'real' si hay credenciales y el SDK instalado; 'demo' en cualquier otro caso."""
    if os.environ.get("DEMO_MODE"):
        return "demo"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return "demo"
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "demo"
    return "real"


def make_backend():
    return RealBackend() if backend_mode() == "real" else MockBackend()


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------

@dataclass
class Metrics:
    calls: list = field(default_factory=list)
    wall_ms: float = 0.0

    def add(self, label: str, reply: Reply) -> None:
        self.calls.append(
            {
                "label": label,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "ms": round(reply.ms),
            }
        )

    def summary(self) -> dict:
        input_tokens = sum(c["input_tokens"] for c in self.calls)
        output_tokens = sum(c["output_tokens"] for c in self.calls)
        return {
            "calls": len(self.calls),
            "wall_ms": round(self.wall_ms),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            # Contexto máximo que tuvo que procesar una sola llamada.
            "peak_context_tokens": max((c["input_tokens"] for c in self.calls), default=0),
            "cost_usd": round(input_tokens * agents.PRICE_IN + output_tokens * agents.PRICE_OUT, 5),
            "detail": self.calls,
        }


# --------------------------------------------------------------------------
# Modo A: un solo agente, cuatro turnos secuenciales, un único contexto
# --------------------------------------------------------------------------

def run_single_agent(code: str, backend, emit: Callable[[dict], None]) -> dict:
    metrics = Metrics()
    messages: list = []
    t0 = time.perf_counter()

    for turn in agents.SINGLE_TURNS:
        emit({"type": "agent_start", "agent": turn["key"], "label": turn["label"]})
        messages.append({"role": "user", "content": turn["ask"].format(code=code)})

        reply = backend.call(
            system=agents.SINGLE_SYSTEM,
            messages=messages,
            mock_key=turn["key"],
            mock_seconds=turn["mock_seconds"],
        )
        # El historial completo se reenvía en la llamada siguiente: por eso los
        # tokens de entrada crecen turno a turno.
        messages.append({"role": "assistant", "content": reply.content})

        metrics.add(turn["label"], reply)
        emit(
            {
                "type": "agent_done",
                "agent": turn["key"],
                "label": turn["label"],
                "text": reply.text,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "ms": round(reply.ms),
            }
        )

    metrics.wall_ms = (time.perf_counter() - t0) * 1000
    return metrics.summary()


# --------------------------------------------------------------------------
# Modo B: orquestador + subagentes especializados en paralelo
# --------------------------------------------------------------------------

def run_subagents(code: str, backend, emit: Callable[[dict], None]) -> dict:
    metrics = Metrics()
    lock = threading.Lock()
    t0 = time.perf_counter()

    def run_one(spec: dict):
        emit({"type": "agent_start", "agent": spec["key"], "label": spec["label"]})
        # Contexto propio y mínimo: system prompt del especialista + el código.
        reply = backend.call(
            system=spec["system"],
            messages=[{"role": "user", "content": spec["ask"].format(code=code)}],
            mock_key=spec["key"],
            mock_seconds=spec["mock_seconds"],
        )
        with lock:
            metrics.add(spec["label"], reply)
        emit(
            {
                "type": "agent_done",
                "agent": spec["key"],
                "label": spec["label"],
                "text": reply.text,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "ms": round(reply.ms),
            }
        )
        return spec, reply

    with ThreadPoolExecutor(max_workers=len(agents.SPECIALISTS)) as pool:
        results = list(pool.map(run_one, agents.SPECIALISTS))

    # El orquestador sólo recibe los informes finales, no la exploración de cada
    # subagente: su contexto se mantiene pequeño.
    reports = "\n\n".join(f"### {spec['label']}\n{reply.text}" for spec, reply in results)

    orch = agents.ORCHESTRATOR
    emit({"type": "agent_start", "agent": orch["key"], "label": orch["label"]})
    reply = backend.call(
        system=orch["system"],
        messages=[{"role": "user", "content": orch["ask"].format(reports=reports)}],
        mock_key=orch["key"],
        mock_seconds=orch["mock_seconds"],
    )
    metrics.add(orch["label"], reply)
    emit(
        {
            "type": "agent_done",
            "agent": orch["key"],
            "label": orch["label"],
            "text": reply.text,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "ms": round(reply.ms),
        }
    )

    metrics.wall_ms = (time.perf_counter() - t0) * 1000
    return metrics.summary()


# --------------------------------------------------------------------------
# Orquestación de la comparación
# --------------------------------------------------------------------------

MODES = {
    "single": ("Un solo agente (secuencial)", run_single_agent),
    "subagents": ("Orquestador + subagentes (paralelo)", run_subagents),
}


def stream_comparison(code: str) -> Iterator[dict]:
    """Lanza los dos modos a la vez y va emitiendo eventos hasta que ambos acaban."""
    backend = make_backend()
    events: queue.Queue = queue.Queue()
    summaries: dict = {}

    def worker(mode: str, fn) -> None:
        def emit(event: dict) -> None:
            events.put({**event, "mode": mode})

        try:
            summaries[mode] = fn(code, backend, emit)
            emit({"type": "mode_done", "metrics": summaries[mode]})
        except Exception as exc:  # se muestra en la interfaz en vez de romper el stream
            emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    threads = [
        threading.Thread(target=worker, args=(mode, fn), daemon=True)
        for mode, (_, fn) in MODES.items()
    ]

    yield {
        "type": "start",
        "backend": backend.name,
        "model": agents.MODEL,
        "effort": agents.EFFORT,
    }
    for t in threads:
        t.start()

    while any(t.is_alive() for t in threads) or not events.empty():
        try:
            yield events.get(timeout=0.1)
        except queue.Empty:
            continue

    yield {"type": "done", "comparison": compare(summaries)}


def compare(summaries: dict) -> dict:
    """Diferencias entre los dos modos, ya calculadas para la interfaz."""
    single = summaries.get("single")
    subs = summaries.get("subagents")
    if not single or not subs:
        return {}

    def ratio(a: float, b: float) -> float | None:
        return round(a / b, 2) if b else None

    def saved(a: int, b: int) -> int | None:
        return round((a - b) / a * 100) if a else None

    return {
        "speedup": ratio(single["wall_ms"], subs["wall_ms"]),
        "input_tokens_saved_pct": saved(single["input_tokens"], subs["input_tokens"]),
        "peak_context_saved_pct": saved(
            single["peak_context_tokens"], subs["peak_context_tokens"]
        ),
        "cost_saved_pct": saved(single["cost_usd"], subs["cost_usd"]),
    }
