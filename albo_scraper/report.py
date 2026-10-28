"""Tabella finale degli atti: costruzione e scrittura del file HTML."""

from __future__ import annotations

from datetime import datetime
from html import escape as esc_html
from pathlib import Path
from typing import NamedTuple

from .config import COLONNE_TABELLA
from .log import logger

CSS_TABELLA = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1f2328; --muted: #6b7280; --bordo: #d8dee4;
  --testata: #f3f4f6; --hover: #f8fafc; --link: #0b5cad;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171a; --fg: #e6e8eb; --muted: #9aa4af; --bordo: #2d333b;
    --testata: #1d2228; --hover: #1a1f24; --link: #6cb2ff;
  }
}
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg); margin: 0; padding: 1.5rem; line-height: 1.45;
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.meta { color: var(--muted); margin: 0 0 1rem; font-size: .9rem; }
.contenitore { overflow-x: auto; border: 1px solid var(--bordo); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; min-width: 760px; }
th, td { padding: .6rem .8rem; text-align: left; vertical-align: top;
         border-bottom: 1px solid var(--bordo); }
thead th { background: var(--testata); font-size: .85rem; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--hover); }
td.data, td.link { white-space: nowrap; }
td.riassunto { white-space: pre-line; min-width: 22rem; }
a { color: var(--link); }
.vuoto { color: var(--muted); }
"""

VUOTO = '<span class="vuoto">—</span>'  # segnaposto per le celle senza contenuto


class Riga(NamedTuple):
    """Una riga della tabella: un documento PDF di un atto."""

    data: str
    titolo: str
    url: str
    riassunto: str


def titolo_leggibile(testo: str) -> str:
    """
    Titolo con le iniziali maiuscole e gli spazi normalizzati: i titoli degli atti arrivano
    tutti in maiuscolo. Nota: `str.title()` porta in "Title Case" anche le sigle (CIG -> Cig).
    """
    return " ".join(testo.title().split())


def righe_tabella(atti: list[dict]) -> list[Riga]:
    """
    Una riga per ogni PDF collegato a un atto (un atto senza allegati ha una sola
    riga con link e riassunto vuoti). 'Data atto' è la data di inizio pubblicazione.
    Se un atto ha più documenti, la descrizione del documento è aggiunta al titolo.
    """
    righe = []
    for atto in atti:
        data = atto["data_inizio"].strftime("%d-%m-%Y") if atto.get("data_inizio") else ""
        documenti = atto.get("link_pdf") or []

        if not documenti:
            righe.append(Riga(data, titolo_leggibile(atto["testo_atto"]), "", ""))
            continue

        for doc in documenti:
            titolo = atto["testo_atto"]
            if len(documenti) > 1 and doc.get("descrizione"):
                titolo += f" [{doc['descrizione']}]"
            righe.append(
                Riga(data, titolo_leggibile(titolo), doc["url"], doc.get("riassunto", ""))
            )
    return righe


def _cella_testo(testo: str) -> str:
    """Testo "escapato", oppure il segnaposto se è vuoto."""
    return esc_html(testo.strip()) or VUOTO


def _cella_link(url: str) -> str:
    """Link "Apri PDF", cliccabile solo per indirizzi http/https."""
    if not url.startswith(("http://", "https://")):
        return VUOTO
    u = esc_html(url, quote=True)
    return f'<a href="{u}" target="_blank" rel="noopener" title="{u}">Apri PDF</a>'


def _riga_html(riga: Riga) -> str:
    return (
        "      <tr>"
        f'<td class="data">{_cella_testo(riga.data)}</td>'
        f'<td class="titolo">{esc_html(riga.titolo)}</td>'
        f'<td class="link">{_cella_link(riga.url)}</td>'
        f'<td class="riassunto">{_cella_testo(riga.riassunto)}</td>'
        "</tr>"
    )


def tabella_html(righe: list[Riga]) -> str:
    """La tabella (dentro il suo contenitore scorrevole), pronta da inserire in una pagina."""
    intestazione = "".join(f"<th>{esc_html(c)}</th>" for c in COLONNE_TABELLA)
    corpo = "\n".join(_riga_html(r) for r in righe)
    return (
        '<div class="contenitore">\n  <table>\n'
        f"    <thead><tr>{intestazione}</tr></thead>\n    <tbody>\n"
        f"{corpo}\n    </tbody>\n  </table>\n</div>"
    )


def pagina_html(titolo: str, corpo: str, css: str = CSS_TABELLA) -> str:
    """Pagina HTML autonoma con `corpo` dentro <body>."""
    return (
        '<!DOCTYPE html>\n<html lang="it">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc_html(titolo)}</title>\n"
        f"<style>{css}</style>\n</head>\n<body>\n"
        f"{corpo}\n</body>\n</html>\n"
    )


def scrivi_tabella(atti: list[dict], percorso: str | Path) -> Path:
    """
    Scrive su file (UTF-8, sovrascrivendo) una pagina HTML autonoma con la tabella
    Data atto | Titolo atto | Link remoto al PDF | Riassunto.
    Tutti i testi sono "escapati"; i link sono cliccabili solo se http/https.
    """
    righe = righe_tabella(atti)
    n_documenti = sum(1 for r in righe if r.url)
    generato = datetime.now().strftime("%d-%m-%Y %H:%M")

    corpo = (
        "<h1>Atti pubblicati</h1>\n"
        f'<p class="meta">Generato il {generato} · {len(atti)} atti · {n_documenti} documenti</p>\n'
        + tabella_html(righe)
    )

    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(pagina_html("Atti pubblicati", corpo), encoding="utf-8")
    logger.debug(f"Tabella HTML scritta in {percorso}: {len(righe)} righe")
    return percorso
