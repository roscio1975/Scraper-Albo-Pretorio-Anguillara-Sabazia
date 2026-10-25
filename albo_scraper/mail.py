from __future__ import annotations
import smtplib
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from .config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, RECEIPTS_FILE
from .log import logger

def invia_report(file_percorso: Path) -> None:
    """
    Legge i destinatari da receipts.txt e invia una mail con il file allegato.
    """
    if not SMTP_PASSWORD:
        logger.error("SMTP_PASSWORD non impostata nelle variabili d'ambiente.")
        return

    # 1. Leggi i destinatari
    try:
        with open(RECEIPTS_FILE, "r") as f:
            destinatari = [line.strip() for line in f if line.strip() and "@" in line]
    except FileNotFoundError:
        logger.error(f"File {RECEIPTS_FILE} non trovato.")
        return

    if not destinatari:
        logger.warning("Nessun destinatario valido trovato in receipts.txt")
        return

    # 2. Prepara il messaggio
    msg = EmailMessage()
    msg["Subject"] = "Ultimi atti sull’albo Pretorio"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(destinatari)
    msg.set_content(f"Ciao a tutti,\n\nIn allegato la tabella aggiornata degli atti pubblicati sull'albo pretorio.\n\nHast Siempre!.")

    # 3. Aggiungi l'allegato
    with open(file_percorso, "rb") as f:
        file_data = f.read()
        file_name = file_percorso.name
        msg.add_attachment(
            file_data, 
            maintype="application",
            subtype="octet-stream",
            filename=file_name, 
            disposition="attachment"
        )
    # 4. Invia la mail
    try:
        # Connessione al server SMTP
        logger.debug(
            f"Invio a {len(destinatari)} destinatari tramite {SMTP_SERVER}:{SMTP_PORT} "
            f"(allegato: {file_percorso.name}, {len(file_data)} byte)"
        )
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            #scommentare per debuggare problemi nell'invio della mail 
            #server.set_debuglevel(1)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            logger.info("Email inviata con successo!")
    except Exception as e:
        logger.error(f"Errore durante l'invio dell'email: {e}")
   