# Ernährungsplanung

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

**Ernährung wird geplant wie Training** (`ernaehrung_import.py`,
`ai_export.ERNAEHRUNG_PROMPT_TEMPLATE`, `routers/ernaehrung.py`). Die App plante
zehn Stunden Ausdauer die Woche und sagte kein Wort dazu, was daneben gehört —
obwohl alles dafür längst dalag: der Block Tag für Tag, das Ziel aus dem
Fragebogen, Gewicht, Körperfett und Trainingslast aus Garmin. Gebaut ist deshalb
**dasselbe Muster** wie bei Blockplanung und Einzelanpassung: ein KI-Lauf als
Job, mit der Zwischenablage als Rückfallebene. Nur die Aufgabe ist eine andere.

**Der Kontext ist derselbe, der Prompt nicht.** `erzeuge_ernaehrung_export()`
ruft `_lade_kontext()` und `build_payload()` unverändert und hängt einen Block
`payload["ernaehrung"]` daran — genau der Zuschnitt von
`erzeuge_einheit_export()`, und aus demselben Grund: Ein zweiter Lader liefe mit
dem ersten neuen Feld auseinander. Geteilt wird dagegen **kein einziger
Prompttext**. `FITNESSREGELN_MIT_DATEN` sagt der KI, wann sie die *Intensität*
zurücknimmt; für eine Ernährungsaufgabe ist das die falsche Anweisung — bei
gestörter Erholungslage steigt der Kohlenhydratbedarf, er sinkt nicht.
Übernommen ist nur die **Verzweigung** mit/ohne Gerätedaten
(`_ernaehrung_datenregeln()`), und die aus dem dokumentierten Grund: Regeln zu
Daten, die es nicht gibt, laden zum Erfinden ein.

