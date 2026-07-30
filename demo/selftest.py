"""Comprobación automática de la demo, sin navegador y sin clave de API.

Ejecuta la comparación completa en modo DEMO y verifica que las ventajas que la
interfaz afirma se cumplen de verdad en los números medidos.

Uso:  python -m demo.selftest
"""

from __future__ import annotations

import os
import sys

os.environ["DEMO_MODE"] = "1"  # antes de importar el runner: fuerza respuestas simuladas

from . import agents, runner  # noqa: E402


def main() -> int:
    print(f"Modo: {runner.backend_mode()}  ·  modelo configurado: {agents.MODEL}")
    print("Ejecutando los dos modos en paralelo (tarda ~11 s por las latencias simuladas)…\n")

    summaries: dict = {}
    comparison: dict = {}
    errors: list = []

    for event in runner.stream_comparison(agents.SAMPLE_CODE):
        if event["type"] == "mode_done":
            summaries[event["mode"]] = event["metrics"]
        elif event["type"] == "done":
            comparison = event["comparison"]
        elif event["type"] == "error":
            errors.append(f"{event['mode']}: {event['message']}")

    if errors:
        print("FALLO: la ejecución produjo errores:")
        for e in errors:
            print("  -", e)
        return 1

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, bool(ok), detail))

    single, subs = summaries.get("single"), summaries.get("subagents")
    check("los dos modos terminan", bool(single and subs), f"modos: {sorted(summaries)}")
    if not (single and subs):
        _report(checks)
        return 1

    for mode, m in (("single", single), ("subagents", subs)):
        print(
            f"  {mode:10} tiempo={m['wall_ms'] / 1000:5.1f}s  llamadas={m['calls']}  "
            f"entrada={m['input_tokens']:5} tok  salida={m['output_tokens']:4} tok  "
            f"contexto_max={m['peak_context_tokens']:5} tok  coste=${m['cost_usd']}"
        )
    print()

    check("mismo nº de llamadas en los dos modos", single["calls"] == subs["calls"],
          f"{single['calls']} vs {subs['calls']}")
    check("los subagentes tardan menos (paralelismo)", subs["wall_ms"] < single["wall_ms"],
          f"{subs['wall_ms']}ms < {single['wall_ms']}ms")
    check("los subagentes gastan menos tokens de entrada",
          subs["input_tokens"] < single["input_tokens"],
          f"{subs['input_tokens']} < {single['input_tokens']}")
    check("los subagentes usan menos contexto en su llamada mayor",
          subs["peak_context_tokens"] < single["peak_context_tokens"],
          f"{subs['peak_context_tokens']} < {single['peak_context_tokens']}")
    check("el contexto del agente único crece turno a turno",
          [c["input_tokens"] for c in single["detail"]]
          == sorted(c["input_tokens"] for c in single["detail"]),
          str([c["input_tokens"] for c in single["detail"]]))
    check("la comparación trae las cuatro métricas",
          all(comparison.get(k) is not None for k in
              ("speedup", "input_tokens_saved_pct", "peak_context_saved_pct", "cost_saved_pct")),
          str(comparison))

    return _report(checks)


def _report(checks: list) -> int:
    failed = 0
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'FALLO'}] {name}  ({detail})")
        if not ok:
            failed += 1
    print()
    if failed:
        print(f"{failed} comprobación(es) fallida(s).")
        return 1
    print(f"{len(checks)} comprobaciones correctas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
