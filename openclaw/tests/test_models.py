#!/usr/bin/env python3
# =============================================================================
# OpenClaw Orchestrator — tests
# =============================================================================
# Verifica que la configuracion sea coherente y que los modelos Ollama esten
# disponibles ANTES de correr el batch de enriquecimiento.
#
# Ejecutar con pytest:        pytest openclaw/tests/
# Ejecutar sin pytest:        python3 openclaw/tests/test_models.py
#
# Convenciones de resultado:
#   - Los tests de configuracion son puros y siempre corren.
#   - Si Ollama no responde, los tests dependientes se SALTAN (no fallan),
#     porque la maquina puede no tener el servidor levantado.
#   - Si Ollama responde pero falta un modelo, el test FALLA con la instruccion
#     exacta de `ollama pull` a ejecutar.
# =============================================================================
import sys
from pathlib import Path
from unittest import SkipTest  # pytest tambien lo interpreta como "skip"

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

import run_batch  # noqa: E402

CONFIG_PATH = MODULE_DIR / "config.json"
MODELOS_ESPERADOS = {"qwen2.5:7b", "llama3.1:8b"}


def _skip(reason: str):
    """Salta el test (compatible con pytest y con el runner propio)."""
    raise SkipTest(reason)


def _config() -> dict:
    return run_batch.load_config(CONFIG_PATH)


# ─── CONFIGURACION (puros, siempre corren) ──────────────────────────────────
def test_config_es_json_valido():
    cfg = _config()
    assert cfg.get("version", 0) >= 1
    assert isinstance(cfg.get("agentes"), dict)


def test_tres_agentes_definidos():
    agentes = _config()["agentes"]
    assert set(agentes) == {"orquestador", "descubridor", "redactor"}, \
        f"agentes inesperados: {sorted(agentes)}"
    for nombre, a in agentes.items():
        assert a.get("model"), f"el agente '{nombre}' no declara modelo"
        assert a.get("system_prompt"), f"el agente '{nombre}' no tiene system_prompt"


def test_modelos_declarados_son_los_esperados():
    modelos = run_batch.required_models(_config())
    assert modelos <= MODELOS_ESPERADOS, \
        f"modelos fuera de lo esperado: {modelos - MODELOS_ESPERADOS}"
    assert "qwen2.5:7b" in modelos, "ningun agente usa qwen2.5:7b"
    assert "llama3.1:8b" in modelos, "ningun agente usa llama3.1:8b"


# ─── DISPONIBILIDAD DE OLLAMA (se saltan si no hay servidor) ────────────────
def test_ollama_responde():
    client = run_batch.OllamaClient.from_config(_config())
    try:
        client.list_models()
    except Exception as e:  # noqa: BLE001
        _skip(f"Ollama no responde en {client.host}: {e}")


def test_modelos_disponibles_antes_del_batch():
    cfg = _config()
    client = run_batch.OllamaClient.from_config(cfg)
    ok, report = run_batch.verify_models(cfg, client)
    if not report["ollama_ok"]:
        _skip(f"Ollama no responde en {report['host']}: {report.get('error', '')}")
    assert ok, (
        "Faltan modelos en Ollama: " + ", ".join(report["faltantes"]) + ". "
        "Descargalos con: "
        + " ; ".join(f"ollama pull {m}" for m in report["faltantes"])
    )


# ─── RUNNER PROPIO (sin pytest) ─────────────────────────────────────────────
def _run_cli() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = skipped = failed = 0
    print(f"OpenClaw Orchestrator — {len(tests)} test(s)\n")
    for t in tests:
        try:
            t()
            print(f"  PASS   {t.__name__}")
            passed += 1
        except SkipTest as s:
            print(f"  SKIP   {t.__name__} — {s}")
            skipped += 1
        except AssertionError as e:
            print(f"  FAIL   {t.__name__} — {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR  {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} pass, {skipped} skip, {failed} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_cli())
