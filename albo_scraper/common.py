"""Dispatcher per le chiamate LLM: sceglie Omlx oppure Ollama in base al provider."""

from __future__ import annotations

from .config import (
    MODELLO_LOCALE,
    MODELLO_OMLX,
    NUM_CTX_FALLBACK,
    OLLAMA_URL,
    OMLX_URL,
)
from .ollama import chiedi_a_ollama
from .omlx import chiedi_a_omlx

PROVIDER_VALIDI = ("omlx", "ollama")


def _normalizza_provider(provider: str | None) -> str:
    valore = (provider or "omlx").strip().lower()
    if valore not in PROVIDER_VALIDI:
        raise ValueError(
            f"provider non riconosciuto: {provider!r} (usa 'omlx' oppure 'ollama')"
        )
    return valore


def chiedi_llm(
    provider: str,
    prompt: str,
    *,
    modello: str | None = None,
    url: str | None = None,
    num_ctx: int | None = None,
    temperatura: float | None = None,
    max_caratteri: int | None = None,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> str:
    """
    Invia `prompt` al provider scelto e restituisce la risposta.

    - `provider="omlx"`: usa l'API OpenAI-compatibile; `modello` e `url` hanno
      come default MODELLO_OMLX e OMLX_URL.
    - `provider="ollama"`: usa l'API locale; `modello` e `url` hanno come default
      MODELLO_LOCALE e OLLAMA_URL. `max_caratteri`/`max_tokens` sono ignorati
      (il testo viene già troncato prima della chiamata).

    `timeout` ha un default diverso per provider (Omlx 120s, Ollama 300s).
    """
    provider = _normalizza_provider(provider)

    if provider == "omlx":
        return chiedi_a_omlx(
            prompt,
            modello=modello or MODELLO_OMLX,
            url=url or OMLX_URL,
            num_ctx=num_ctx,
            temperatura=temperatura,
            max_caratteri=max_caratteri,
            max_tokens=max_tokens,
            timeout=120 if timeout is None else timeout,
        )

    return chiedi_a_ollama(
        prompt,
        modello=modello or MODELLO_LOCALE,
        url=url or OLLAMA_URL,
        num_ctx=NUM_CTX_FALLBACK if num_ctx is None else num_ctx,
        temperatura=temperatura,
        timeout=300 if timeout is None else timeout,
    )
