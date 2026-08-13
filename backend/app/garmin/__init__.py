"""Anbindung an Garmin Connect.

Aufteilung:

- `errors`   — eigene Fehler mit deutschen Meldungen
- `client`   — die einzige Stelle, an der die Bibliothek betreten wird
- `mapping`  — Garmin-JSON in die Begriffe dieser App (rein funktional)
- `matching` — importierte Einheit an eine offene Planeinheit knüpfen
- `sync`     — Abruf und Speicherung eines Zeitraums
- `runner`   — führt einen Lauf im Hintergrund aus und schreibt den Fortschritt
"""