**Die Historie kommt ohne ihre Einheiten** (`ERNAEHRUNG_HISTORIE_FELDER`,
`_ernaehrungshistorie()`). `trainingshistorie.einheiten` war an echten Daten die
**Hälfte des ganzen Payloads** — 28 absolvierte Einheiten mit Zonenzeiten,
Abschnitten, Trainingseffekt und Aufbautext. Das steht dort für Punkt 12 der
Trainingsplanung („fortschreiben statt neu erfinden"): Aus 5x1000 m soll
6x1000 m werden. **Hier wird nichts fortgeschrieben** — der Block steht fest und
ist Vorgabe. Für die Frage, wie viel Energie ein Athlet braucht, entscheidet der
Umfang, und den beschreibt `wochenuebersicht` genauer und kürzer als 28
Einzeleinträge. Nachweis, dass es totes Gewicht war: Der Ernährungsprompt nannte
**keinen einzigen** Schlüssel aus `trainingshistorie`. Gemessen am echten Konto
fiel der Prompt damit von 51.155 auf 27.944 Zeichen — 45 %.

Ebenfalls draußen: `aktueller_plan` (steht als ganzer Block schon unter
`ernaehrung.trainingsblock`), die Abstände je Sportart und die Umsetzungsquote —
sie entscheiden, *welche* Einheit als Nächstes drankommt, und das ist nicht diese
Aufgabe. Punkt 4 des Prompts nennt `wochenuebersicht`,
`letzte_volle_woche` und die ACWR seither **namentlich**: Ein Aggregat, das als
Einziges übrig bleibt und im Prompt keinen Leser hat, wäre nur die kleinere
Verschwendung.

**Positivliste, keine Ausschlussliste** — das ist die eigentliche Entscheidung.
Wer künftig einen Schlüssel an `_history_block()` ergänzt, tut das für die
Trainingsplanung; er landet dann nicht ungefragt auch hier. Ein Ausschluss hätte
den umgekehrten Verlauf: Jedes neue Feld wäre stillschweigend drin, und der
Payload wüchse zurück. `test_der_trainingsprompt_behaelt_seine_einheiten` hält
die Gegenrichtung fest — das Kürzen gilt **nur** für die Ernährung, sonst fiele
Punkt 12 aus.

**Der Fitnessblock bleibt dagegen vollständig**, obwohl `fitnessdaten.tage`
weitere 18 % trägt: Es ist die **einzige** Stelle mit dem Gewichtsverlauf —
`wellness_mittelwerte()` führt Schlaf, HRV, Ruhepuls, Stress, Trainingsreife und
Körperbatterie, aber kein Gewicht. Und der Gewichtstrend bei gleichbleibender
Last ist die Kennzahl der Energiebilanz schlechthin; genau darauf zeigt
`ERNAEHRUNGSDATEN_MIT`. Wer ihn je kürzen will, trägt das Gewicht vorher in die
Mittelwerte ein.

**Der Trainingsblock geht als Vorgabe hinein, nicht als Anregung.**
`_planumfeld()` ist dafür aus `_blockumfeld()` herausgezogen — dieselbe
Tagesliste, nur ohne die Markierung, die nur die Einzelanpassung braucht, und
mit `ab`/`bis` für das Ernährungsfenster. Eine zweite Funktion „derselbe Block,
diesmal ohne Markierung" wäre genau die Doppelung, gegen die `_lade_kontext()`
steht. Der Prompt sagt ausdrücklich, dass das Training feststeht und nicht Teil
der Aufgabe ist — sonst plant ein Sprachmodell es gleich mit.

**Der Zeitraum ist auf den Trainingsblock gedeckelt**
(`routers.ernaehrung.ernaehrungsrahmen`, `pruefe_zeitraum`). Weiter zu planen,
als der Block reicht, hieße für Tage zu decken, deren Belastung niemand kennt.
Die Obergrenze steht deshalb an **einer** Stelle und wird von dreien gelesen:
der Oberfläche (fürs Zahlenfeld), dem KI-Router und dem Handweg. Drei Rechnungen
liefen auseinander, und dann plante der Knopf einen anderen Zeitraum, als das
Feld daneben anzeigt.

**Der Freitext steht am Nutzer, nicht am Plan** (`ErnaehrungsProfil`). Eine
Laktoseintoleranz endet nicht, weil ein Block ausläuft — sie überlebt deshalb
ausdrücklich auch das *Löschen* des Ernährungsplans und geht in jeden folgenden
Prompt. Eigene Tabelle und keine Spalte an `AthleteProfile`: Das Profil trägt
gemessene Athletenwerte, die `profile_sync` aus Garmin fortschreibt, und liefe
durch dessen Teil-Update-Pfad, den das Profilformular bedient, ohne das Feld zu
kennen. Dieselbe Trennung wie bei `KiSettings`. Der Text geht als fertiger
**Wert** in die Vorlage (`_individualisierung()`) — geschweifte Klammern darin
sind damit folgenlos, als Vorlagenteil wären sie ein Absturz.

**Es gibt immer genau einen Ernährungsplan.** Ein neuer erbt die Tage seines
Vorgängers, die vor seinem eigenen Beginn liegen, und löscht ihn danach —
dieselbe Überlegung wie bei `uebernimm_vergangenheit`: Wer morgen neu plant,
verliert heute nicht. Damit braucht die Ansicht keine Liste früherer Pläne, und
ein `is_active` hätte nichts zu unterscheiden. Der Umzug läuft über die
**Beziehung** (`neu.tage.append(tag)`) und nicht über die Fremdschlüsselspalte:
An `alt.tage` hängt `cascade="all, delete-orphan"`, und die Sammlung im Speicher
weiß von einer direkt gesetzten Spalte nichts — das anschließende `db.delete()`
nähme die gerade geerbten Zeilen sonst wieder mit, folgenlos und unbemerkt.

**Die Formerkennung fragt nach `datum` oder `mahlzeiten`, nicht nach einer
Tagesliste** (`ernaehrung_import._ist_ernaehrungsform`). „Trägt eine Liste unter
`tage` oder `days`" klingt richtig und lässt einen **Trainingsblock** durch: Der
trägt dieselbe Liste. Der Athlet läse dann eine Feldliste statt der benannten
Verwechslung. Aus demselben Grund sieht `_falsche_antwort()` eine Ebene tiefer —
der Block steckt fast immer in einer `plan`-Hülle.

**`KiJob.ernaehrungsplan_id` ist eine eigene Spalte**, nicht `plan_id`. Die
Oberfläche springt nach einem geglückten Blocklauf auf `/plan/{plan_id}`; unter
derselben Kennung stünde dort die eines Ernährungsplans, also ein
Trainingsblock, den es nicht gibt. Und die Verzweigung in `ki/runner._lauf` ist
seither ein `elif`: Der `else`-Zweig ist der **Auffangfall der Blockplanung** —
eine neue Jobart, die dort hineinfiele, plante still einen Trainingsblock, den
niemand bestellt hat.

**Nachrechnen kann die App genau eine Zusage** (`_makros_passen_nicht`): ob
4 kcal je Gramm Kohlenhydrat und Eiweiß plus 9 je Gramm Fett zur genannten
Tagessumme passen, mit 15 % Toleranz für Ballaststoffe und Rundung. Dieselbe
Rolle wie `_dauer_weicht_ab` beim Bauplan — und wie überall beim Import wird
**gewarnt, nicht abgelehnt**: Die Antwort wird nirgends gespeichert, ein
abgelehnter Lauf ist ganz verloren und hat trotzdem Kontingent gekostet.
