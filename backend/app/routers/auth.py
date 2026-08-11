from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_

from ..deps import CurrentUser, DbSession
from ..models import AthleteProfile, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, verify_password

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

    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(data.password),
    )
    # Leeres Profil direkt anlegen, damit das Frontend immer ein Objekt vorfindet.
    user.profile = AthleteProfile()

    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: DbSession) -> TokenOut:
    identifier = data.identifier.lower().strip()
    user = (
        db.query(User)
        .filter(
            or_(
                func.lower(User.email) == identifier,
                func.lower(User.username) == identifier,
            )
        )
        .first()
    )

    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzername oder Passwort ist falsch.",
        )

    return TokenOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
