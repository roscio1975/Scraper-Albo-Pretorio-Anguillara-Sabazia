"""Logging su file e/o console con timestamp e livello.
"""

from __future__ import annotations

import logging
import re

from .config import FORMATO_DATA, FORMATO_LOG, LOG_FILE


logger = logging.getLogger("scraper_albo")

# Parametri di URL che contengono token/sessioni: nei log vanno oscurati, perché i file
# di log vengono condivisi (bug report, issue) e i token non devono uscire dal browser.
_RE_TOKEN_URL = re.compile(
    r"([?&;](?:FNSTR|SESSION|SESSIONID|JSESSIONID|PHPSESSID|SID|TOKEN|API_KEY|PASSWORD)=)"
    r"[^&\s#]+",
    re.IGNORECASE,
)


def url_sicuro(url: str) -> str:
    """URL con i parametri di sessione/token sostituiti da `***`, da usare nei log."""
    return _RE_TOKEN_URL.sub(r"\1***", url)


class _FormatoConsole(logging.Formatter):
    """Come Formatter, ma senza traceback: sulla console basta il messaggio."""

    def format(self, record: logging.LogRecord) -> str:
        exc_info, exc_text = record.exc_info, record.exc_text
        record.exc_info = record.exc_text = None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text = exc_info, exc_text


def configura_logging(
    file_log: str = LOG_FILE,
    livello_file: int = logging.DEBUG,
    console: bool = True,
    livello_console: int = logging.INFO,
    su_file: bool = True,
) -> None:
    """
    Configura il logging (timestamp + livello) su file e/o console.
    - su_file=True: scrive su `file_log` (in append) i messaggi da `livello_file`
      in su, con i traceback degli errori.
    - console=True: scrive sulla console i messaggi da `livello_console` in su
      (senza traceback se si registra anche su file).
    """
    if not su_file and not console:
        raise ValueError("serve almeno una destinazione: file o console")

    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)  # il filtro vero è negli handler
    logger.propagate = False

    if su_file:
        handler_file = logging.FileHandler(file_log, encoding="utf-8")
        handler_file.setLevel(livello_file)
        handler_file.setFormatter(logging.Formatter(FORMATO_LOG, FORMATO_DATA))
        logger.addHandler(handler_file)

    if console:
        handler_console = logging.StreamHandler()
        handler_console.setLevel(livello_console)
        classe_formato = _FormatoConsole if su_file else logging.Formatter
        handler_console.setFormatter(classe_formato(FORMATO_LOG, FORMATO_DATA))
        logger.addHandler(handler_console)
