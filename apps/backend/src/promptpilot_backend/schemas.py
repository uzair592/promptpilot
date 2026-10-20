from datetime import datetime
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def display_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Display name must not be blank")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    status: str
    created_at: datetime
    last_login_at: datetime | None


class AuthResponse(BaseModel):
    user: UserResponse


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    domain: str | None = Field(default=None, max_length=80)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Project name must not be blank")
        return value


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    domain: str | None = Field(default=None, max_length=80)

    @field_validator("name")
    @classmethod
    def update_name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Project name must not be blank")
        return value


class ProjectMemberResponse(BaseModel):
    user_id: UUID
    role: str
    status: str


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    domain: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    current_user_role: str
    members: list[ProjectMemberResponse]


class PageMetadata(BaseModel):
    cursor: str | None
    next_cursor: str | None
    limit: int
    total: int


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    page: PageMetadata


class ConversationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Conversation title must not be blank")
        return value


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def update_title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Conversation title must not be blank")
        return value


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    current_user_role: str


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    page: PageMetadata


class MessageCreateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"user", "assistant", "system"}:
            raise ValueError("Message role must be user, assistant, or system")
        return value

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    sequence: int
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    page: PageMetadata


class AnalysisDimensionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    score: int | None
    status: str
    applicable: bool
    evidence: str | None
    explanation: str


class InformationGapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dimension: str
    title: str
    description: str
    severity: str
    importance: str
    question_target: str
    status: str


class PromptAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    conversation_id: UUID
    message_id: UUID
    task_category: str
    overall_score: int
    status: str
    analysis_version: str
    analysis_mode: str
    ai_provider: str | None
    ai_model: str | None
    ai_succeeded: bool
    fallback_used: bool
    created_at: datetime
    dimensions: list[AnalysisDimensionResponse]
    gaps: list[InformationGapResponse]


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    text: str
    question_type: str
    priority: int
    status: str
    source: str
    options: list[str] | None = None


class AnswerCreateRequest(BaseModel):
    connection_id: UUID | None = None
    content: str = Field(min_length=1, max_length=10000)


class ClarificationAnswerResponse(BaseModel):
    id: UUID
    question_id: UUID
    question: str
    content: str
    created_at: datetime


class ProjectMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category: str
    subject: str
    content: str
    source: str
    status: str
    confidence: int
    created_at: datetime
    updated_at: datetime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    media_type: str
    source_type: str
    source_url: str | None
    size_bytes: int
    checksum: str
    status: str
    error_message: str | None
    processing_version: str
    created_at: datetime
    updated_at: datetime


class UrlIngestRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ContextAssembleRequest(BaseModel):
    task: str = Field(min_length=1, max_length=10000)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    analysis_id: UUID | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    budget: int = Field(default=8000, ge=500, le=100000)


class RetrievedContextResponse(BaseModel):
    content: str
    score: float
    source_type: str
    document_id: UUID | None
    chunk_id: UUID | None
    provenance: str
    metadata: dict[str, str]


class ContextPackageResponse(BaseModel):
    task: str
    project_memory: list[dict[str, str]]
    user_answers: list[dict[str, str]]
    document_context: list[RetrievedContextResponse]
    requirements: list[dict[str, str]]
    constraints: list[dict[str, str]]
    sources: list[dict[str, str]]
    omitted_items: list[dict[str, str]]
    budget: int
    used_budget: int


class QuestionSessionResponse(BaseModel):
    id: UUID
    status: str
    stop_reason: str | None
    next_question: QuestionResponse | None
    analysis: PromptAnalysisResponse | None = None
    answered_questions: list[ClarificationAnswerResponse] = Field(default_factory=list)
    memory_updates: list[ProjectMemoryResponse] = Field(default_factory=list)


class PromptGenerateRequest(BaseModel):
    connection_id: UUID | None = None
    message_id: UUID
    mode: str = Field(default="structured", pattern="^(structured|minimal|detailed)$")
    regeneration_instruction: str = Field(default="", max_length=4000)


