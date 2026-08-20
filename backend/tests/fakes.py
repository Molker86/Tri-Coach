"""Nachbildung der Garmin-Bibliothek für die Tests.

Die Antworten behalten absichtlich die krummen Formen des Originals:

- `get_training_readiness` und `get_max_metrics_range` liefern Listen,
  obwohl die Typangaben der Bibliothek etwas anderes behaupten
- `get_training_status` gruppiert nach Geräte-Kennung, nicht nach Datum
- Gewichte kommen in Gramm, Geschwindigkeiten in m/s
- die Sportart steckt verschachtelt in `activityType.typeKey`

Eine glattgebügelte Nachbildung würde genau die Fehler verstecken, an denen das
Mapping in der Wirklichkeit bricht.
"""

from datetime import date, timedelta
from typing import Any


class FakeGarmin:
    """Bildet genau die Oberfläche nach, die die App benutzt."""

    def __init__(
        self,
        aktivitaeten: list[dict[str, Any]] | None = None,
        tage: list[date] | None = None,
        rate_limit_ab_tag: int | None = None,
    ) -> None:
        self.display_name = "test-athlet"
        self.username = "athlet@example.com"
        self.password = "geheim"
        self._aktivitaeten = aktivitaeten if aktivitaeten is not None else []
        # Bewertungen je Aktivitätskennung, wie sie im Detail stehen. Leer, weil
        # die meisten Einheiten unbewertet bleiben — der Normalfall.
        self.bewertungen: dict[str, dict[str, Any]] = {}
        # Was sonst noch im Aktivitätsdetail steht, je Aktivität: die
        # absolvierten Abschnitte (`splitSummaries`) und der Rückbezug aufs
        # Workout (`metadataDTO`). Die Form ist an einem echten Konto
        # abgelesen, nicht nach dem Parser geformt — siehe
        # `scripts/garmin_aktivitaetsdetail_probe.py`.
        self.details: dict[str, dict[str, Any]] = {}
        self._tage = tage or []
        self._rate_limit_ab_tag = rate_limit_ab_tag
        self._tagesabrufe = 0
        self.aufrufe: list[str] = []
        self.client = _FakeClient()
        self.mfa_noetig = False
        self._workouts: dict[int, dict[str, Any]] = {}
        self._termine: dict[int, tuple[int, str]] = {}
        self._workout_id = 5000
        self._schedule_id = 9000

    # -- Anmeldung ----------------------------------------------------------

    def login(self, tokenstore=None):
        """Gibt `("needs_mfa", None)` oder `(None, None)` zurück — wie das Original."""
        self.aufrufe.append("login")
        return ("needs_mfa", None) if self.mfa_noetig else (None, None)

    def resume_login(self, client_state, mfa_code):
        self.aufrufe.append("resume_login")
        if mfa_code != "123456":
            from garminconnect import GarminConnectAuthenticationError

            raise GarminConnectAuthenticationError("Falscher Code")
        self.mfa_noetig = False
        return (None, None)

    # -- Trainings ----------------------------------------------------------

    def get_activities_by_date(self, startdate, enddate=None, activitytype=None, sortorder=None):
        self.aufrufe.append("get_activities_by_date")
        von, bis = date.fromisoformat(startdate), date.fromisoformat(enddate)
        return [
            a
            for a in self._aktivitaeten
            if von <= date.fromisoformat(str(a["startTimeLocal"])[:10]) <= bis
        ]

    def get_activity(self, activity_id):
        """Das Detail — und nur hier stehen Anstrengung und Befinden.

        Die Trennung ist keine Vereinfachung der Nachbildung, sondern der
        eigentliche Grund für den zusätzlichen Abruf: An einem echten Konto
        führt die Listenantwort 111 Felder je Aktivität, `directWorkoutFeel`
        und `directWorkoutRpe` sind keines davon.
        """
        self.aufrufe.append("get_activity")
        antwort: dict[str, Any] = {
            "activityId": activity_id,
            "summaryDTO": dict(self.bewertungen.get(str(activity_id), {})),
        }
        # Der Rest des Details. `summaryDTO` wird zusammengeführt statt
        # ersetzt: Am echten Konto stehen Anstrengung, Einhaltungsbewertung und
        # die Messgrößen in **einem** Objekt.
        weiteres = self.details.get(str(activity_id))
        if weiteres:
            antwort["summaryDTO"].update(weiteres.get("summaryDTO", {}))
            antwort.update({k: v for k, v in weiteres.items() if k != "summaryDTO"})
        return antwort

    # -- Bereichsabfragen ---------------------------------------------------

    def get_rhr_daily(self, start, end):
        self.aufrufe.append("get_rhr_daily")
        # Die Bibliothek flacht diesen Endpunkt bereits selbst ab.
        return [
            {"calendarDate": tag.isoformat(), "value": 44.0 + (tag.toordinal() % 3)}
            for tag in self._im_bereich(start, end)
        ]

    def get_hrv_data_range(self, start, end):
        self.aufrufe.append("get_hrv_data_range")
        return {
            "hrvSummaries": [
                {
                    "calendarDate": tag.isoformat(),
                    "lastNightAvg": 58 + (tag.toordinal() % 5),
                    "weeklyAvg": 60,
                    "status": "BALANCED",
                    "baseline": {"balancedLow": 52, "balancedUpper": 71},
                }
                for tag in self._im_bereich(start, end)
            ]
        }

    def get_max_metrics_range(self, start, end):
        self.aufrufe.append("get_max_metrics_range")
        # Liste, nicht Dict — trotz gegenteiliger Typangabe der Bibliothek.
        return [
            {
                "generic": {
                    "calendarDate": tag.isoformat(),
                    "vo2MaxValue": 54.0,
                    "vo2MaxPreciseValue": 54.3,
                },
                "cycling": {"calendarDate": tag.isoformat(), "vo2MaxPreciseValue": 51.2},
            }
            for tag in self._im_bereich(start, end)
        ]

    def get_sleep_daily(self, start, end):
        self.aufrufe.append("get_sleep_daily")
        # Feldnamen am echten Konto abgelesen: Der Bereichsabruf benennt die
        # Phasen *anders* als die Tagesantwort von `get_sleep_data`
        # (`deepTime` statt `deepSleepSeconds`) und nennt die Gesamtdauer
        # `totalSleepTimeInSeconds`. Die hier zuvor stehenden Namen gab es
        # nirgends — der Parser las deshalb an allen Zeilen None.
        return [
            {
                "calendarDate": tag.isoformat(),
                "values": {
                    "totalSleepTimeInSeconds": 27000,
                    "deepTime": 4200,
                    "lightTime": 15600,
                    "remTime": 6000,
                    "awakeTime": 1200,
                    "sleepScore": 81,
                    "bodyBatteryChange": 45,
                },
            }
            for tag in self._im_bereich(start, end)
        ]

    def get_body_composition(self, startdate, enddate=None):
        self.aufrufe.append("get_body_composition")
        return {
            "dateWeightList": [
                # Gramm, nicht Kilogramm.
                {"calendarDate": tag.isoformat(), "weight": 78500.0, "bodyFat": 14.2}
                for tag in self._im_bereich(startdate, enddate)
            ]
        }

    def get_body_battery(self, startdate, enddate=None):
        self.aufrufe.append("get_body_battery")
        # Form am echten Konto abgelesen: zwei Spalten, und welche den
        # Ladestand trägt, sagt der Descriptor. Hier stand einmal eine
        # erfundene vierspaltige Zeile mit dem Wert an Index 2 — passend zum
        # damaligen Parser, aber zu nichts sonst. Beide zusammen ergaben einen
        # grünen Test über einer Spalte, die am echten Konto immer leer blieb.
        return [
            {
                "date": tag.isoformat(),
                "bodyBatteryValueDescriptorDTOList": [
                    {
                        "bodyBatteryValueDescriptorIndex": 0,
                        "bodyBatteryValueDescriptorKey": "timestamp",
                    },
                    {
                        "bodyBatteryValueDescriptorIndex": 1,
                        "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
                    },
                ],
                "bodyBatteryValuesArray": [
                    [1755036000000, 24],
                    [1755039600000, 92],
                    # Randtage kommen mit leerem Ladestand.
                    [1755043200000, None],
                ],
            }
            for tag in self._im_bereich(startdate, enddate)
        ]

    # -- Schwellenwerte -----------------------------------------------------
    #
    # Kein Zeitraum, kein Tag: Garmin gibt nur den zuletzt erkannten Stand
    # heraus. Die Formen sind die des Originals — die FTP kommt als Liste, die
    # Laktatschwelle als Bündel aus Tempo (m/s) und Herzfrequenz.

    def get_cycling_ftp(self):
        self.aufrufe.append("get_cycling_ftp")
        return [
            {
                "userProfilePK": 4711,
                "calendarDate": date.today().isoformat(),
                "sport": "CYCLING",
                "functionalThresholdPower": 248,
            }
        ]

    def get_lactate_threshold(self, latest=True, **_kwargs):
        self.aufrufe.append("get_lactate_threshold")
        return {
            "speed_and_heart_rate": {
                "calendarDate": date.today().isoformat(),
                # 3,7 m/s sind 4:30 min/km.
                "speed": 3.7037,
                "heartRate": 168,
                "heartRateCycling": None,
            },
            "power": {},
        }

    def get_personal_record(self):
        """Bestzeiten in der Form des Originals: nur `typeId` und `value`.

        Mit dabei, was der Mapper aussortieren muss — ein Schrittrekord ohne
        Aktivität und ein Eintrag, dessen Wert keine Zeit sein kann.
        """
        self.aufrufe.append("get_personal_record")
        return [
            {
                "id": 1,
                "typeId": 3,  # 5 km
                "activityId": 900001,
                "activityStartDateTimeLocal": "2026-05-02T08:14:00.0",
                "value": 1214.0,  # 20:14
            },
            {
                "id": 2,
                "typeId": 4,  # 10 km
                "activityId": 900002,
                "activityStartDateTimeLocal": "2026-06-14T07:02:00.0",
                "value": 2550.0,  # 42:30
            },
            {
                "id": 3,
                "typeId": 12,  # meiste Schritte an einem Tag — keine Bestzeit
                "activityId": None,
                "value": 28412.0,
            },
            {
                "id": 4,
                "typeId": 1,  # 1 km, aber der Wert wäre ein Tempo von 0:16/km
                "activityId": 900003,
                "value": 16.0,
            },
        ]

    # -- Tagesabfragen ------------------------------------------------------

    def _tagesabruf(self) -> None:
        self._tagesabrufe += 1
        if (
            self._rate_limit_ab_tag is not None
            and self._tagesabrufe > self._rate_limit_ab_tag * 4
        ):
            from garminconnect import GarminConnectTooManyRequestsError

            raise GarminConnectTooManyRequestsError("429 Too Many Requests")

    def get_training_readiness(self, cdate):
        self.aufrufe.append("get_training_readiness")
        self._tagesabruf()
        # Liste von Momentaufnahmen; die nach dem Aufwachen ist die gültige.
        return [
            {
                "calendarDate": cdate,
                "score": 45,
                "level": "MODERATE",
                "feedbackShort": "MODERATE",
                "inputContext": "SLEEP_UPDATE",
            },
            {
                "calendarDate": cdate,
                "score": 78,
                "level": "HIGH",
                "feedbackShort": "READY",
                "recoveryTime": 12,
                "hrvFactorPercent": 85,
                "acwrFactorPercent": 88,
                "acuteLoad": 745,
                "inputContext": "AFTER_WAKEUP_RESET",
            },
        ]

    def get_training_status(self, cdate):
        self.aufrufe.append("get_training_status")
        self._tagesabruf()
        # Nach Geräte-Kennung gruppiert: Laufuhr und Radcomputer nebeneinander.
        return {
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "3403410297": {
                        "calendarDate": cdate,
                        "timestamp": 1755062063000,
                        "trainingStatus": 3,
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE_1",
                        "weeklyTrainingLoad": 812,
                        "acuteTrainingLoadDTO": {
                            "acwrStatus": "OPTIMAL",
                            "dailyAcuteChronicWorkloadRatio": 0.92,
                            "dailyTrainingLoadAcute": 745,
                            "dailyTrainingLoadChronic": 810,
                        },
                    },
                    "9999999999": {
                        # Älterer Eintrag eines zweiten Geräts — darf nicht gewinnen.
                        "calendarDate": (
                            date.fromisoformat(cdate) - timedelta(days=3)
                        ).isoformat(),
                        "timestamp": 1754000000000,
                        "trainingStatus": 6,
                        "trainingStatusFeedbackPhrase": "OVERREACHING_1",
                        "weeklyTrainingLoad": 200,
                        "acuteTrainingLoadDTO": {
                            "acwrStatus": "HIGH",
                            "dailyAcuteChronicWorkloadRatio": 1.8,
                        },
                    },
                }
            }
        }

    def get_all_day_stress(self, cdate):
        self.aufrufe.append("get_all_day_stress")
        self._tagesabruf()
        return {"calendarDate": cdate, "avgStressLevel": 28, "maxStressLevel": 91}

    def get_sleep_data(self, cdate):
        self.aufrufe.append("get_sleep_data")
        self._tagesabruf()
        return {
            "dailySleepDTO": {
                "calendarDate": cdate,
                "sleepTimeSeconds": 27000,
                "deepSleepSeconds": 4200,
                "lightSleepSeconds": 15600,
                "remSleepSeconds": 6000,
                "awakeSleepSeconds": 1200,
                "avgSleepStress": 18.0,
                "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
            },
            "avgOvernightHrv": 62.0,
            "hrvStatus": "BALANCED",
            "restingHeartRate": 44,
            "bodyBatteryChange": 41,
        }

    # -- Workouts und Kalender ----------------------------------------------
    #
    # Garmin führt Vorlage und Termin getrennt: Ein Workout liegt in der
    # Bibliothek, ein Zeitplaneintrag verweist darauf. Die Nachbildung hält
    # beides ebenso getrennt — sonst fiele nicht auf, wenn die App eine Vorlage
    # löscht und den Termin stehen lässt.

    def upload_workout(self, workout_json):
        self.aufrufe.append("upload_workout")
        self._workout_id += 1
        self._workouts[self._workout_id] = dict(workout_json)
        return {"workoutId": self._workout_id}

    def get_workout_by_id(self, workout_id):
        self.aufrufe.append("get_workout_by_id")
        vorlage = self._workouts.get(int(workout_id))
        if vorlage is None:
            raise RuntimeError("404 Not Found")
        return dict(vorlage, workoutId=int(workout_id))

    def get_workouts(self, start=0, limit=100):
        self.aufrufe.append("get_workouts")
        eintraege = [
            dict(vorlage, workoutId=workout_id)
            for workout_id, vorlage in sorted(self._workouts.items())
        ]
        return eintraege[int(start) : int(start) + int(limit)]

    def update_workout(self, workout_id, workout_json):
        self.aufrufe.append("update_workout")
        if int(workout_id) not in self._workouts:
            raise RuntimeError("404 Not Found")
        self._workouts[int(workout_id)] = dict(workout_json)
        return {"workoutId": int(workout_id)}

    def delete_workout(self, workout_id):
        self.aufrufe.append("delete_workout")
        if self._workouts.pop(int(workout_id), None) is None:
            raise RuntimeError("404 Not Found")
        return {}

    def schedule_workout(self, workout_id, date_str):
        self.aufrufe.append("schedule_workout")
        if int(workout_id) not in self._workouts:
            raise RuntimeError("404 Not Found")
        self._schedule_id += 1
        self._termine[self._schedule_id] = (int(workout_id), date_str)
        return {"workoutScheduleId": self._schedule_id}

    def unschedule_workout(self, scheduled_workout_id):
        self.aufrufe.append("unschedule_workout")
        if self._termine.pop(int(scheduled_workout_id), None) is None:
            raise RuntimeError("404 Not Found")
        return {}

    def get_scheduled_workouts(self, year, month):
        self.aufrufe.append("get_scheduled_workouts")
        eintraege = []
        for termin_id, (workout_id, tag) in self._termine.items():
            wann = date.fromisoformat(tag)
            if (wann.year, wann.month) != (int(year), int(month)):
                continue
            workout = self._workouts.get(workout_id, {})
            eintraege.append({
                "id": termin_id,
                "itemType": "workout",
                "date": tag,
                "title": workout.get("workoutName", "Training"),
                "workoutId": workout_id,
                "sportTypeKey": workout.get("sportType", {}).get("sportTypeKey"),
                "estimatedDurationInSecs": workout.get("estimatedDurationInSecs"),
            })
        for aktivitaet in self._aktivitaeten:
            wann = date.fromisoformat(str(aktivitaet["startTimeLocal"])[:10])
            if (wann.year, wann.month) != (int(year), int(month)):
                continue
            eintraege.append({
                "id": aktivitaet["activityId"],
                "itemType": "activity",
                "date": wann.isoformat(),
                "title": aktivitaet["activityName"],
                "activityId": aktivitaet["activityId"],
                "activityType": {"typeKey": aktivitaet["activityType"]["typeKey"]},
                # Millisekunden und Zentimeter — der Kalenderdienst zählt hier
                # anders als `get_activities` (Sekunden und Meter). Genau das
                # hat die Nachbildung früher eingeebnet und den Fehler verdeckt.
                "duration": aktivitaet["duration"] * 1000,
                "distance": aktivitaet["distance"] * 100,
            })
        # Umhülltes Dict, nicht die blanke Liste — so kommt es wirklich an.
        return {"calendarItems": eintraege, "year": year, "month": month}

    # -- Hilfsmittel --------------------------------------------------------

    def _im_bereich(self, start, end) -> list[date]:
        von = date.fromisoformat(start)
        bis = date.fromisoformat(end) if end else von
        return [tag for tag in self._tage if von <= tag <= bis]


