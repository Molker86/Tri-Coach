# Bekannte Grenzen und mögliche nächste Schritte

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

- **Ohne Garmin gibt es keine Trainingshistorie.** Die App kann eine Einheit
  weder erfassen noch nachtragen; wer keine Uhr verbindet, bekommt Blöcke
  allein aus Fragebogen und Profil. Ebenso fehlt jede Möglichkeit, eine
  importierte Einheit zu korrigieren — was Garmin falsch liefert, wird in
  Connect berichtigt und beim nächsten Abgleich nachgezogen, oder der Eintrag
  wird im Verlauf gelöscht. Die **einzige** Ausnahme ist die Zuordnung zur
  Planeinheit: Sie lässt sich im Einheiten-Dialog lösen
  (`DELETE /api/plans/sessions/{id}/verknuepfung`), und das ändert nichts an
  der Einheit, sondern nur an der Behauptung, sie habe eine Vorgabe erfüllt.
- **Ohne gestartetes Workout entsteht die Zuordnung nicht von selbst.**
  Zugeordnet wird ausschließlich über die Workout-Kennung der Uhr
  (`garmin/matching.py`); eine frei aufgezeichnete Runde zählt nie von allein
  als geplante Einheit, auch wenn Tag und Sportart stimmen. Wer die Übertragung
  auf die Uhr abschaltet (`GarminAccount.auto_push_enabled`), bekommt deshalb
  ohne Zutun dauerhaft `rate_pct: 0` — bewusst so, denn die Gegenrichtung
  färbte jede Feierabendrunde zur Schlüsseleinheit. Nachholen lässt es sich
  seither im Einheiten-Dialog: „Von Hand zuordnen" bietet die nicht
  zugeordneten Trainings aus drei Tagen um den Plantag an
  (`POST /api/plans/sessions/{id}/verknuepfung`). Das bleibt **Handarbeit je
  Einheit** — es gibt keine Sammelzuordnung, keinen Vorschlag und keine
  Prüfung, ob das gewählte Training zur Vorgabe passt.
- **Zugeordnet wird nur innerhalb von 42 Tagen.** Die Workout-Kennung steht im
  Aktivitätsdetail, und das wird nur für diese Spanne geholt
  (`sync.BEWERTUNGSFENSTER_TAGE`). Bei einem Erstimport über ein Jahr bleibt
  alles ältere ohne Vorgabe — für die Quote folgenlos, die ohnehin nur den
  laufenden Block betrachtet.
- Die **subjektiven Werte** (Muskelkater, Schlafqualität, Morgenpuls,
  Morgen-HRV, Bedingungen, Schlaf je Einheit) haben damit keine Quelle mehr und
  sind ersatzlos aus Modell, Schema, Export und Datenbank entfernt. Wer eines
  dieser Felder je zurückholen will, braucht wieder ein Formular — die Spalte ist
  weg, die Historie damit auch. Anstrengung und **Befinden** sind die Ausnahme:
  Sie sind zurück, aber über Garmin Connect statt über ein Formular, und deshalb
  nur an den Einheiten, die der Athlet dort bewertet.
- Die **Bewertung kostet eine Anfrage je Einheit** und reicht nur 42 Tage zurück
  (`sync.BEWERTUNGSFENSTER_TAGE`). Wer eine ältere Einheit nachträglich in
  Connect bewertet, bekommt das hier nie zu sehen — auch ein Rückblick holt das
  Detail für diese Tage nicht. Wer eine Bewertung dort *löscht*, behält sie hier:
  Der Abgleich fasst einen einmal gesetzten Wert nicht wieder an.
- Was ein Athlet **vor** dieser Umstellung von Hand eingetragen hat, bleibt
  liegen und zählt weiter mit. `/api/garmin/dubletten` zeigt, was dabei doppelt
  ist; entfernt wird es über den Verlauf, einzeln und von Hand.
- `training_status.weeklyTrainingLoad` ist an **allen** 370 Tagen leer, und das
  ist kein Lesefehler: Am echten Konto steht der Schlüssel im JSON und trägt
  `null` (ebenso `loadTunnelMin`/`loadTunnelMax`). Garmin füllt ihn schlicht
  nicht. Was die Wochenlast tatsächlich beschreibt, steht daneben in
  `acuteTrainingLoadDTO.dailyTrainingLoadAcute` — die App speichert es längst
  als `garmin_load_acute`. Die Spalte `weekly_training_load` bleibt als
  Altlast stehen; wer sie füllen will, holt sie von dort.
- **Die Beschwerde ist Freitext, und die Ursache dahinter rät die KI.** Punkt 13
  verlangt, aus „Läuferknie rechts" die wahrscheinliche Ursache abzuleiten und
  die Übungen dagegen zu planen — das ist eine Vermutung aus einem Satz, keine
  Untersuchung. Die App kann daran nichts prüfen: Sie weiß nicht, ob die
  gewählten Übungen zur Beschwerde passen, ob die Beschwerde noch besteht oder ob
  sie überhaupt behandelbar ist. Der Freitext ist außerdem der einzige Ort, an
  dem sie steht — er veraltet nur, wenn der Athlet ihn selbst ändert, und ein
  vergessener Eintrag lenkt das Ergänzungstraining monatelang weiter. Was
  hilft, ist der Nachweis im Begründungsfeld: Dort steht seit dieser Änderung,
  welche Beschwerde der Block angeht, und daran ist eine überholte Angabe zu
  erkennen.
