"""Riassunti dei PDF con un LLM locale servito da Ollama.
"""

from __future__ import annotations

from pathlib import Path

from .config import MAX_CARATTERI, MODELLO_LOCALE, NUM_CTX, OLLAMA_URL, PROMPT_RIASSUNTO
from .log import logger


def estrai_testo_pdf(percorso: str | Path) -> str:
    """Estrae il testo da un PDF (serve `pip install pypdf`)."""
    from pypdf import PdfReader

    lettore = PdfReader(str(percorso))
    testo = "\n".join((pagina.extract_text() or "") for pagina in lettore.pages)
    return testo.strip()


def riassumi_pdf_locale(
    percorso: str | Path,
    modello: str = MODELLO_LOCALE,
    url: str = OLLAMA_URL,
    max_righe: int = 4,
) -> str:
    """
    Riassume un PDF con un LLM locale servito da Ollama.
    Il testo viene estratto con pypdf e inviato al modello (nessun dato esce dal PC).
    """
    import json
    import urllib.request

    testo = estrai_testo_pdf(percorso)
    if not testo:
        raise RuntimeError("il PDF non contiene testo (probabile scansione: serve OCR)")
    logger.debug(
        f"Testo estratto da {Path(percorso).name}: {len(testo)} caratteri "
        f"(inviati al massimo {MAX_CARATTERI}) - modello {modello}"
    )
    testo = testo[:MAX_CARATTERI]

    istruzioni = PROMPT_RIASSUNTO.format(max_righe=max_righe)
    payload = {
        "model": modello,
        "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.2},
        "messages": [
            {"role": "user", "content": f"{istruzioni}\n\nTESTO DELL'ATTO:\n{testo}"}
        ],
    }
    richiesta = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(richiesta, timeout=300) as risposta:
        dati = json.load(risposta)
    return dati["message"]["content"].strip()
