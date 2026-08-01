#!/usr/bin/env python3
# =============================================================================
# OpenClaw Orchestrator — tests
# =============================================================================
# Verifica que la configuracion sea coherente y que los modelos declarados
# esten disponibles en el backend configurado ANTES de correr el batch.
#
# Los tests NO conocen ningun nombre de modelo: validan que cada agente declare
# alguno y que ese alguno exista en el backend. Cambiar de modelo o de backend
# es editar config.json (o el entorno), no este archivo.
#
# Ejecutar con pytest:        pytest openclaw/tests/
# Ejecutar sin pytest:        python3 openclaw/tests/test_models.py
#
# Convenciones de resultado:
#   - Los tests de configuracion son puros y siempre corren.
#   - Si el backend no responde, los tests dependientes se SALTAN (no fallan),
#     porque la maquina puede no tener el servidor levantado.
#   - Si el backend responde pero falta un modelo declarado, el test FALLA
#     nombrando exactamente cual.
# =============================================================================
import sys
from pathlib import Path
from unittest import SkipTest  # pytest tambien lo interpreta como "skip"

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

import run_batch  # noqa: E402

CONFIG_PATH = MODULE_DIR / "config.json"


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
    assert set(agentes) == {"orquestador", "descubridor", "summarizer"}, \
        f"agentes inesperados: {sorted(agentes)}"
    for nombre, a in agentes.items():
        assert a.get("system_prompt"), f"el agente '{nombre}' no tiene system_prompt"


def test_cada_agente_declara_un_modelo():
    """Cada agente resuelve a ALGUN modelo. Cual sea es irrelevante aqui."""
    cfg = _config()
    for nombre in cfg["agentes"]:
        modelo = run_batch.agent_model(cfg, nombre)
        assert modelo, (
            f"el agente '{nombre}' no resuelve a ningun modelo: declaralo en "
            f"config.json o en {run_batch.model_env_var(nombre)}")


def test_el_entorno_puede_sobreescribir_el_modelo(monkeypatch=None):
    """El modelo viene de config, pero el entorno manda."""
    import os
    cfg = _config()
    nombre = sorted(cfg["agentes"])[0]
    var = run_batch.model_env_var(nombre)
    previo = os.environ.get(var)
    os.environ[var] = "modelo-de-prueba:0b"
    try:
        assert run_batch.agent_model(cfg, nombre) == "modelo-de-prueba:0b", \
            f"{var} no sobreescribe el modelo de config.json"
    finally:
        if previo is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = previo


def test_el_endpoint_no_esta_quemado_en_el_codigo():
    """El backend se configura; el codigo no trae un endpoint fijo."""
    import os
    cfg = _config()
    previo = os.environ.get("LLM_BASE_URL")
    os.environ["LLM_BASE_URL"] = "http://backend-de-prueba:9999"
    try:
        client = run_batch.OllamaClient.from_config(cfg)
        assert client.host == "http://backend-de-prueba:9999", \
            "LLM_BASE_URL no sobreescribe el endpoint"
    finally:
        if previo is None:
            os.environ.pop("LLM_BASE_URL", None)
        else:
            os.environ["LLM_BASE_URL"] = previo


# ─── DISPONIBILIDAD DE OLLAMA (se saltan si no hay servidor) ────────────────
def test_el_backend_responde():
    client = run_batch.OllamaClient.from_config(_config())
    try:
        client.list_models()
    except Exception as e:  # noqa: BLE001
        _skip(f"el backend LLM no responde en {client.host}: {e}")


def test_los_modelos_declarados_estan_en_el_backend():
    """Cada modelo declarado existe en el backend configurado, sea cual sea."""
    cfg = _config()
    client = run_batch.OllamaClient.from_config(cfg)
    ok, report = run_batch.verify_models(cfg, client)
    if not report["ollama_ok"]:
        _skip(f"el backend no responde en {report['host']}: {report.get('error', '')}")
    assert ok, (
        f"modelos declarados que faltan en {report['host']}: "
        + ", ".join(report["faltantes"])
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
