"""Invio della tabella finale per email (SMTP)."""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from .config import (
    EMAIL_FROM,
    RECEIPTS_FILE,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USER,
)
from .log import logger

TIMEOUT_SMTP = 30.0  # secondi: evita che una connessione bloccata fermi lo script
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _leggi_destinatari(percorso: str | Path | None = None) -> list[str]:
    """
    Legge un indirizzo per riga, ignorando righe vuote, duplicati e indirizzi non validi.
    `parseaddr` normalizza il valore e impedisce che caratteri di controllo (es. CR/LF)
    finiscano negli header della mail.
    """
    percorso = Path(percorso) if percorso else Path(RECEIPTS_FILE)
    try:
        righe = percorso.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.error(f"Impossibile leggere {percorso}: {e}")
        return []

    destinatari: list[str] = []
    for numero, riga in enumerate(righe, 1):
        grezza = riga.strip()
        if not grezza:
            continue
        # Una riga tipo "Bcc: altro@example.it" non è un destinatario ma un tentativo
        # di aggiungere header: parseaddr la accetterebbe, quindi la scartiamo prima.
        if ":" in grezza and "<" not in grezza:
            logger.warning(f"Destinatario non valido in {percorso}:{numero}, riga ignorata")
            continue
        _, indirizzo = parseaddr(grezza)
        if not _RE_EMAIL.match(indirizzo):
            logger.warning(f"Destinatario non valido in {percorso}:{numero}, riga ignorata")
            continue
        if indirizzo not in destinatari:
            destinatari.append(indirizzo)
    return destinatari


def invia_report(file_percorso: Path, timeout: float = TIMEOUT_SMTP) -> bool:
    """
    Legge i destinatari da receipts.txt e invia una mail con il file allegato.
    Restituisce True se l'invio è riuscito, False altrimenti (il motivo è nel log).
    `timeout` limita l'attesa della connessione SMTP.
    """
    if not SMTP_PASSWORD:
        logger.error("SMTP_PASSWORD non impostata nelle variabili d'ambiente.")
        return False

    destinatari = _leggi_destinatari()
    if not destinatari:
        logger.warning("Nessun destinatario valido trovato in receipts.txt")
        return False

    percorso = Path(file_percorso)
    try:
        file_data = percorso.read_bytes()
    except OSError as e:
        logger.error(f"Impossibile leggere l'allegato {percorso}: {e}")
        return False

    msg = EmailMessage()
    msg["Subject"] = "Ultimi atti sull’albo Pretorio"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(destinatari)
    msg.set_content(
        "Ciao a tutti,\n\nIn allegato la tabella aggiornata degli atti pubblicati "
        "sull'albo pretorio.\n\nHast Siempre!."
    )
    msg.add_attachment(
        file_data,
        maintype="application",
        subtype="octet-stream",
        filename=percorso.name,
    )

    try:
        logger.debug(
            f"Invio a {len(destinatari)} destinatari tramite {SMTP_SERVER}:{SMTP_PORT} "
            f"(allegato: {percorso.name}, {len(file_data)} byte)"
        )
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=timeout) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        logger.error(f"Errore durante l'invio dell'email: {e}")
        return False

    logger.info("Email inviata con successo!")
    return True
