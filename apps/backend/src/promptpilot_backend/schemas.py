from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    key: str
    score: int | None
    status: str
    applicable: bool
    evidence: str | None
    explanation: str


class InformationGapResponse(BaseModel):
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
    content: str = Field(min_length=1, max_length=10000)


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
    memory_updates: list[ProjectMemoryResponse] = []


class PromptGenerateRequest(BaseModel):
    message_id: UUID
    mode: str = Field(default="structured", pattern="^(structured|minimal|detailed)$")
    regeneration_instruction: str = Field(default="", max_length=4000)


class PromptGenerationResponse(BaseModel):
    version_id: UUID
    version_number: int
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
    strategy: str = Field(pattern="^(baseline|promptpilot)$")
    message_id: UUID | None = None
    system_instruction: str | None = Field(default=None, max_length=10000)
    parameters: dict[str, float | int | str | bool] = {}


class ModelRunResponse(BaseModel):
    id: UUID
    prompt_version_id: UUID | None
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
