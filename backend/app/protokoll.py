"""Wohin die Meldungen des Servers gehen.

**Ohne diese Datei war der Wurzel-Logger handlerlos.** Uvicorn richtet nur seine
eigenen ein (`uvicorn`, `uvicorn.error`, `uvicorn.access`) und lässt sie nicht
weiterreichen; alles andere fiel auf `logging.lastResort`, und der schluckt
jede Meldung unterhalb von WARNING. Damit war jedes `logger.info(...)` dieser
App unsichtbar — ausgerechnet in den Automatiken, denen ohnehin niemand zusieht:
`ki/tagesform.py` schreibt seit jeher „Tagesanpassung … gestartet", und die
Zeile hat nie ein Auge erreicht. Wer wissen wollte, warum die Tagesanpassung
nicht lief, hatte keine einzige Spur.

**Auf stderr und nicht in eine Datei.** Im Add-on sammelt Home Assistant den
Strom des Prozesses ein und zeigt ihn im Protokoll des Add-ons; eine Datei unter
`/data` müsste dagegen selbst gedreht und von Hand gelesen werden.

**Und `force=True`.** `basicConfig` tut sonst nichts, sobald der Wurzel-Logger
schon einen Handler hat — was beim Import in umgekehrter Reihenfolge oder unter
`--reload` vorkommt. Dann stünde hier eine Konfiguration, die nie gilt.
"""

import logging
import sys

from .config import LOG_LEVEL


def richte_ein() -> None:
    """Gibt dem Wurzel-Logger einen Handler. Mehrfach zu rufen ist harmlos."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    # SQLAlchemy meldet auf INFO jede einzelne Anweisung samt Parametern. Das
    # ist beim Fehlersuchen an einer Abfrage nützlich und sonst eine Wand, in
    # der die eine interessante Zeile untergeht — wer es braucht, holt es sich
    # gezielt mit `TRI_LOG_LEVEL=DEBUG` zurück.
    if LOG_LEVEL != "DEBUG":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
