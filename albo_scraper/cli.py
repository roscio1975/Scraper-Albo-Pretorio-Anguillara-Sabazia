"""Interfaccia da riga di comando.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path

from .config import (
    DESCRIZIONI_ESCLUSE,
    LOG_FILE,
    MODELLO_LOCALE,
    OCR_LINGUA,
    OLLAMA_URL,
    STATO_FILE,
)
from .debug import debug_modale
from .diario import crea_diario_html
from .log import configura_logging, logger
from .mail import invia_report
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


def _intero_positivo(valore: str) -> int:
    """Converte in intero maggiore di zero, per gli argomenti da riga di comando."""
    try:
        numero = int(valore)
    except ValueError:
        raise argparse.ArgumentTypeError(f"numero non valido: {valore!r}") from None
    if numero < 1:
        raise argparse.ArgumentTypeError("deve essere almeno 1")
    return numero


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
  python scraper_albo.py                                  link + download dei PDF (prima pagina)
  python scraper_albo.py --scarica false                  solo link, niente download
  python scraper_albo.py --max-atti 25                    i 25 atti più recenti (scorre le pagine)
  python scraper_albo.py --max-pagine 3                   solo le prime 3 pagine della tabella
  python scraper_albo.py --dal 01-10-2026 --al oggi       solo gli atti in quell'intervallo
  python scraper_albo.py --riassumi true --modello gemma3:12b
                                                          riassunti con un modello Ollama a scelta
  python scraper_albo.py --escludi "VISTO CONTABILE PER IMPEGNI"
                                                          esclude anche questo tipo di allegato
  python scraper_albo.py --invia-mail false               non invia la tabella per mail
  python scraper_albo.py --output risultati.html          nome del file HTML con la tabella finale
  python scraper_albo.py --diario --output risultati.html diario discorsivo dal file già prodotto
  python scraper_albo.py --livello-log debug --log file   log dettagliato solo su file
  python scraper_albo.py --debug true                     salva HTML/screenshot di tabella e modale
  python scraper_albo.py --url https://cloud.urbi.it/...  albo di un altro ente
"""


def _crea_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scraper dell'albo pretorio: legge gli atti, ricava i link dei PDF,\n"
            "li scarica e (opzionale) li riassume con un LLM locale (Ollama)."
        ),
        formatter_class=_HelpFormatter,
        epilog=EPILOGO_HELP,
        add_help=False,  # -h/--help è definito sotto, in italiano
    )
    bool_kw = dict(type=_bool, nargs="?", const=True, metavar="true|false")

    princ = parser.add_argument_group("opzioni principali")
    princ.add_argument("-h", "--help", action="help", help="mostra questo messaggio ed esce")
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
        help="modalità debug: salva HTML e screenshot della tabella (con la paginazione) e "
        "della modale della prima riga, poi esce senza scaricare nulla "
        "(browser visibile se c'è uno schermo)", **bool_kw,
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
    altre.add_argument(
        "--url", metavar="URL",
        help="indirizzo della pagina dell'albo (default: quello di Anguillara Sabazia, "
        "impostato in config.py)",
    )
    altre.add_argument("--dal", type=_data_cli, help="filtro data: da (GG-MM-AAAA o 'oggi')")
    altre.add_argument("--al", type=_data_cli, help="filtro data: a (GG-MM-AAAA o 'oggi')")
    altre.add_argument(
        "--max-atti", type=_intero_positivo, metavar="N",
        help="elabora al massimo N atti, partendo dal più recente per data dell'atto e "
        "passando alle pagine successive se serve (dopo l'eventuale filtro --dal/--al; "
        "gli atti già elaborati contano nel limite)",
    )
    altre.add_argument(
        "--max-pagine", type=_intero_positivo, metavar="N",
        help="legge al massimo N pagine della tabella. Senza --max-atti, --dal/--al né "
        "--max-pagine si legge solo la prima pagina",
    )
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
        "--invia-mail", default=True,
        help="invia una mail con la tabella finale in allegato (destinatari in receipts.txt, "
        "password SMTP nella variabile d'ambiente SMTP_PASSWORD)", **bool_kw,
    )
    altre.add_argument(
        "--escludi", action="append", metavar="DESCRIZIONE",
        help="descrizione di un allegato da escludere, come appare nella modale "
        "(si può ripetere); si aggiunge a quelle già escluse: "
        + ", ".join(DESCRIZIONI_ESCLUSE),
    )

    altre.add_argument(
        "--diario", default=False,
        help="non fa scraping: crea un diario in linguaggio semplice (testo di Ollama + tabella) "
        "a partire dal file --output già prodotto e lo salva come diario_atti.html nella "
        "stessa cartella. Usa --modello e --ollama-url; non invia la mail", **bool_kw,
    )

    return parser


def _leggi_argomenti(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _crea_parser()
    args = parser.parse_args(argv)
    if not (args.debug or args.diario):
        if args.riassumi and not args.scarica:
            parser.error("--riassumi true richiede --scarica true")
        if args.dal and args.al and args.dal > args.al:
            parser.error("--dal deve essere precedente o uguale a --al")
    return args


def _modalita_diario(args: argparse.Namespace) -> None:
    """--diario: crea il diario HTML dal file --output, senza fare scraping."""
    logger.info(f"Generazione del diario HTML (input: {args.output})")
    try:
        percorso = crea_diario_html(
            Path(args.output), modello=args.modello, ollama_url=args.ollama_url
        )
    except Exception:
        logger.error("Errore nella generazione del diario HTML", exc_info=True)
        percorso = None
    if percorso is None:
        raise SystemExit(1)  # il motivo è nel log; il codice di uscita serve a script e cron


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

    if args.diario:
        _modalita_diario(args)
        return
    if args.debug:
        debug_modale(url=args.url)
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
        max_atti=args.max_atti,
        max_pagine=args.max_pagine,
        escludi=DESCRIZIONI_ESCLUSE + tuple(args.escludi or ()),
        url=args.url,
    )

    percorso = scrivi_tabella(atti, args.output)
    logger.info(f"Tabella scritta in {percorso} ({len(atti)} atti)")
    if args.invia_mail:
        invia_report(Path(percorso))
