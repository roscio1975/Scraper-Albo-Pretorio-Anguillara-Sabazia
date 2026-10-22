"""Download dei PDF e riuso dei file già presenti in locale.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.sync_api import BrowserContext

from .log import logger


def nome_file_sicuro(testo: str, max_len: int = 150) -> str:
    """Ripulisce un testo per usarlo come nome file."""
    testo = re.sub(r'[\\/:*?"<>|]', " ", testo)  # caratteri non validi nei nomi file
    testo = " ".join(testo.split())  # normalizza gli spazi
    return testo[:max_len].rstrip(" .")


def id_documento(url: str) -> str:
    """
    Identificativo stabile del documento ricavato dall'URL: DOCORE_testata e
    DOCORE_versione (se presenti), altrimenti un hash dei parametri, ignorando il
    token di sessione FNSTR che può cambiare a ogni visita.
    """
    parametri = parse_qs(urlparse(url).query)
    testata = parametri.get("DOCORE_testata", [""])[0]
    if testata:
        versione = parametri.get("DOCORE_versione", ["1"])[0]
        return re.sub(r"[^\w.-]", "", f"{testata}-v{versione}")
    resto = sorted((k, v) for k, v in parametri.items() if k.upper() != "FNSTR")
    return hashlib.sha1(urlencode(resto, doseq=True).encode()).hexdigest()[:10]


def _e_pdf_valido(percorso: Path) -> bool:
    try:
        with open(percorso, "rb") as f:
            return b"%PDF" in f.read(1024)
    except OSError:
        return False


def trova_pdf_locale(cartella: Path, id_doc: str) -> Path | None:
    """
    Cerca in `cartella` un PDF già scaricato per questo documento: i file sono
    salvati come "<testo atto> - <descrizione> [<id>].pdf". Un file vuoto o
    corrotto viene ignorato, così verrà riscaricato.
    """
    if not cartella.is_dir():
        return None
    for percorso in sorted(cartella.glob("*.pdf")):
        if percorso.name.endswith(f"[{id_doc}].pdf"):
            if _e_pdf_valido(percorso):
                return percorso
            logger.error(f"File locale non valido, verrà riscaricato: {percorso}")
    return None


def scarica_pdf(
    context: BrowserContext,
    url: str,
    testo_atto: str,
    descrizione: str,
    cartella: Path,
) -> Path | None:
    """
    Restituisce il percorso locale del PDF. Se il documento è già presente in
    `cartella` non viene scaricato e si usa il file esistente; altrimenti lo scarica
    con la sessione (cookie) del browser e lo salva come
    "<testo atto> - <descrizione allegato> [<id>].pdf".
    Restituisce None se il download non è valido.
    """
    cartella.mkdir(parents=True, exist_ok=True)
    id_doc = id_documento(url)

    esistente = trova_pdf_locale(cartella, id_doc)
    if esistente:
        logger.info(f"   già presente in locale, download saltato: {esistente}")
        return esistente

    logger.debug(f"GET {url}")
    risposta = context.request.get(url, timeout=60_000)
    if not risposta.ok:
        logger.error(f"Download fallito (HTTP {risposta.status}): {url}")
        return None

    contenuto = risposta.body()
    if b"%PDF" not in contenuto[:1024]:
        logger.error(f"Il contenuto scaricato non è un PDF: {url}")
        return None

    base = nome_file_sicuro(testo_atto, 120)
    if descrizione:
        base += " - " + nome_file_sicuro(descrizione, 40)

    destinazione = cartella / f"{base} [{id_doc}].pdf"
    temporaneo = destinazione.with_name(destinazione.name + ".part")
    temporaneo.write_bytes(contenuto)
    temporaneo.replace(destinazione)  # scrittura atomica: niente file a metà
    logger.info(f"   scaricato: {destinazione}")
    logger.debug(f"Salvato {destinazione} ({len(contenuto)} byte)")
    return destinazione
