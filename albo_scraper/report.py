"""Scrittura della tabella finale in un file HTML.
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc_html
from pathlib import Path

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


def righe_tabella(atti: list[dict]) -> list[tuple[str, str, str, str]]:
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
            righe.append((data, atto["testo_atto"], "", ""))
            continue

        for doc in documenti:
            titolo = atto["testo_atto"]
            if len(documenti) > 1 and doc.get("descrizione"):
                titolo += f" [{doc['descrizione']}]"
            righe.append((data, titolo, doc["url"], doc.get("riassunto", "")))
    return righe


def scrivi_tabella(atti: list[dict], percorso: str | Path) -> Path:
    """
    Scrive su file (UTF-8, sovrascrivendo) una pagina HTML autonoma con la tabella
    Data atto | Titolo atto | Link remoto al PDF | Riassunto.
    Tutti i testi sono "escapati"; i link sono cliccabili solo se http/https.
    """
    vuoto = '<span class="vuoto">—</span>'
    righe = righe_tabella(atti)

    corpo = []
    for data, titolo, url, riassunto in righe:
        titolo = titolo.title()
        if url.startswith(("http://", "https://")):
            u = esc_html(url, quote=True)
            cella_link = f'<a href="{u}" target="_blank" rel="noopener" title="{u}">Apri PDF</a>'
        else:
            cella_link = vuoto
        corpo.append(
            "      <tr>"
            f'<td class="data">{esc_html(data) or vuoto}</td>'
            f'<td class="titolo">{esc_html(" ".join(titolo.split()))}</td>'
            f'<td class="link">{cella_link}</td>'
            f'<td class="riassunto">{esc_html(riassunto.strip()) or vuoto}</td>'
            "</tr>"
        )

    n_documenti = sum(1 for r in righe if r[2])
    generato = datetime.now().strftime("%d-%m-%Y %H:%M")
    intestazione = "".join(f"<th>{esc_html(c)}</th>" for c in COLONNE_TABELLA)

    pagina = (
        '<!DOCTYPE html>\n<html lang="it">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Atti pubblicati</title>\n"
        f"<style>{CSS_TABELLA}</style>\n</head>\n<body>\n"
        "<h1>Atti pubblicati</h1>\n"
        f'<p class="meta">Generato il {generato} · {len(atti)} atti · {n_documenti} documenti</p>\n'
        '<div class="contenitore">\n  <table>\n'
        f"    <thead><tr>{intestazione}</tr></thead>\n    <tbody>\n"
        + "\n".join(corpo)
        + "\n    </tbody>\n  </table>\n</div>\n</body>\n</html>\n"
    )

    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(pagina, encoding="utf-8")
    logger.debug(f"Tabella HTML scritta in {percorso}: {len(righe)} righe")
    return percorso
