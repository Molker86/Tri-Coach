"""Anbindung an Claude Code — die KI plant den nächsten Block auf Knopfdruck.

Aufgebaut wie `garmin/`: Die Berührung mit dem fremden Programm liegt in
`client.py`, die Fehlerübersetzung in `errors.py`, der Lauf mit Fortschritt in
`runner.py`.

Was hier bewusst **fehlt**, ist eine Automatik: Ein Block entsteht nur, wenn
jemand ihn anstößt — über den Knopf oder über die Zwischenablage.
"""