- **Auch die *Form* der Behandlung ist eine Zusage, keine Prüfung.** Seit der
  Dehneinheit an drei Tagen hintereinander sagt der Prompt, dass die abgeleitete
  Ursache über mobilisieren oder belasten entscheidet und dieselbe Region an zwei
  Tagen sich unterscheiden muss. Nachrechnen kann die App weder das eine noch das
  andere: Sie weiß nicht, welche Übung welche Region trifft, und `kategorie` aus
  `absolvierte_uebungen` steht nur für Einheiten, die aus einem Workout mit
  Übungskennung liefen. Der einzige Nachweis ist wieder das Begründungsfeld —
  dort steht seither auch, *warum in dieser Form*.
- **Die Disziplin ist eine Zusage der KI, keine Prüfung.** Der Prompt sagt einem
  Laufblock, dass er nur Laufeinheiten enthält; nachrechnen kann die App das
  nicht, sie meldet beim Import nur, was danebensteht. Und die Disziplin hängt
  am Fragebogen: Ein Plan von vor dieser Änderung oder einer ohne Fragebogen
  (`request_id = NULL`) fällt auf die Triathlonfassung zurück und bekommt
  weiterhin alle drei Sportarten angeboten. Wer eine Einzeldisziplin will,
  passt den Fragebogen an — der nächste Block greift.
- **Ein gelöschter aktiver Plan nimmt die ganze Kette mit.** Seit ein Block die
  Vergangenheit seiner Vorgänger übernimmt, hängt an ihm nicht mehr nur seine
  eigene Woche. `SessionLog` überlebt (die Verknüpfung wird auf `NULL` gesetzt),
  aber `geplant_war` ist für jeden absorbierten Tag weg — derselbe Verlust wie
  am 16.08.2026, nur ausdrücklich vom Nutzer ausgelöst. Der Bestätigungsdialog
  nennt bislang nur die Zahl der Einheiten.
- **Der aktive Block wächst auf vier Wochen Erbe und bleibt dort stehen** —
  an 365 simulierten Tagen: 35 Einheiten ab Tag 28, `GET /api/plans/active`
  konstant 15,3 kB, ein Plan. Der Garmin-Kalender wächst nie
  (`planbare_einheiten()` filtert auf `plan.beginn`, konstant sieben;
  `entferne_link()` löscht die Zuordnung mit dem Termin), der Export an die KI
  ebenso wenig (byte-identisch zum alten Verhalten). **In der Datenbank
  schrumpft es deutlich**: nach einem Jahr 35 `plan_sessions`-Zeilen statt der
  2555, die 365 stehengebliebene Blöcke ergäben.
- **Ein `SessionLog` jenseits der vier Wochen verliert seinen Verweis auf den
  geplanten Aufbau** (`plan_session_id = NULL`). Das Training selbst bleibt
  vollständig; nur `geplant_war` wäre für so alte Einheiten nicht mehr
  aufzulösen — der Export zeigt sie ohnehin nicht. Wer den Rückblick je
  vertieft, bekommt für die neu sichtbaren Tage keinen Aufbau nachgeliefert:
  Er ist zu dem Zeitpunkt schon weg.
- **Eine heute schon absolvierte Einheit steht bis morgen doppelt** — einmal
  als erledigte (umgehängt), einmal als neu geplante. Ihr Garmin-Termin bleibt
  den Tag über stehen: `raeume_vergangene_auf` greift erst ab
  `scheduled_date < heute`, und für `ersetzte_links` gehört sie nach dem Umzug
  zum aktiven Block.
- **Ein alter Mehrwochenplan wird beim Ersetzen aufgelöst.** Wer noch einen
  Vier-Wochen-Block aus der Frühzeit aktiv hat und „Neu planen ab heute"
  drückt, findet ihn danach nicht mehr unter „Frühere Pläne": Seine Einheiten
  leben im neuen Block weiter, sein `title`, `summary`, `coaching_notes` und
  `raw_json` nicht. Eine Obergrenze für die Übernahme hilft nicht — der Rest
  jenseits davon trüge wieder ein Training und bliebe wieder stehen.
- **Ein Wechsel der Disziplin ändert den laufenden Block nicht.** Er zeigt auf
  den Fragebogen, aus dem er entstanden ist (dieselbe Lage wie bei der
  Ausrüstung). Wer aus einem Triathlonblock heraus auf „Laufen" umstellt, plant
  neu — die bestehenden Schwimm- und Radeinheiten bleiben stehen, samt ihrer
  Workouts auf der Uhr.
