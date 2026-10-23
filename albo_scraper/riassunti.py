"""Riassunti dei PDF con un LLM locale servito da Ollama.
"""

from __future__ import annotations

from pathlib import Path

from .config import (
    MAX_CARATTERI,
    MIN_CARATTERI_PAGINA,
    MODELLO_LOCALE,
    NUM_CTX,
    OCR_LINGUA,
    OLLAMA_URL,
    PROMPT_RIASSUNTO,
)
from .log import logger
from .ocr import LettoreOcr


def estrai_testo_pdf(
    percorso: str | Path,
    ocr: bool = True,
    lingua_ocr: str = OCR_LINGUA,
    max_caratteri: int | None = MAX_CARATTERI,
) -> str:
    """
    Estrae il testo da un PDF pagina per pagina con pypdf. Le pagine senza testo
    (scansioni) vengono lette con l'OCR se `ocr=True`; le altre non lo usano mai.
    Si ferma appena raggiunge `max_caratteri`, così di un lungo documento scansionato
    si leggono con l'OCR solo le prime pagine.
    """
    from pypdf import PdfReader

    lettore = PdfReader(str(percorso))
    testi: list[str] = []
    totale = 0

    with LettoreOcr(percorso, lingua_ocr) as lettore_ocr:
        for indice, pagina in enumerate(lettore.pages):
            testo = (pagina.extract_text() or "").strip()

            if ocr and len(testo) < MIN_CARATTERI_PAGINA:
                logger.info(f"   pagina {indice + 1} senza testo: uso l'OCR ({lingua_ocr})")
                testo_ocr = lettore_ocr.testo_pagina(indice)
                if len(testo_ocr) > len(testo):
                    testo = testo_ocr

            if testo:
                testi.append(testo)
                totale += len(testo)
            if max_caratteri and totale >= max_caratteri:
                break

    return "\n".join(testi).strip()


def riassumi_pdf_locale(
    percorso: str | Path,
    modello: str = MODELLO_LOCALE,
    url: str = OLLAMA_URL,
    max_righe: int = 4,
    ocr: bool = True,
    lingua_ocr: str = OCR_LINGUA,
) -> str:
    """
    Riassume un PDF con un LLM locale servito da Ollama.
    Il testo viene estratto con pypdf (e con l'OCR per le pagine scansionate, se `ocr`)
    e inviato al modello: nessun dato esce dal PC.
    """
    import json
    import urllib.request

    testo = estrai_testo_pdf(percorso, ocr=ocr, lingua_ocr=lingua_ocr)
    if not testo:
        raise RuntimeError(
            "nessun testo trovato nemmeno con l'OCR"
            if ocr
            else "il PDF non contiene testo (probabile scansione: abilita l'OCR con --ocr true)"
        )
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
    logger.debug(f"PAYLOAD:  {payload}")
    richiesta = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(richiesta, timeout=300) as risposta:
        dati = json.load(risposta)
    return dati["message"]["content"].strip()
