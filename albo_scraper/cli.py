"""Interfaccia da riga di comando.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from .config import (
    DESCRIZIONI_ESCLUSE,
    LOG_FILE,
    MODELLO_LOCALE,
    OCR_LINGUA,
    OLLAMA_URL,
    STATO_FILE,
)
from .debug import debug_modale
from .log import configura_logging, logger
from .pipeline import stampa_link_pdf
from .report import scrivi_tabella


def _bool(valore: str) -> bool:
    """Converte true/false (e varianti) in bool, per gli argomenti da riga di comando."""
    v = str(valore).strip().lower()
    if v in ("true", "t", "1", "si", "sì", "s", "yes", "y"):
        return True
    if v in ("false", "f", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"valore non valido: {valore!r} (usa true o false)")


def _data_cli(valore: str) -> date:
    """Converte 'GG-MM-AAAA' oppure 'oggi' in date."""
    if valore.strip().lower() == "oggi":
        return date.today()
    try:
        return datetime.strptime(valore, "%d-%m-%Y").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"data non valida: {valore!r} (usa GG-MM-AAAA oppure 'oggi')"
        ) from None


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Mostra i valori predefiniti e mantiene la formattazione dell'epilogo."""


EPILOGO_HELP = """\
esempi:
  python scraper_albo.py                                  link + download dei PDF
  python scraper_albo.py --scarica false                  solo link, niente download
  python scraper_albo.py --livello-log debug --log file   log dettagliato solo su file
  python scraper_albo.py --debug true                     salva HTML/screenshot della modale
  python scraper_albo.py --output risultati.html         nome del file HTML con la tabella finale
  python scraper_albo.py --dal 01-10-2026 --al oggi       solo gli atti in quell'intervallo
  python scraper_albo.py --riassumi true --modello gemma3:12b
                                                          riassunti con un modello Ollama a scelta
  python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"
                                                          esclude anche questo tipo di allegato
"""


def _crea_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scraper dell'albo pretorio: legge gli atti, ricava i link dei PDF,\n"
            "li scarica e (opzionale) li riassume con un LLM locale (Ollama)."
        ),
        formatter_class=_HelpFormatter,
        epilog=EPILOGO_HELP,
    )
    bool_kw = dict(type=_bool, nargs="?", const=True, metavar="true|false")

    princ = parser.add_argument_group("opzioni principali")
    princ.add_argument(
        "--livello-log", type=str.lower, choices=["debug", "info", "error"],
        default="info", help="livello minimo dei messaggi registrati",
    )
    princ.add_argument(
        "--log", choices=["console", "file", "entrambi"], default="entrambi",
        help="dove scrivere il log",
    )
    princ.add_argument(
        "--debug", default=False,
        help="modalità debug: salva HTML e screenshot della modale della prima riga "
        "ed esce, senza scaricare nulla (browser visibile se c'è uno schermo)", **bool_kw,
    )
    princ.add_argument(
        "--scarica", default=True,
        help="scarica i PDF (false = stampa solo i link)", **bool_kw,
    )

    altre = parser.add_argument_group("altre opzioni")
    altre.add_argument("--file-log", default=LOG_FILE, help="nome del file di log")
    altre.add_argument(
        "--output", default="tabella_atti.html",
        help="file HTML in cui scrivere la tabella finale (data, titolo, link PDF, riassunto)",
    )
    altre.add_argument("--cartella", default="download_atti", help="cartella dei PDF scaricati")
    altre.add_argument("--headless", default=True, help="browser senza finestra", **bool_kw)
    altre.add_argument("--dal", type=_data_cli, help="filtro data: da (GG-MM-AAAA o 'oggi')")
    altre.add_argument("--al", type=_data_cli, help="filtro data: a (GG-MM-AAAA o 'oggi')")
    altre.add_argument(
        "--campo", choices=["data_inizio", "data_fine", "periodo"], default="data_inizio",
        help="campo su cui applicare il filtro per data",
    )
    altre.add_argument(
        "--riassumi", default=False,
        help="riassume ogni PDF scaricato (richiede --scarica true)", **bool_kw,
    )
    altre.add_argument(
        "--modello", default=MODELLO_LOCALE,
        help="modello Ollama usato per i riassunti con --riassumi true "
        "(nome come in `ollama list`, es. gemma3:12b)",
    )
    altre.add_argument(
        "--stato", default=STATO_FILE, metavar="FILE",
        help="file JSON che ricorda i documenti già scaricati e riassunti, per non rifarli "
        "(stringa vuota = non usare la memoria)",
    )
    altre.add_argument(
        "--ignora-stato", default=False,
        help="rifà tutto anche per i documenti già registrati (il file di stato viene "
        "comunque aggiornato)", **bool_kw,
    )
    altre.add_argument(
        "--ocr", default=True,
        help="legge con l'OCR i PDF scansionati prima di riassumerli (richiede Tesseract)",
        **bool_kw,
    )
    altre.add_argument(
        "--ocr-lingua", default=OCR_LINGUA, metavar="LINGUA",
        help="lingua/e di Tesseract per l'OCR, es. ita oppure ita+eng",
    )
    altre.add_argument(
        "--ollama-url", default=OLLAMA_URL, metavar="URL",
        help="indirizzo del server Ollama (default: variabile d'ambiente OLLAMA_URL, "
        "altrimenti locale)",
    )
    altre.add_argument(
        "--escludi", action="append", metavar="DESCRIZIONE",
        help="descrizione di un allegato da escludere, come appare nella modale "
        "(si può ripetere); si aggiunge a quelle già escluse: "
        + ", ".join(DESCRIZIONI_ESCLUSE),
    )

    return parser


def _leggi_argomenti(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _crea_parser()
    args = parser.parse_args(argv)
    if not args.debug:
        if args.riassumi and not args.scarica:
            parser.error("--riassumi true richiede --scarica true")
        if args.dal and args.al and args.dal > args.al:
            parser.error("--dal deve essere precedente o uguale a --al")
    return args


def main(argv: list[str] | None = None) -> None:
    args = _leggi_argomenti(argv)

    # Usage sempre visibile su console (indipendente da --log)
    print(_crea_parser().format_usage(), end="")
    print("Usa --help per l'elenco completo delle opzioni.\n")

    livello = getattr(logging, args.livello_log.upper())
    configura_logging(
        file_log=args.file_log,
        livello_file=livello,
        console=args.log in ("console", "entrambi"),
        livello_console=livello,
        su_file=args.log in ("file", "entrambi"),
    )
    logger.debug(f"Argomenti: {vars(args)}")

    if args.debug:
        debug_modale()
        return

    atti = stampa_link_pdf(
        headless=args.headless,
        scarica=args.scarica,
        cartella=args.cartella,
        dal=args.dal,
        al=args.al,
        campo=args.campo,
        riassumi=args.riassumi,
        modello=args.modello,
        ollama_url=args.ollama_url,
        ocr=args.ocr,
        ocr_lingua=args.ocr_lingua,
        stato_file=args.stato or None,
        ignora_stato=args.ignora_stato,
        escludi=DESCRIZIONI_ESCLUSE + tuple(args.escludi or ()),
    )

    percorso = scrivi_tabella(atti, args.output)
    logger.info(f"Tabella scritta in {percorso} ({len(atti)} atti)")