class _FakeClient:
    def dumps(self) -> str:
        return '{"di_token": "test-zugang", "di_refresh_token": "test-erneuerung"}'


def baue_aktivitaet(
    kennung: int,
    tag: date,
    typkey: str = "running",
    dauer_s: float = 3600.0,
    distanz_m: float = 12000.0,
    **extra: Any,
) -> dict[str, Any]:
    aktivitaet = {
        "activityId": kennung,
        "activityName": "Testeinheit",
        "activityType": {"typeKey": typkey},
        "startTimeLocal": f"{tag.isoformat()} 07:14:23",
        "startTimeGMT": f"{tag.isoformat()} 05:14:23",
        "duration": dauer_s,
        "distance": distanz_m,
        "elevationGain": 142.0,
        "averageSpeed": distanz_m / dauer_s if dauer_s else 0,
        "averageHR": 148.0,
        "maxHR": 172.0,
        "calories": 812.0,
        "aerobicTrainingEffect": 3.4,
        "anaerobicTrainingEffect": 0.6,
        "activityTrainingLoad": 142.5,
        "hrTimeInZone_1": 210.0,
        "hrTimeInZone_2": 1420.0,
        "hrTimeInZone_3": 1502.0,
        "hrTimeInZone_4": 289.0,
        "hrTimeInZone_5": 0.0,
    }
    aktivitaet.update(extra)
    return aktivitaet
