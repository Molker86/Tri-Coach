from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession
from ..models import TrainingRequest
from ..schemas import TrainingRequestIn, TrainingRequestOut

router = APIRouter(prefix="/api/requests", tags=["questionnaire"])


@router.post("", response_model=TrainingRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    data: TrainingRequestIn, user: CurrentUser, db: DbSession
) -> TrainingRequest:
    request = TrainingRequest(user_id=user.id, **data.model_dump())
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@router.get("", response_model=list[TrainingRequestOut])
def list_requests(user: CurrentUser, db: DbSession) -> list[TrainingRequest]:
    return (
        db.query(TrainingRequest)
        .filter(TrainingRequest.user_id == user.id)
        .order_by(TrainingRequest.created_at.desc())
        .all()
    )


@router.get("/latest", response_model=TrainingRequestOut | None)
def latest_request(user: CurrentUser, db: DbSession) -> TrainingRequest | None:
    return (
        db.query(TrainingRequest)
        .filter(TrainingRequest.user_id == user.id)
        .order_by(TrainingRequest.created_at.desc())
        .first()
    )


@router.get("/{request_id}", response_model=TrainingRequestOut)
def get_request(request_id: int, user: CurrentUser, db: DbSession) -> TrainingRequest:
    request = db.get(TrainingRequest, request_id)
    if request is None or request.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fragebogen nicht gefunden.")
    return request


@router.put("/{request_id}", response_model=TrainingRequestOut)
def update_request(
    request_id: int, data: TrainingRequestIn, user: CurrentUser, db: DbSession
) -> TrainingRequest:
    request = db.get(TrainingRequest, request_id)
    if request is None or request.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fragebogen nicht gefunden.")

    for field, value in data.model_dump().items():
        setattr(request, field, value)

    db.commit()
    db.refresh(request)
    return request
