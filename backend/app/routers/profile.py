from fastapi import APIRouter

from ..deps import CurrentUser, DbSession
from ..models import AthleteProfile, ProfileHistory
from ..profile_sync import TRACKED_FIELDS, uebernehme_profilwerte
from ..schemas import ProfileHistoryOut, ProfileIn, ProfileOut
from ..sportscience import calc_age, calc_bmi, hr_zones

router = APIRouter(prefix="/api/profile", tags=["profile"])

__all__ = ["router", "TRACKED_FIELDS"]


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
    uebernehme_profilwerte(db, user.id, profile, data.model_dump(exclude_unset=True))

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
