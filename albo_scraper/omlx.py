"""Chiamate al server Omlx (API OpenAI-compatibile), usate da riassunti e diario."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import (
    OMLX_API_KEY,
    OMLX_URL,
    MODELLO_OMLX,
    MAX_CARATTERI_OMLX,
)
from .log import logger


def _endpoint(url: str) -> str:
    """Trasforma la base dell'API (es. .../v1) nell'URL della chat completions."""
    base = (url or OMLX_URL).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def chiedi_a_omlx(
    prompt: str,
    modello: str = MODELLO_OMLX,
    url: str = OMLX_URL,
    temperatura: float | None = None,
    max_caratteri: int | None = MAX_CARATTERI_OMLX,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> str:
    """
    Invia `prompt` al modello Omlx in `url` e restituisce la risposta.

    L'API è quella OpenAI-compatibile (`POST {url}/chat/completions`).
    `max_tokens` limita la lunghezza della risposta e `max_caratteri` tronca il
    testo restituito.
    Con `enable_thinking=False` si evita che i modelli "reasoning" consumino
    tutti i token nel campo `reasoning_content` senza produrre `content`.

    Solleva un'eccezione se la chiamata non riesce (timeout, errori HTTP, ecc.).
    """
    if not OMLX_API_KEY:
        raise ValueError(
            "La variabile d'ambiente OMLX_API_KEY è obbligatoria per usare "
            "--provider omlx.\n"
            'Impostala prima di avviare: export OMLX_API_KEY="..."\n'
            "In alternativa usa --provider ollama (modello locale, nessuna chiave)."
        )

    body: dict = {
        "model": modello,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if temperatura is not None:
        body["temperature"] = temperatura
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OMLX_API_KEY}",
    }
    endpoint = _endpoint(url)

    logger.info(f"Inizio chiamata a Omlx ({modello}) su {endpoint}...")

    richiesta = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            dati = json.load(risposta)
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Errore HTTP {e.code} da Omlx: {dettaglio}") from e

    try:
        output = dati["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Risposta Omlx non valida: {dati!r}") from e

    output = output.strip()
    if max_caratteri and len(output) > max_caratteri:
        output = output[:max_caratteri]

    if output:
        logger.info(f"Omlx ha restituito {len(output)} caratteri.")
    else:
        logger.warning("Omlx ha restituito una risposta vuota.")
    return output
