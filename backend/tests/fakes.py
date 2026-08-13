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
        self._tage = tage or []
        self._rate_limit_ab_tag = rate_limit_ab_tag
        self._tagesabrufe = 0
        self.aufrufe: list[str] = []
        self.client = _FakeClient()
        self.mfa_noetig = False

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
        # Zeilen aus `individualStats` — andere Verschachtelung als die
        # Tagesantwort von `get_sleep_data`.
        return [
            {
                "calendarDate": tag.isoformat(),
                "values": {
                    "totalSleepSeconds": 27000,
                    "deepSleepSeconds": 4200,
                    "lightSleepSeconds": 15600,
                    "remSleepSeconds": 6000,
                    "awakeSleepSeconds": 1200,
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
        return [
            {
                "date": tag.isoformat(),
                "bodyBatteryValuesArray": [
                    [1755036000000, "MEASURED", 24, 1.0],
                    [1755039600000, "MEASURED", 92, 1.0],
                ],
            }
            for tag in self._im_bereich(startdate, enddate)
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
