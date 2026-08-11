from fastapi import APIRouter

from ..deps import CurrentUser, DbSession
from ..models import AthleteProfile, ProfileHistory
from ..schemas import ProfileHistoryOut, ProfileIn, ProfileOut
from ..sportscience import calc_age, calc_bmi, hr_zones

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Werte, deren Verlauf für die Trainingssteuerung interessant ist.
TRACKED_FIELDS = ("weight_kg", "resting_hr", "hrv_rmssd", "vo2max", "max_hr", "ftp_watts")


def _ensure_profile(db, user) -> AthleteProfile:
    if user.profile is None:
        user.profile = AthleteProfile()
        db.commit()
        db.refresh(user)
    return user.profile


def _to_out(profile: AthleteProfile) -> ProfileOut:
    age = calc_age(profile.birth_date)
    out = ProfileOut.model_validate(profile)
    out.age = age
    out.bmi = calc_bmi(profile.height_cm, profile.weight_kg)
    out.hr_zones = hr_zones(profile.max_hr, profile.resting_hr, age)
    return out


@router.get("", response_model=ProfileOut)
def get_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    return _to_out(_ensure_profile(db, user))


@router.put("", response_model=ProfileOut)
def update_profile(data: ProfileIn, user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = _ensure_profile(db, user)

    # Nur gesetzte Felder überschreiben — ein Teil-Update darf nichts löschen.
    updates = data.model_dump(exclude_unset=True)
    changed_tracked = any(
        field in updates and updates[field] != getattr(profile, field)
        for field in TRACKED_FIELDS
    )

    for field, value in updates.items():
        setattr(profile, field, value)

    if changed_tracked:
        db.add(
            ProfileHistory(
                user_id=user.id,
                **{field: getattr(profile, field) for field in TRACKED_FIELDS},
            )
        )

    db.commit()
    db.refresh(profile)
    return _to_out(profile)


@router.get("/history", response_model=list[ProfileHistoryOut])
def get_history(user: CurrentUser, db: DbSession) -> list[ProfileHistory]:
    return (
        db.query(ProfileHistory)
        .filter(ProfileHistory.user_id == user.id)
        .order_by(ProfileHistory.recorded_at.asc())
        .all()
    )
