"""Riassunti dei PDF con un LLM (Omlx o Ollama)."""

from __future__ import annotations

from pathlib import Path

from .common import chiedi_llm, normalizza_provider
from .config import (
    MAX_CARATTERI_FALLBACK,
    MAX_CARATTERI_OMLX,
    MIN_CARATTERI_PAGINA,
    OCR_LINGUA,
    PROMPT_RIASSUNTO,
)
from .log import logger
from .ocr import LettoreOcr


def estrai_testo_pdf(
    percorso: str | Path,
    ocr: bool = True,
    lingua_ocr: str = OCR_LINGUA,
    max_caratteri: int | None = MAX_CARATTERI_FALLBACK,
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


def riassumi_pdf(
    percorso: str | Path,
    provider: str = "omlx",
    modello: str | None = None,
    url: str | None = None,
    max_righe: int = 4,
    ocr: bool = True,
    lingua_ocr: str = OCR_LINGUA,
    max_caratteri: int | None = None,
) -> str:
    """
    Riassume un PDF con il provider scelto (`omlx` oppure `ollama`).
    Il testo viene estratto con pypdf (e con l'OCR per le pagine scansionate, se `ocr`)
    e inviato al modello.

    `max_caratteri` limita il testo inviato: se non indicato vale MAX_CARATTERI_OMLX
    (10000) con Omlx e MAX_CARATTERI_FALLBACK (12000) con Ollama.
    """
    provider = normalizza_provider(provider)
    if max_caratteri is None:
        max_caratteri = (
            MAX_CARATTERI_OMLX if provider == "omlx" else MAX_CARATTERI_FALLBACK
        )

    testo = estrai_testo_pdf(
        percorso, ocr=ocr, lingua_ocr=lingua_ocr, max_caratteri=max_caratteri
    )
    if not testo:
        raise RuntimeError(
            "nessun testo trovato nemmeno con l'OCR"
            if ocr
            else "il PDF non contiene testo (probabile scansione: abilita l'OCR con --ocr true)"
        )
    logger.debug(
        f"Testo estratto da {Path(percorso).name}: {len(testo)} caratteri "
        f"(inviati al massimo {max_caratteri}) - provider {provider}"
    )
    testo = testo[:max_caratteri]

    istruzioni = PROMPT_RIASSUNTO.format(max_righe=max_righe)
    prompt = f"{istruzioni}\n\nTESTO DELL'ATTO:\n{testo}"
    return chiedi_llm(
        provider,
        prompt,
        modello=modello,
        url=url,
        temperatura=0.2,
        max_tokens=512,
        timeout=300,
    )


# Nome storico mantenuto per compatibilità con eventuale codice esterno.
riassumi_pdf_locale = riassumi_pdf