class PromptGenerationResponse(BaseModel):
    version_id: UUID
    version_number: int
    source_message_id: UUID
    created_at: datetime
    original_prompt: str
    optimized_prompt: str
    task_summary: str
    assumptions: list[str]
    incorporated_context: list[str]
    incorporated_requirements: list[str]
    output_format: str
    quality_notes: list[str]
    warnings: list[str]
    generation_metadata: dict[str, object]


class ExecutePromptRequest(BaseModel):
    connection_id: UUID | None = None
    strategy: str = Field(pattern="^(baseline|promptpilot)$")
    message_id: UUID | None = None
    system_instruction: str | None = Field(default=None, max_length=10000)
    parameters: dict[str, float | int | str | bool] = {}


class ModelRunResponse(BaseModel):
    id: UUID
    prompt_version_id: UUID | None
    source_message_id: UUID
    execution_strategy: str
    optimized_prompt: str
    response_text: str | None
    provider: str
    model: str
    status: str
    finish_reason: str | None
    usage: dict[str, object]
    latency_ms: int | None
    error_message: str | None
    created_at: datetime


EVALUATION_DIMENSIONS = (
    "relevance",
    "completeness",
    "instruction_following",
    "contextual_grounding",
    "clarity",
)
EVALUATION_WEIGHTS = {
    "relevance": 25,
    "completeness": 20,
    "instruction_following": 20,
    "contextual_grounding": 20,
    "clarity": 15,
}


class ResponseScore(BaseModel):
    relevance: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    instruction_following: int = Field(ge=0, le=100)
    contextual_grounding: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    explanations: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)


class LLMJudgeOutput(BaseModel):
    """Strict structured output requested from an LLM judge."""

    response_a: ResponseScore
    response_b: ResponseScore


class SingleRunEvaluationRequest(BaseModel):
    method: str = Field(default="heuristic", pattern="^(heuristic|llm_judge)$")
    evaluator: str | None = Field(default=None, pattern="^(heuristic|llm_judge)$")
    model_run_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("model_run_id", "run_id")
    )
    task: str | None = Field(default=None, min_length=1, max_length=100000)
    original_task: str | None = Field(default=None, min_length=1, max_length=100000)
    requirements: list[dict[str, object] | str] = Field(default_factory=list)
    constraints: list[dict[str, object] | str] = Field(default_factory=list)
    context: list[dict[str, object] | str] = Field(default_factory=list)

    def selected_method(self) -> str:
        return self.evaluator or self.method


class CompareEvaluationRequest(BaseModel):
    baseline_model_run_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("baseline_model_run_id", "baseline_run_id"),
    )
    promptpilot_model_run_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("promptpilot_model_run_id", "promptpilot_run_id"),
    )
    method: str = Field(default="heuristic", pattern="^(heuristic|llm_judge)$")
    evaluator: str | None = Field(default=None, pattern="^(heuristic|llm_judge)$")
    task: str | None = Field(default=None, min_length=1, max_length=100000)
    original_task: str | None = Field(default=None, min_length=1, max_length=100000)
    requirements: list[dict[str, object] | str] = Field(default_factory=list)
    constraints: list[dict[str, object] | str] = Field(default_factory=list)
    context: list[dict[str, object] | str] = Field(default_factory=list)

    def selected_method(self) -> str:
        return self.evaluator or self.method

    def selected_run_ids(self) -> tuple[UUID, UUID]:
        if self.baseline_model_run_id is None or self.promptpilot_model_run_id is None:
            raise ValueError("baseline_model_run_id and promptpilot_model_run_id are required")
        return self.baseline_model_run_id, self.promptpilot_model_run_id


class EvaluationItemResponse(BaseModel):
    id: UUID
    evaluation_id: UUID
    response_label: str
    dimension: str
    score: int
    explanation: str


class EvaluationResponse(BaseModel):
    id: UUID
    project_id: UUID
    conversation_id: UUID
    baseline_model_run_id: UUID | None
    promptpilot_model_run_id: UUID | None
    method: str
    evaluator_provider: str
    evaluator_model: str
    rubric_version: str
    baseline_score: float | None
    promptpilot_score: float | None
    overall_delta: float | None
    winner: str | None
    comparison_summary: str | None
    baseline_strengths: list[str]
    baseline_weaknesses: list[str]
    promptpilot_strengths: list[str]
    promptpilot_weaknesses: list[str]
    metadata: dict[str, object]
    created_at: datetime
    items: list[EvaluationItemResponse]


