"""Chiamate al server Ollama (API /api/chat), usate da riassunti e diario."""

from __future__ import annotations

import json
import urllib.request

from .config import NUM_CTX, OLLAMA_URL
from .log import logger


def chiedi_a_ollama(
    prompt: str,
    modello: str,
    url: str = OLLAMA_URL,
    num_ctx: int = NUM_CTX,
    temperatura: float | None = None,
    timeout: int = 300,
) -> str:
    """
    Invia `prompt` al modello `modello` del server Ollama in `url` e restituisce la risposta.
    `num_ctx` è la finestra di contesto richiesta; `temperatura=None` usa quella del modello.
    Solleva un'eccezione (URLError, TimeoutError, KeyError...) se la chiamata non riesce.
    """
    opzioni: dict = {"num_ctx": num_ctx}
    if temperatura is not None:
        opzioni["temperature"] = temperatura

    payload = {
        "model": modello,
        "stream": False,
        "options": opzioni,
        "messages": [{"role": "user", "content": prompt}],
    }
    # Nel log solo l'inizio del prompt: contiene il testo degli atti, che può essere lungo
    logger.debug(
        f"Richiesta a Ollama ({url}, modello {modello}, num_ctx {num_ctx}): "
        f"{len(prompt)} caratteri, inizio: {prompt[:300]!r}"
    )
    richiesta = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
        dati = json.load(risposta)
    return dati["message"]["content"].strip()
