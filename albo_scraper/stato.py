"""Memoria degli atti già scaricati e riassunti, salvata in un file JSON."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .log import logger

VERSIONE_STATO = 1


def adesso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class StatoAtti:
    """
    Registro dei documenti già elaborati, indicizzati con `id_documento` (vedi pdf.py).
    Per ogni documento si ricorda: titolo, descrizione, data, file scaricato, riassunto,
    modello usato e quando. Il file viene riscritto dopo ogni aggiornamento (in modo
    atomico), così un'esecuzione interrotta non perde il lavoro già fatto.

    - percorso=None: stato disattivato (non legge e non scrive nulla).
    - ignora=True: non usa quanto registrato in precedenza (tutto viene rifatto), ma
      continua ad aggiornare il file con i nuovi risultati.
    """

    def __init__(self, percorso: str | Path | None, ignora: bool = False):
        self.percorso = Path(percorso) if percorso else None
        self.ignora = ignora
        self._documenti: dict[str, dict] = {}
        self._carica()

    def _carica(self) -> None:
        if not self.percorso or not self.percorso.exists():
            return
        try:
            dati = json.loads(self.percorso.read_text(encoding="utf-8"))
            documenti = dati["documenti"]
            if not isinstance(documenti, dict):
                raise ValueError("formato non valido")
        except (OSError, ValueError, KeyError, TypeError) as e:  # JSONDecodeError è un ValueError
            copia = self.percorso.with_name(self.percorso.name + ".corrotto")
            logger.error(
                f"File di stato illeggibile ({e}): lo conservo come {copia.name} e riparto da zero"
            )
            try:
                self.percorso.replace(copia)
            except OSError:
                pass
            return

        self._documenti = documenti
        logger.info(f"Stato: {len(documenti)} documenti già registrati in {self.percorso}")

    def get(self, id_doc: str) -> dict | None:
        """Quanto registrato per il documento, oppure None."""
        if self.ignora or not self.percorso:
            return None
        return self._documenti.get(id_doc)

    def aggiorna(self, id_doc: str, **campi: str) -> None:
        """Aggiunge/aggiorna i campi del documento e salva subito il file."""
        if not self.percorso:
            return
        self._documenti.setdefault(id_doc, {}).update(campi)
        self._salva()

    def _salva(self) -> None:
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        temporaneo = self.percorso.with_name(self.percorso.name + ".tmp")
        contenuto = {"versione": VERSIONE_STATO, "documenti": self._documenti}
        temporaneo.write_text(
            json.dumps(contenuto, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporaneo.replace(self.percorso)  # scrittura atomica
        logger.debug(f"Stato salvato in {self.percorso} ({len(self._documenti)} documenti)")