class EvaluationListResponse(BaseModel):
    items: list[EvaluationResponse]


# Explicit names keep the public contract readable for clients that distinguish
# the two creation flows while sharing the same persisted response shape.
class CompareEvaluationResponse(EvaluationResponse):
    pass


class SingleRunEvaluationResponse(EvaluationResponse):
    pass


class CompareResponsesRequest(CompareEvaluationRequest):
    pass


class ProviderConnectionCreateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=8, max_length=1000)
    default_model: str = Field(min_length=1, max_length=240)
    base_url: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_provider_endpoint(self) -> "ProviderConnectionCreateRequest":
        from .provider_registry import provider_definition

        provider_definition(self.provider, self.base_url)
        return self

    @field_validator("label", "api_key", "default_model")
    @classmethod
    def provider_value_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class ProviderConnectionResponse(BaseModel):
    id: UUID
    provider: str
    label: str
    masked_key: str
    default_model: str
    base_url: str | None = None
    available_models: list[str] = Field(default_factory=list)
    status: str
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str | None
    created_at: datetime
    updated_at: datetime


class ProviderConnectionListResponse(BaseModel):
    items: list[ProviderConnectionResponse]


class ProviderTestResponse(BaseModel):
    connection: ProviderConnectionResponse
    available_models: list[str]


class ProviderConnectionUpdateRequest(BaseModel):
    default_model: str | None = Field(default=None, min_length=1, max_length=240)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)

    @field_validator("default_model", "api_key")
    @classmethod
    def connection_update_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Value must not be blank")
        return value


class ProviderDiscoveryRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=1000)
    base_url: str | None = None


class ProjectPlanCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    idea: str = Field(min_length=10, max_length=20000)
    start_at: datetime | None = None
    planner_connection_id: UUID | None = None

    @field_validator("title", "idea")
    @classmethod
    def plan_value_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class ProjectRepositoryRequest(BaseModel):
    owner: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    token: str = Field(min_length=8, max_length=1000)


class ProjectRepositoryResponse(BaseModel):
    owner: str
    repo: str
    default_branch: str
    url: str


class PublishTaskResponse(BaseModel):
    pull_request_url: str
    branch: str


class AgentDraftUpdateRequest(BaseModel):
    output_text: str = Field(min_length=1, max_length=1000000)


class AgentTaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    dependencies: list[UUID] | None = Field(default=None, max_length=30)
    acceptance_criteria: list[str] | None = Field(default=None, max_length=20)
    review_notes: str | None = Field(default=None, max_length=10000)
    assigned_connection_id: UUID | None = None
    assigned_model: str | None = Field(default=None, max_length=240)
    scheduled_for: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern="^(backlog|scheduled|ready|review|completed|cancelled)$",
    )


class AgentRunResponse(BaseModel):
    id: UUID
    task_id: UUID
    provider: str
    model: str
    status: str
    output_text: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class AgentTaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    plan_id: UUID
    milestone_id: UUID
    title: str
    description: str
    role: str
    assignment_reason: str
    assigned_connection_id: UUID | None
    assigned_provider: str | None
    assigned_model: str | None
    review_notes: str | None = None
    acceptance_criteria: list[str]
    dependencies: list[str]
    status: str
    scheduled_for: datetime | None
    output_text: str | None
    pull_request_url: str | None
    last_error: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class PlanMilestoneResponse(BaseModel):
    id: UUID
    plan_id: UUID
    title: str
    description: str
    position: int
    status: str
    due_at: datetime | None
    tasks: list[AgentTaskResponse]


class ProjectPlanResponse(BaseModel):
    planning_mode: str = "template"
    id: UUID
    project_id: UUID
    title: str
    summary: str
    status: str
    created_at: datetime
    updated_at: datetime
    milestones: list[PlanMilestoneResponse]


class ProjectPlanListResponse(BaseModel):
    items: list[ProjectPlanResponse]
