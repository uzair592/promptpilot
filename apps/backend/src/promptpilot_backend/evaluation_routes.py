from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .evaluation_service import (
    ResponseEvaluationService,
    evaluation_lists,
    evaluation_metadata,
    list_evaluations,
)
from .llm_provider import ProviderUnavailable
from .models import Evaluation, User
from .project_policy import ProjectRole
from .schemas import (
    CompareEvaluationRequest,
    EvaluationListResponse,
    EvaluationResponse,
    SingleRunEvaluationRequest,
)

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}", tags=["evaluations"])


def evaluation_response(evaluation: Evaluation) -> EvaluationResponse:
    from .schemas import EvaluationItemResponse

    items = [
        EvaluationItemResponse(
            id=item.id,
            evaluation_id=item.evaluation_id,
            response_label=item.response_label,
            dimension=item.dimension,
            score=item.score,
            explanation=item.explanation,
        )
        for item in evaluation.items
    ]
    return EvaluationResponse(
        id=evaluation.id,
        project_id=evaluation.project_id,
        conversation_id=evaluation.conversation_id,
        baseline_model_run_id=evaluation.baseline_model_run_id,
        promptpilot_model_run_id=evaluation.promptpilot_model_run_id,
        method=evaluation.method,
        evaluator_provider=evaluation.evaluator_provider,
        evaluator_model=evaluation.evaluator_model,
        rubric_version=evaluation.rubric_version,
        baseline_score=evaluation.baseline_score,
        promptpilot_score=evaluation.promptpilot_score,
        overall_delta=evaluation.overall_delta,
        winner=evaluation.winner,
        comparison_summary=evaluation.comparison_summary,
        **evaluation_lists(evaluation),
        metadata=evaluation_metadata(evaluation),
        created_at=evaluation.created_at,
        items=items,
    )


@router.post("/runs/{run_id}/evaluate", response_model=EvaluationResponse)
def evaluate_run(
    conversation_id: UUID,
    run_id: UUID,
    payload: SingleRunEvaluationRequest = SingleRunEvaluationRequest(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    try:
        evaluation = ResponseEvaluationService().evaluate_single(
            db,
            conversation_id,
            run_id,
            payload.task,
            payload.selected_method(),
            payload.original_task,
            payload.requirements,
            payload.constraints,
            payload.context,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ProviderUnavailable as error:
        raise HTTPException(status_code=503, detail=error.reason) from None
    return evaluation_response(evaluation)


@router.post("/evaluations", response_model=EvaluationResponse)
@router.post("/evaluations/single", response_model=EvaluationResponse)
def evaluate_single(
    conversation_id: UUID,
    payload: SingleRunEvaluationRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    if payload.model_run_id is None:
        raise HTTPException(status_code=422, detail="model_run_id is required")
    try:
        evaluation = ResponseEvaluationService().evaluate_single(
            db,
            conversation_id,
            payload.model_run_id,
            payload.task,
            payload.selected_method(),
            payload.original_task,
            payload.requirements,
            payload.constraints,
            payload.context,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ProviderUnavailable as error:
        raise HTTPException(status_code=503, detail=error.reason) from None
    return evaluation_response(evaluation)


@router.post("/evaluations/compare", response_model=EvaluationResponse)
def compare_runs(
    conversation_id: UUID,
    payload: CompareEvaluationRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    try:
        baseline_run_id, promptpilot_run_id = payload.selected_run_ids()
        evaluation = ResponseEvaluationService().evaluate_pair(
            db,
            conversation_id,
            baseline_run_id,
            promptpilot_run_id,
            payload.task,
            payload.selected_method(),
            payload.original_task,
            payload.requirements,
            payload.constraints,
            payload.context,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ProviderUnavailable as error:
        raise HTTPException(status_code=503, detail=error.reason) from None
    return evaluation_response(evaluation)


@router.get("/evaluations", response_model=EvaluationListResponse)
def get_evaluations(
    conversation_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> EvaluationListResponse:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    return EvaluationListResponse(
        items=[evaluation_response(item) for item in list_evaluations(db, conversation_id)]
    )
