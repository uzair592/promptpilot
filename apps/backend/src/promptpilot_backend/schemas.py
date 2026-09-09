from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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


class AnswerCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class QuestionSessionResponse(BaseModel):
    id: UUID
    status: str
    stop_reason: str | None
    next_question: QuestionResponse | None
