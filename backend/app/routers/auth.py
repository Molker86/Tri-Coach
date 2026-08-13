from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_

from ..deps import CurrentUser, DbSession
from ..models import AthleteProfile, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOption, UserOut
from ..security import create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: DbSession) -> TokenOut:
    email = data.email.lower().strip()
    username = data.username.strip()

    existing = (
        db.query(User)
        .filter(
            or_(
                func.lower(User.email) == email,
                func.lower(User.username) == username.lower(),
            )
        )
        .first()
    )
    if existing:
        field = "E-Mail-Adresse" if existing.email.lower() == email else "Benutzername"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Diese(r) {field} ist bereits vergeben.",
        )

    user = User(email=email, username=username)
    # Leeres Profil direkt anlegen, damit das Frontend immer ein Objekt vorfindet.
    user.profile = AthleteProfile()

    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.get("/users", response_model=list[UserOption])
def list_users(db: DbSession) -> list[User]:
    """Kontoauswahl für die Anmeldeseite.

    Ohne Authentifizierung erreichbar -- sie ist die Anmeldung, käme sie nur
    mit Token, wäre sie nutzlos. Sie liefert deshalb nur Name und ID.
    """
    return db.query(User).order_by(func.lower(User.username)).all()


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: DbSession) -> TokenOut:
    """Anmeldung per Kontoauswahl, ohne Passwort.

    Bewusste Entscheidung: Die App läuft hinter dem Home-Assistant-Ingress,
    der die Sitzung bereits authentifiziert. Ein zweites Passwort davor wäre
    nur ein Hindernis, keine zusätzliche Absicherung.
    """
    user = db.get(User, data.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dieses Konto gibt es nicht mehr.",
        )

    return TokenOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
