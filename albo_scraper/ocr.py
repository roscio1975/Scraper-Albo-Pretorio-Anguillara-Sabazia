"""OCR delle pagine scansionate dei PDF con Tesseract."""

from __future__ import annotations

from pathlib import Path

from .config import OCR_DPI, OCR_LINGUA
from .log import logger

INSTALLAZIONE_TESSERACT = (
    "Installa Tesseract con la lingua italiana: "
    "macOS: `brew install tesseract tesseract-lang` - "
    "Debian/Ubuntu: `apt install tesseract-ocr tesseract-ocr-ita`"
)


class OcrNonDisponibile(RuntimeError):
    """OCR richiesto ma Tesseract, la lingua o le librerie Python non sono installati."""


class LettoreOcr:
    """
    Trasforma in immagine le pagine di un PDF e le legge con Tesseract.
    Il PDF viene aperto solo al primo utilizzo, quindi i PDF con testo non costano nulla.
    Si usa con `with LettoreOcr(percorso) as ocr: ocr.testo_pagina(0)`.
    """

    def __init__(self, percorso: str | Path, lingua: str = OCR_LINGUA, dpi: int = OCR_DPI):
        self.percorso = Path(percorso)
        self.lingua = lingua
        self.dpi = dpi
        self._pdf = None
        self._pytesseract = None

    def __enter__(self) -> "LettoreOcr":
        return self

    def __exit__(self, *args) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None

    def _prepara(self) -> None:
        if self._pdf is not None:
            return
        try:
            import pypdfium2
            import pytesseract
        except ImportError as e:
            raise OcrNonDisponibile(
                f"libreria OCR mancante ({e.name}): "
                "pip install pypdfium2 pytesseract pillow"
            ) from e
        self._pytesseract = pytesseract
        self._pdf = pypdfium2.PdfDocument(str(self.percorso))

    def testo_pagina(self, indice: int) -> str:
        """Testo riconosciuto con l'OCR nella pagina `indice` (da 0)."""
        self._prepara()
        immagine = self._pdf[indice].render(scale=self.dpi / 72).to_pil()
        try:
            testo = self._pytesseract.image_to_string(immagine, lang=self.lingua)
        except self._pytesseract.TesseractNotFoundError as e:
            raise OcrNonDisponibile(f"Tesseract non trovato. {INSTALLAZIONE_TESSERACT}") from e
        except self._pytesseract.TesseractError as e:
            msg = str(e).lower()
            if "failed loading language" in msg or "error opening data file" in msg:
                raise OcrNonDisponibile(
                    f"lingua OCR '{self.lingua}' non installata in Tesseract. "
                    f"{INSTALLAZIONE_TESSERACT}"
                ) from e
            raise
        logger.debug(
            f"OCR di {self.percorso.name}, pagina {indice + 1}: {len(testo.strip())} caratteri"
        )
        return testo.strip()
