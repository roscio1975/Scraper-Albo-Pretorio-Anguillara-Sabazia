"""
Scraper dell'albo pretorio (cloud.urbi.it) - Comune di Anguillara Sabazia.

Flusso:
1. apre il sito e clicca "Avanti" per caricare la tabella degli atti
2. legge ogni riga (ente, tipologia, testo, data inizio, data fine)
3. per ogni riga apre la modale "Pubblicazione" e ricava i link dei PDF
   (il badge "FILE" = documento contenuto nella busta firmata P7M)
4. opzionalmente scarica i PDF (quelli già presenti in locale non vengono riscaricati)
5. opzionalmente genera un riassunto di ogni PDF con un LLM locale (Ollama); le pagine
   scansionate (senza testo) vengono prima lette con l'OCR
6. scrive un file HTML con la tabella: data atto, titolo, link remoto al PDF, riassunto

Moduli:
    config      costanti e impostazioni di default
    log         logging su file e/o console
    filtri      conversione e filtro delle date
    sito        interazione con il sito (tabella, modale, link)
    pdf         download dei PDF e riuso dei file locali
    riassunti   riassunti con Ollama
    ocr         OCR (Tesseract) delle pagine scansionate dei PDF
    report      tabella HTML finale
    pipeline    flusso principale (stampa_link_pdf)
    debug       modalità debug (HTML/screenshot della modale)
    cli         interfaccia da riga di comando
"""

from .pipeline import stampa_link_pdf
from .report import scrivi_tabella

__all__ = ["stampa_link_pdf", "scrivi_tabella"]