- **Die Einzelanpassung ändert nur den Inhalt, nie den Tag.** Verschieben geht
  über den Garmin-Kalender der App (dort zieht die Planeinheit mit um), und
  mehrere Einheiten auf einmal gibt es nicht — dafür ist „Neu planen ab heute"
  da. `Plan.raw_json` bleibt dabei bewusst die ursprüngliche KI-Antwort: Was
  gilt, steht in den Einheiten; die Anpassung dorthin zu schreiben machte aus
  dem Original ein Gemisch aus zwei Antworten.
- Ein **Sportartwechsel an einer bereits übertragenen Einheit** („mach lieber
  Schwimmen draus") schickt über `update_workout` ein neues `sportType` an eine
  bestehende Kennung — genau der Weg, der laut „Vorlage und Termin sind zwei
  Dinge" gegen ein echtes Konto ungeprüft ist. Bisher trat er nur beim
  Wiederverwenden eines freien Pool-Slots auf; mit der Einzelanpassung ist er
  ein Alltagsfall. Lehnt Garmin ihn ab, bleibt die Anpassung in der App stehen
  und der Hinweis nennt den Grund — der Termin trägt dann noch die alte
  Sportart.
- Eine angepasste Einheit **kostet ein eigenes Kontingent** aus dem Abo — ein
  Lauf mit Opus bei `max`, wie beim ganzen Block. Wer an einem Tag mehrere
  Einheiten einzeln anpasst, zahlt das mehrfach; die Aufgabe ist kleiner, der
  Prompt aber fast gleich groß, weil derselbe Kontext mitgeht.
- Wird aus einer Einheit **Ruhe** und Garmin nimmt den Termin nicht zurück,
  taucht sie im Trainingsplan nicht mehr auf (Ruhetage lässt
  `planbare_einheiten` aus). Der verwaiste Termin steht dann nur noch im
  Garmin-Kalender der App und ist dort von Hand zu entfernen; der Hinweis am
  Lauf sagt das.
- **Die Schrittliste ist gegen einen echten Lauf bestätigt** (Opus,
  `--effort max`, 288 s, 0,64 USD): Alle zehn Einheiten des Blocks kamen mit
  `steps`, ohne eine einzige Warnung, und `swim_location` traf beide Fälle —
  `pool` fürs Becken, `open_water` für die Freiwasserrunde. Die Koppeleinheit
  benannte ihre Disziplin je Abschnitt und wurde deshalb nicht geschätzt.
  `--json-schema` bleibt trotzdem in der Hinterhand: Fällt `steps` einmal aus,
  sagt es der Hinweis „Ohne Schrittliste geliefert" beim Übernehmen, und die
  Einheiten gehen über den Zerleger auf die Uhr wie zuvor.
- **Ein Lauf kann sofort und folgenlos scheitern.** Beim ersten Versuch kam
  nach zwei Sekunden `is_error` mit `stop_reason: "stop_sequence"` und null
  Eingabetoken zurück — der unmittelbar folgende Versuch mit demselben Prompt
  lief durch. Das ist keine Kontingent- und keine Anmeldefrage, sondern eine
  vorübergehende Störung der Gegenseite; sie landet über `_ordne_fehler_ein`
  als allgemeiner Fehler mit Originaltext. Eine Wiederholung baut die App
  bewusst nicht ein — was zweimal hintereinander losläuft, kostet auch zweimal
  Kontingent.
- **`steps` steht nicht in `PlanSessionOut`.** Der Athlet sieht in der App
  `structure`; ob die Schrittliste dasselbe sagt, zeigt sich erst auf der Uhr.
  Wer das prüfen will, braucht das Feld in der Ausgabe und eine Darstellung
  dafür — beides gibt es nicht.
- **Ohne aktiven Trainingsblock gibt es keinen Ernährungsplan.** Der Plan
  richtet sich nach dem geplanten Training; ohne eines fehlt der Bezug, an dem
  Kohlenhydratmenge und Timing hängen. Die Seite zeigt dann einen Verweis auf
  die Trainingsplanung statt der Knöpfe.
- **Am Ernährungsplan kann die App inhaltlich fast nichts nachprüfen.** Ob die
  Tagessumme zum Umfang passt, ob die Lebensmittel die genannten Nährwerte
  haben, ob ein Supplement für diesen Athleten trägt — all das ist eine Zusage
  der KI. Nachgerechnet wird genau eine Sache: ob Kalorien und Makronährstoffe
  zueinander passen (`MAKRO_TOLERANZ_PCT`), und auch die nur als Warnung.
- **Ein Ernährungslauf kostet ein eigenes Kontingent** aus demselben Abo — ein
  Opus-Lauf bei `max`, wie ein ganzer Trainingsblock. Und er belegt dasselbe
  Schloss: Solange er läuft, lässt sich kein Block planen und keine Einheit
  anpassen.
- **Ein Ernährungsplan lässt sich nicht teilweise ändern.** Es gibt kein
  Gegenstück zur Einzelanpassung — wer einen Tag anders haben will, plant neu.
  Und es gibt immer nur einen: Ein abgelöster Plan gibt seine früheren Tage ab
  und verschwindet, eine Liste „Frühere Ernährungspläne" existiert nicht.
- **Die Uhrzeit einer Einheit kennt die App nicht.** `PlanSession` hat kein Feld
  dafür. Alles, was am Training hängt, steht deshalb als *Bezug* im Plan („90 min
  vor der Einheit") statt als Uhrzeit — der Prompt verlangt das ausdrücklich,
  weil eine erfundene Uhrzeit schlechter wäre als der Bezug.
- **Der Ernährungsplan geht nirgendwohin.** Kein Garmin, kein Kalender, kein
  Export — er steht in der App, und beim Einkaufen liest man ihn dort.
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic. Neue Spalten werden im Migrationshelfer in `database.py`
  eingetragen und beim Start ergänzt, entfallene über `_ENTFALLENE_SPALTEN`
  beim Start gelöscht; für Umbenennungen oder Typänderungen bleibt es beim
  Löschen der Datei. Die Tabelle `garmin_workout_links` legt
  `create_all()` beim Start an; die zwei Zählwerke an `garmin_sync_jobs`,
  `athlete_profiles.garmin_personal_bests`, `session_logs.garmin_feel`, die fünf
  Ausführungsspalten an `session_logs` (`hr_zone_seconds`, `garmin_abschnitte`,
  `garmin_uebungen`, `garmin_compliance`, `garmin_workout_id`) sowie
  `garmin_accounts.synced_through` und `garmin_accounts.auto_push_enabled`
  kommen über den Helfer — ebenso `garmin_accounts.sync_hour`,
  `ki_settings.token_encrypted` und `ai_jobs.ernaehrungsplan_id`. Die fünf
  Ernährungstabellen brauchen dort **nichts**: `create_all()` legt neue
  Tabellen vollständig an, der Helfer ist nur für neue *Spalten* an
  bestehenden.
- **Die fünf Ausführungsspalten bleiben an bestehenden Einheiten leer.** Die
  Zonenzeiten stehen zwar in der Listenantwort, drei weitere im
  Aktivitätsdetail und die Übungen hinter einer eigenen Anfrage — nichts davon
  wird für zurückliegende Tage noch einmal geholt
  (`AKTUALISIERUNGSFENSTER_TAGE` = 5). Wer sie für die Historie will,
  stößt einen **Rückblick** an; für Einheiten außerhalb von
  `BEWERTUNGSFENSTER_TAGE` = 42 kommen Abschnitte, Einhaltung,
  Workout-Kennung und Übungen auch dann nicht nach, weil dort kein Detail
  geholt wird.
- **Die Übungsliste kostet eine eigene Anfrage je Kraft- und
  Mobility-Einheit** (`get_activity_exercise_sets`), anders als die drei
  Nachbarn aus dem Detail. Bei einem Rückblick über ein Jahr betrifft das nur
  die Einheiten der letzten 42 Tage, im Alltag also eine Handvoll — spürbar
  wird es erst, wer sehr viel Kraft trainiert.
- **Was die Uhr nicht erkennt, steht nicht da.** Garmin meldet `UNKNOWN`, und
  das fällt heraus statt als Übung zu erscheinen. Betroffen ist alles, was
  nicht aus einem Workout mit Übungskennung gestartet wurde — eine frei
  begonnene Krafteinheit erkennt die Uhr nur zum Teil, und genau die Übungen,
  die `garmin/uebungen.py` nicht zuordnen kann (Faszienrolle, „World's Greatest
  Stretch" …), kommen deshalb auch hier nicht zurück. Dieselbe Lücke, zweimal.
- **`saetze` und `wiederholungen` sind nicht, was der Athlet gemacht hat.**
  `saetze` zählt die *aufgezeichneten* Sätze — drei Sätze in einem
  Workout-Schritt bis zur Rundentaste stehen als einer —, und `wiederholungen`
  kommt aus der Bewegungserkennung am Handgelenk und zählt bei
  Körpergewichtsübungen zu niedrig (an einer echten Einheit: 3 Wiederholungen
  über 232 s). Der Prompt sagt das der KI; nachrechnen kann die App es nicht.
  Verlässlich sind Übungsauswahl und Dauer.
- Ein **Zusatzgewicht** wird nicht gelesen: `weight` stand an jedem geprüften
  Satz auf `null`, damit ist die Einheit (Gramm oder Kilogramm) nicht belegt.
- **Der Weg über `associatedWorkoutId` funktioniert nur, solange die Planeinheit
  lebt.** Ihren Workout-Vermerk trägt sie selbst
  (`PlanSession.garmin_workout_id`), und ein gelöschter Block nimmt ihn mit —
  danach ist die Zuordnung für seine Tage nicht mehr herzustellen. Für Einheiten
  aus der Zeit davor bleibt das Feld leer; sie behalten die Zuordnung, die sie
  unter der alten Regel bekommen haben.
- **`geplant_fuer` sagt nur, dass der Tag abwich, nicht warum.** Ob der Athlet
  die Einheit vorgezogen oder eine andere ausgelassen hat, steht nirgends. Die
  Umsetzungsquote wertet die verschobene Einheit aber richtig als umgesetzt —
  die Zuordnung kennt keinen Tagesbezug mehr.
- Was Garmin **später als fünf Tage** nachträgt (nachgeladene Aktivität aus
  einem zweiten Gerät, korrigierter Schlaf), holt kein Abgleich mehr von
  allein — dafür gibt es den Rückblick. Ebenso kann ein Lauf, der mitten im
  Zeitraum scheitert, nicht teilweise als geholt gelten: `synced_through` rückt
  nur im Erfolgsfall vor, der nächste Lauf wiederholt den ganzen Zeitraum.
- Der Rückblick über ein Jahr wurde bisher nur gegen die Nachbildung geprüft,
  nicht gegen ein echtes Konto.
- Auch die Antwortform von `get_lactate_threshold()` ist nicht dokumentiert.
  Der Mapper liest sie über mehrere Pfade und verwirft, was außerhalb der
  Profilspanne liegt; **beim ersten echten Abgleich prüfen**, ob der
  Schwellenpuls tatsächlich ankommt — bleibt er leer, steht der Grund als
  Hinweis in der Meldung des Laufs.
- Die Kennziffern in `get_personal_record()` sind ebenfalls nirgends
  dokumentiert; die Zuordnung in `BESTZEIT_STRECKEN` ist aus Garmin Connect
  abgelesen und über die Tempo-Spanne abgesichert, nicht bestätigt. **Beim
  ersten echten Abgleich prüfen**, ob die Strecken zu den Zeiten passen. Rad-
  und Schwimmbestzeiten fehlen deshalb ganz — sie bleiben Freitext.
- **FTP, Schwellenpace Laufen und CSS bleiben Handarbeit** — die App holt sie
  nicht mehr, auch wenn Garmin die ersten beiden führt. Wer sie nie einträgt,
  bekommt keine Watt- und keine Tempozonen: `power_zones()` und `pace_zones()`
  geben ohne Schwellenwert eine leere Liste zurück, und die Uhr steuert dann
  über den Puls. Und was ein früherer Abgleich einmal geschrieben hat, steht
  weiter im Profil, bis der Athlet es selbst ändert — zurückgesetzt wird
  nichts. Die CSS führt Garmin ohnehin nirgends; aus den Trainingsdaten ließe
  sie sich nur schätzen, denn die Dauer eines importierten Trainings steht auf
  ganze Minuten gerundet in `SessionLog`, was für einen 200-m-Testabschnitt
  schon 10 % Fehler bedeutet.
- Die Anmeldung schützt nichts: Jeder, der die App erreicht, kann jedes Konto
  wählen (bewusst — siehe „Anmeldung"). Der Schutz kommt vom Ingress davor.
- Kein Löschen von Konten in der Oberfläche; ein Konto bleibt für immer in der
  Auswahlliste.
- Ein zweites Garmin-Konto im selben Haushalt teilt sich die Anfragegrenze über
  die gemeinsame Herkunftsadresse; das globale Schloss im Runner bremst das ab,
  löst es aber nicht.
- Die Übertragung wurde bisher nur gegen die Nachbildung geprüft, nicht gegen
  ein echtes Konto. Der Aufbau der Workout-JSON folgt den Modellen der
  Bibliothek; sollte Garmin eine Einheit ablehnen, steht die Meldung an der
  Einheit und die anderen gehen trotzdem durch.
- Die **automatische Übertragung wartet nicht ab, sondern stellt sich an.** Wer
  mehrere Blöcke hintereinander übernimmt, während ein Jahresrückblick läuft,
  hat ebenso viele Fäden am globalen Schloss stehen. Bei einer Handvoll
  Einheiten je Block ist das folgenlos; eine Warteschlange mit Zusammenfassen
  gleicher Aufträge gibt es aber nicht.
- Die **Bahnlänge für Schwimm-Workouts** liegt fest bei 25 m
  (`workouts.POOL_LAENGE_M`) — die App fragt sie nirgends ab. Im 50-m-Becken
  stimmen die Strecken, nur die Bahnzahl auf der Uhr nicht.
- **Eine Freiwassereinheit geht ohne Bahnlänge nach Garmin, sonst unverändert.**
  Dass Garmin sie so annimmt, ist am echten Konto geprüft; dass sie sich auf
  der Uhr im *Freiwassermodus* starten lässt, ist es nicht — Garmin führt für
  Workouts keinen Freiwasser-Untertyp, das Workout bleibt formal ein
  Schwimm-Workout. Der Hinweis dazu steht in seiner Beschreibung, den Modus
  wählt der Athlet selbst.
- Der **Wattkorridor aus der Zone** ist eine Umrechnung über feste
  FTP-Anteile und damit die gröbste der drei Leistungsquellen: Er trifft das
  Ein- und Ausrollen, ersetzt aber keine Wattangabe der KI. Wer im Profil
  **keine FTP** stehen hat, bekommt auf dem Rad weiterhin Pulsziele — dann
  regelt der Smarttrainer in diesen Schritten nicht. Die FTP kommt ausschließlich
  von Hand aus der Profilseite.
- **Ob die Radeinheit drinnen oder draußen stattfindet, kann die App nicht
  nachprüfen** — sie glaubt `bike_location` bzw. dem Titel. Plant die KI eine
  Einheit als `indoor`, die der Athlet dann doch auf der Straße fährt, steht
  dort ein Wattziel ohne Messwert; umgekehrt fährt er auf der Rolle ohne
  Regelung. Korrigieren lässt sich das nur über die Einzelanpassung („mach das
  auf der Rolle"), nicht mit einem Schalter an der Einheit.
- Die **Ausrüstung stammt aus dem Fragebogen des Plans**. Wer sich ein
  Powermeter kauft, passt den Fragebogen an, statt einen neuen auszufüllen —
  dann bleibt die Zeile dieselbe und der laufende Block zeigt weiter auf sie.
  Von selbst greift es trotzdem nicht: Der Fingerabdruck der Einheiten ändert
  sich nicht, die Radeinheiten gelten also als aktuell. Erst der nächste Block
  baut die Workouts neu. Wer stattdessen „Neues Training" ausfüllt, legt eine
  neue Zeile an, und der laufende Block bleibt an der alten hängen.
- **Pläne von vor dieser Änderung tragen `request_id = NULL`** und gelten
  deshalb als „Ausrüstung unbekannt" — sie bekommen auf dem Rad weiterhin
  Wattziele. Wer das für einen laufenden Block korrigieren will, trägt die
  `request_id` von Hand nach; danach meldet der Abgleich die Radeinheiten als
  „geändert" und lädt sie neu hoch. Der Trainingsplan bietet bei `NULL` trotzdem
  „Fragebogen anpassen" an und meint damit den zuletzt gespeicherten — das
  bearbeitet die richtige Zeile, verknüpft den Plan aber nicht mit ihr.
- **Die Satzpause kommt von der KI oder gar nicht.** Der Prompt verlangt sie
  jetzt als eigenen `rest`-Eintrag in der Serie; liefert die KI keine, bleibt
  die Serie die Übung allein, und der Athlet drückt zwischen den Durchgängen
  weiter selbst weiter. Geraten wird nach wie vor nichts — ein erfundener Wert
  stünde als Vorgabe auf der Uhr. Der **Zerlegerweg** hat gar keine: Aus
  „3x40 s je Seite“ lässt sich keine Pause ablesen, Blöcke von vor dieser
  Änderung und Antworten über die Zwischenablage bleiben deshalb ohne. Ebenso
  bleibt ein **Zusatzgewicht** ungelesen: `weightValue` steht fest auf „ohne“
  (-1), auch wenn „mit 8 kg Kurzhantel“ in der Zeile steht.
- **Der Prompt verlangt den Bauplan, erzwingen kann ihn niemand.** `steps` ist
  Pflicht laut Punkt 10, aber die Antwort geht durch keinen Schemazwang
  (`--json-schema` liegt weiter „in der Hinterhand“). Fehlt die Liste, greift
  der Zerleger und der Hinweis sagt es — die Einheit geht dann ohne
  Satzpausen und mit verdoppelten Durchgängen auf die Uhr, so wie vorher.
- **Der Umfang wird nur in drei Schreibweisen erkannt** (`_uebungsumfang`):
  „3x40 s“, „3x15“ und die einzelne Angabe mit Einheit. Wer „45 s halten,
  3 Durchgänge“ schreibt, bekommt einen Durchgang; „Wiederholen bis zur
  Erschöpfung“ bleibt die Rundentaste. Das ist Absicht — die Zahl der
  Durchgänge zu raten, hieße die Einheit zu verändern.
- Die **Zuordnung zum Übungskatalog** deckt ab, was in Kraft- und
  Mobilityplänen für Ausdauersportler üblich ist, nicht den ganzen Katalog.
  Gemessen ist sie an den erzeugten Blöcken: Von den 48 Übungen der acht
  Kraft- und Mobility-Einheiten in der Datenbank werden 42 zugeordnet. Die
  sechs übrigen führt Garmin nicht (dreimal Faszienrolle, „World's Greatest
  Stretch“, „Plank Shoulder Tap“, Zwerchfellatmung), und sie bleiben deshalb
  leer. Am ersten Block mit `exercise_en` waren es 18 von 22 — offen blieben
  zwei Faszienrollen und „Band Shoulder Pass-Through“; „Hip Flexor Stretch“
  und „Supine Spinal Twist“ sind dabei als Synonyme nachgetragen worden. Das
  eigene Feld erleichtert das Nachtragen erheblich: Der Name steht für sich
  statt in einer Zeile voller Beiwerk, eine Lücke ist damit sofort sichtbar. Was
  `uebungen.finde()` nicht erkennt, bleibt ohne Animation — **und ohne Titel**:
  Die Überschrift des Schritts kommt in Connect wie auf der Uhr allein aus
  `category`/`exerciseName`, ein Feld für einen eigenen Namen gibt es im
  Schritt-DTO nicht (an einem zurückgelesenen Workout nachgezählt). Ein
  namenloser Schritt steht dort als „--“ über seiner Beschreibung — die deshalb
  in diesem Fall den deutschen Namen behält (siehe „Oben deutsch, unten
  englisch“). Wer eine
  Lücke bemerkt, trägt sie in `SYNONYME` nach; `test_garmin_uebungen.py` prüft,
  dass jede Entsprechung im Katalog existiert.
- Ein paar Bewegungen führt der Katalog **nur mit Gerät**, obwohl der Plan sie
  ohne meint: Für „Single-Leg Romanian Deadlift“ gibt es keinen Eintrag ohne
  Hantel oder Schlingen, weshalb dort das zweibeinige „Romanian Deadlift“
  animiert wird — dieselbe Hüftbeuge, nur auf zwei Beinen. „Bulgarian Split
  Squat“ und „Nordic Hamstring Curl“ bleiben aus demselben Grund ganz ohne
  Animation.
- **Yogaposen laufen als `POSE`, nicht als Yoga.** Einen eigenen
  *Yoga*-Posenkatalog gibt es weiterhin nicht öffentlich
  (`web-data/exercises/Yoga.json` ist ein 404) — die 43 Posen aus
  `Mobility.json` (`POSE`) decken den Bedarf aber ab, und Mobility-Einheiten
  laufen wie bisher als Garmins „Mobility“ (11). **Ob `POSE` und `MOVE` am
  echten Konto angenommen werden, ist offen**: Bisher hat diese App nur
  `WARM_UP`-Kennungen übertragen, und eine abgelehnte Kategorie kostet das
  ganze Workout. Fällt es durch, genügt es, beide Kategorien in
  `katalog.eintraege()` auszulassen.
- Die Sportart `mobility` (11), die Übungskennungen und die Serienform sind am
  echten Konto bestätigt: Ein temporäres Workout aus Einheit 24 kam mit
  Wiederholungsgruppe, Timer (`time`), Wiederholungszählung (`reps`) und
  Übungskennung unverändert zurück. **Offen bleibt, ob die Animation auf dem
  Gerät erscheint** — das zeigt sich erst auf der Uhr.
- Eine **Koppeleinheit** ohne erkennbare Teilung im Aufbautext wird 2:1 auf Rad
  und Lauf geschätzt; die Beschreibung des Workouts weist das aus.
- Workouts landen über den Kalender auf der Uhr — beim nächsten Synchronisieren
  des Geräts. Ein Direktversand an ein bestimmtes Gerät
  (`push_workout_to_device`) ist nicht eingebaut; er kostete zusätzliche
  Anfragen für die Gerätesuche.
- **Die Slotkennung steht im Namen, nicht am Termin.** Im Garmin-Kalender liest
  sich eine Einheit deshalb als „TC01-Schwellentraining Rad" statt bloß als
  „Schwellentraining Rad" — vier Zeichen Beiwerk in einer Ansicht, die sie
  nicht braucht. Sie loszuwerden hieße, dem Kalendereintrag einen eigenen Namen
  zu geben, und den gibt Garmin nicht her (siehe „Der Termin kann keinen
  eigenen Namen tragen"). Der Trainingsplan der App zeigt unverändert nur den
  Trainingsnamen.
- Das Aufräumen vergangener Einheiten lässt sich nicht abschalten und hängt an
  einem Abgleich oder einer Übertragung; wer beides nie auslöst, behält seine
  alten Vorlagen.
- Ein überbügelter Block, dessen Einheiten schon in Garmin liegen, bleibt so
  lange in der Planliste stehen, bis das Aufräumen dort **durchgekommen** ist —
  vorher darf er nicht gelöscht werden, sonst käme niemand mehr an seine
  Workouts heran. Im Normalfall ist das derselbe Handgriff (der Aufräumlauf
  hängt am Übernehmen); scheitert er an einer Anfragesperre, bleibt der Block
  bis zum nächsten Lauf sichtbar.
- Das **Löschen eines Plans wartet auf Garmin** und läuft dabei im
  Anfrage-Thread, nicht als Job: Bei einem Block mit vielen übertragenen
  Einheiten dauert die Antwort entsprechend (je Einheit zwei Anfragen und eine
  Sekunde Pause). Es hält auch **nicht das globale Schloss** des Runners —
  derselbe Zuschnitt wie beim Löschen einer einzelnen Einheit, aber mit mehr
  Anfragen dahinter.
- Wer beim Löschen `garmin_uebergehen` setzt (die Rückfrage „Trotzdem
  löschen?"), behält verwaiste Workouts in Garmin: Mit dem Plan stirbt die
  Zuordnung, und ohne sie fasst die App dort nichts mehr an. Der Kalender in
  der App zeigt sie weiterhin zum Entfernen an — das ist dann der einzige Weg.
- Das **Leeren des Kalenders wirkt nur auf den angezeigten Monat**. Wer Termine
  über mehrere Monate liegen hat, blättert weiter und drückt erneut. Ohne
  Fortschrittsanzeige: Bei einer Handvoll Terminen dauert die Antwort ein paar
  Sekunden (eine Anfrage und eine Sekunde Pause je Termin).
- Der Bestandsabgleich prüft nur die Monate, in denen die App ihre Einheiten
  vermutet. Wer ein Workout in **Connect** auf einen anderen Monat schiebt, wird
  dort nicht gefunden; die Vorlage besteht aber noch, also wird die Zuordnung
  nicht gelöscht, sondern nur ihr Termin vergessen — die nächste Übertragung
  legt einen zweiten Termin auf dem Plantag an, ohne den verschobenen zu
  kennen. Innerhalb der App verschieben (Kalenderansicht) hat das Problem
  nicht: Dort zieht die Planeinheit mit um.
- Für den Netzbetrieb fehlen HTTPS, eine echte Authentifizierung vor der App,
  gesetzter `TRI_SECRET_KEY` und angepasste CORS-Herkünfte (`config.py`).
- Das **Claude-Token aus der Add-on-Option liegt weiterhin im Klartext** in
  `/data/options.json` und wandert damit in jedes Home-Assistant-Backup. Wer das
  nicht will, lässt die Option leer und trägt den Zugang stattdessen unter
  Einstellungen → KI-Planung ein — dort liegt er verschlüsselt (`crypto.py`).
  Gedeckt ist damit dieselbe Lage wie beim Garmin-Token: die Kopie der Datenbank
  ohne den Schlüssel. **Nicht** gedeckt ist Zugriff auf die Maschine selbst.
  Und ein Wechsel von `TRI_SECRET_KEY` macht ihn unlesbar; das meldet
  `token_status`, heilbar ist es nur durch erneutes Eintragen.
- **Das Kontingent teilt sich mit der eigenen Claude-Nutzung.** Ein Lauf mit
  Opus bei `max` verbraucht spürbar vom Fünf-Stunden-Fenster des Abos; ein Lauf
  am Tag ist unkritisch, wer daneben viel mit Claude arbeitet, kann trotzdem ins
  Limit laufen. Dann scheitert der Lauf mit deutscher Meldung, und der Block
  fehlt an dem Tag.
- **Der Zugang läuft irgendwann ab.** Die App kann das nur melden, nicht
  erneuern — die Meldung nennt deshalb ausdrücklich `claude setup-token`.
- **Ohne den Schalter bleibt ein ausgelaufener Block ausgelaufen.** Ab Werk ist
  die automatische Planung aus; bis jemand plant, steht auf der Uhr nichts Neues,
  und im Kalender bleibt der letzte übertragene Block liegen, bis ein Abgleich
  seine vergangenen Tage abräumt. Das Dashboard weist auf den Zustand hin
  (`blockStatus()`), mehr nicht.
- **Mit dem Schalter wird der laufende Block täglich überbügelt.** Das ist
  gewollt — der Export trägt `ersetzt_laufenden_block`, `raeume_abgeloeste_plaene`
  räumt hinterher auf, und die abgelösten Blöcke verschwinden dabei samt ihrer
  Vergangenheit im nachfolgenden. Wer ihn setzt und drei Tage nicht hinsieht,
  hat trotzdem dreimal geplant — sichtbar ist davon nur der letzte Block. Und es
  kostet **jeden Tag** einen Opus-Lauf aus demselben Kontingent, das man daneben
  selbst benutzt. Der Prompt weiß davon (`NEUPLANUNGSHINWEIS`) und plant den
  ersten Tag entsprechend — aber nur, solange der Schalter steht: Wer ihn abends
  ausschaltet, hat morgen früh einen Block, dessen späte Tage plötzlich zählen,
  und der Hinweis von heute stand umsonst darin. Umgekehrt genauso.
- **Die automatische Planung hängt am Abgleich.** Ohne verbundenes Garmin-Konto
  gibt es keinen, und damit auch keinen Auslöser — dann bleibt es beim Knopf.
  Ebenso, wenn `TRI_GARMIN_AUTOSYNC=0` steht oder der Abgleich scheitert: Ein
  Block auf dem Datenstand von gestern wäre schlechter als keiner.
- Die Zuordnung von Fehlertexten der CLI zu eigenen Fehlern (`_ordne_fehler_ein`)
  geht über **Textbausteine**, weil es für Anmelde- und Kontingentfehler kein
  maschinenlesbares Feld gibt — `api_error_status` bleibt leer, wenn die Anfrage
  gar nicht erst hinausging. Ein unbekannter Fall landet als allgemeiner Fehler
  **mit Originaltext** in der Meldung, statt still eingeordnet zu werden.
- **Das Add-on-Abbild ist mit Claude Code ungeprüft**: Der native Installer
  bedient laut Manifest `linux-arm64` und `linux-x64`, gebaut wurde er hier
  aber nicht (kein Docker in der Entwicklungsumgebung). Das `claude --version`
  am Ende der Docker-Stufe lässt den Build scheitern, statt ein Abbild ohne die
  Funktion auszuliefern.
- Der Planungslauf hängt an einem Abbild, das die CLI **zur Bauzeit aus dem Netz
  holt** (`curl … | bash`). Ein Build ohne Netz schlägt fehl, und zwei Builds zu
  verschiedenen Zeiten können verschiedene Versionen enthalten — dasselbe gilt
  aber schon für `npm ci` im Frontend.
