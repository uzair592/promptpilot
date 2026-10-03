from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("normalized_email", name="uq_users_normalized_email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sessions: Mapped[list["SessionToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="sessions")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationMessageCounter(Base):
    __tablename__ = "conversation_message_counters"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "idempotency_key", name="uq_messages_conversation_idempotency"
        ),
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class PromptAnalysis(Base):
    __tablename__ = "prompt_analyses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    task_category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    analysis_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="baseline")
    ai_provider: Mapped[str | None] = mapped_column(String(80))
    ai_model: Mapped[str | None] = mapped_column(String(160))
    ai_succeeded: Mapped[bool] = mapped_column(nullable=False, default=False)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    dimensions: Mapped[list["PromptAnalysisDimension"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    gaps: Mapped[list["InformationGap"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class PromptAnalysisDimension(Base):
    __tablename__ = "prompt_analysis_dimensions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_analyses.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    applicable: Mapped[bool] = mapped_column(nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[PromptAnalysis] = relationship(back_populates="dimensions")


class InformationGap(Base):
    __tablename__ = "information_gaps"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_analyses.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), nullable=False)
    question_target: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unresolved")
    analysis: Mapped[PromptAnalysis] = relationship(back_populates="gaps")


class QuestionSession(Base):
    __tablename__ = "question_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_analyses.id", ondelete="CASCADE"), index=True
    )
    latest_analysis_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_analyses.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    stop_reason: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_sessions.id", ondelete="CASCADE"), index=True
    )
    gap_id: Mapped[UUID] = mapped_column(
        ForeignKey("information_gaps.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(20), nullable=False, default="free_text")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="fallback")
    options: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[QuestionSession] = relationship(back_populates="questions")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    question: Mapped[Question] = relationship(back_populates="answers")


class ProjectMemoryItem(Base):
    __tablename__ = "project_memory"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="file")
    source_url: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="document-processing-v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[str | None] = mapped_column(Text)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_version: Mapped[str] = mapped_column(String(40), nullable=False)
    document: Mapped[Document] = relationship(back_populates="chunks")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    source_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("prompt_analyses.id", ondelete="SET NULL"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    optimized_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    prompt_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("prompt_versions.id", ondelete="SET NULL"), index=True)
    source_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    execution_strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    optimized_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    finish_reason: Mapped[str | None] = mapped_column(String(80))
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    generation_parameters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class Evaluation(Base):
    """A persisted evaluation of one response or a baseline/prompt comparison."""

    __tablename__ = "evaluations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    baseline_model_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), index=True
    )
    promptpilot_model_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), index=True
    )
    method: Mapped[str] = mapped_column(String(30), nullable=False, default="heuristic")
    evaluator_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    evaluator_model: Mapped[str] = mapped_column(String(160), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_score: Mapped[float | None] = mapped_column()
    promptpilot_score: Mapped[float | None] = mapped_column()
    overall_delta: Mapped[float | None] = mapped_column()
    winner: Mapped[str | None] = mapped_column(String(20))
    comparison_summary: Mapped[str | None] = mapped_column(Text)
    baseline_strengths: Mapped[str | None] = mapped_column(Text)
    baseline_weaknesses: Mapped[str | None] = mapped_column(Text)
    promptpilot_strengths: Mapped[str | None] = mapped_column(Text)
    promptpilot_weaknesses: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    items: Mapped[list["EvaluationItem"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class EvaluationItem(Base):
    __tablename__ = "evaluation_items"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "response_label", "dimension",
            name="uq_evaluation_items_evaluation_response_dimension",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), index=True
    )
    response_label: Mapped[str] = mapped_column(String(20), nullable=False)
    dimension: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation: Mapped[Evaluation] = relationship(back_populates="items")


class BenchmarkExperimentRun(Base):
    """Durable technical ledger state; never proof of external study approval."""

    __tablename__ = "benchmark_experiment_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staged', 'running', 'completed', 'failed', 'aborted')",
            name="ck_benchmark_experiment_runs_status",
        ),
        CheckConstraint(
            "external_human_approval_verified = false",
            name="ck_benchmark_experiment_runs_human_unverified",
        ),
        CheckConstraint(
            "analysis_call_ceiling >= 0 AND question_generation_call_ceiling >= 0 "
            "AND prompt_generation_call_ceiling >= 0 AND target_execution_call_ceiling >= 0 "
            "AND judge_call_ceiling >= 0 AND total_call_ceiling >= 0",
            name="ck_benchmark_experiment_runs_nonnegative_ceilings",
        ),
        CheckConstraint(
            "reserved_count >= 0 AND succeeded_count >= 0 AND failed_count >= 0 "
            "AND cancelled_count >= 0 AND analysis_consumed_count >= 0 "
            "AND question_generation_consumed_count >= 0 "
            "AND prompt_generation_consumed_count >= 0 "
            "AND target_execution_consumed_count >= 0 AND judge_consumed_count >= 0",
            name="ck_benchmark_experiment_runs_nonnegative_counts",
        ),
        CheckConstraint(
            "total_call_ceiling = analysis_call_ceiling "
            "+ question_generation_call_ceiling + prompt_generation_call_ceiling "
            "+ target_execution_call_ceiling + judge_call_ceiling",
            name="ck_benchmark_experiment_runs_ceiling_total",
        ),
        CheckConstraint(
            "analysis_consumed_count <= analysis_call_ceiling "
            "AND question_generation_consumed_count <= question_generation_call_ceiling "
            "AND prompt_generation_consumed_count <= prompt_generation_call_ceiling "
            "AND target_execution_consumed_count <= target_execution_call_ceiling "
            "AND judge_consumed_count <= judge_call_ceiling",
            name="ck_benchmark_experiment_runs_role_budgets",
        ),
        CheckConstraint(
            "reserved_count + succeeded_count + failed_count <= total_call_ceiling",
            name="ck_benchmark_experiment_runs_total_budget",
        ),
        CheckConstraint(
            "spent_amount >= 0",
            name="ck_benchmark_experiment_runs_spend_nonnegative",
        ),
        CheckConstraint(
            "max_spend IS NULL OR max_spend >= 0",
            name="ck_benchmark_experiment_runs_max_spend_valid",
        ),
        CheckConstraint(
            "max_spend IS NULL OR spent_amount <= max_spend",
            name="ck_benchmark_experiment_runs_spend_within_limit",
        ),
        CheckConstraint(
            "spent_currency IS NULL OR budget_currency IS NULL OR spent_currency = budget_currency",
            name="ck_benchmark_experiment_runs_spend_currency_match",
        ),
        CheckConstraint(
            "reserved_spend >= 0",
            name="ck_benchmark_experiment_runs_reserved_spend_nonnegative",
        ),
        CheckConstraint(
            "max_spend IS NULL OR (spent_amount + reserved_spend) <= max_spend",
            name="ck_benchmark_experiment_runs_spend_reserved_within_limit",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    experiment_scope: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_id: Mapped[str] = mapped_column(String(160), nullable=False)
    protocol_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="staged", index=True)
    frozen_role_bindings_json: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    question_generation_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_generation_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    target_execution_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    judge_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    total_call_ceiling: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_consumed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_generation_consumed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    prompt_generation_consumed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    target_execution_consumed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    judge_consumed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_sequence: Mapped[int] = mapped_column(
        Integer, CheckConstraint("next_attempt_sequence >= 0"), nullable=False, default=0
    )
    budget_currency: Mapped[str | None] = mapped_column(String(3))
    max_spend: Mapped[float | None] = mapped_column(Float)
    spent_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spent_currency: Mapped[str | None] = mapped_column(String(3))
    reserved_spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    external_human_approval_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    abort_reason_code: Mapped[str | None] = mapped_column(String(80))
    failure_reason_code: Mapped[str | None] = mapped_column(String(80))
    repository_commit_sha: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aborted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[list["BenchmarkProviderCallAttempt"]] = relationship(
        back_populates="experiment_run", cascade="all, delete-orphan"
    )


class BenchmarkProviderCallAttempt(Base):
    """Credential-free provider-call reservation and terminal metadata."""

    __tablename__ = "benchmark_provider_call_attempts"
    __table_args__ = (
        UniqueConstraint(
            "experiment_run_id",
            "idempotency_key",
            name="uq_benchmark_attempts_run_idempotency",
        ),
        UniqueConstraint(
            "experiment_run_id",
            "sequence_number",
            name="uq_benchmark_attempts_run_sequence",
        ),
        CheckConstraint(
            "provider_role IN ('analysis', 'question_generation', 'prompt_generation', "
            "'target_execution', 'judge')",
            name="ck_benchmark_attempts_role",
        ),
        CheckConstraint(
            "status IN ('reserved', 'started', 'succeeded', 'failed', 'cancelled')",
            name="ck_benchmark_attempts_status",
        ),
        CheckConstraint("repetition >= 1", name="ck_benchmark_attempts_repetition"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_benchmark_attempts_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_benchmark_attempts_output_tokens",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_benchmark_attempts_total_tokens",
        ),
        CheckConstraint(
            "cost_estimate IS NULL OR cost_estimate >= 0",
            name="ck_benchmark_attempts_cost",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experiment_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("benchmark_experiment_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stable_unit_id: Mapped[str] = mapped_column(String(240), nullable=False)
    fixture_id: Mapped[str] = mapped_column(String(160), nullable=False)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    repetition: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_condition: Mapped[str | None] = mapped_column(String(20))
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    configured_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    configured_model: Mapped[str] = mapped_column(String(240), nullable=False)
    generation_parameter_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    safe_error_type: Mapped[str | None] = mapped_column(String(80))
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    fallback_classification: Mapped[str | None] = mapped_column(String(40))
    observation_outcome: Mapped[str | None] = mapped_column(String(40))
    response_artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    experiment_run: Mapped[BenchmarkExperimentRun] = relationship(back_populates="attempts")


_IMMUTABLE_BENCHMARK_ATTEMPT_FIELDS = (
    "experiment_run_id",
    "stable_unit_id",
    "fixture_id",
    "task_id",
    "repetition",
    "provider_role",
    "target_condition",
    "sequence_number",
    "idempotency_key",
    "configured_provider",
    "configured_model",
    "generation_parameter_sha256",
    "request_artifact_sha256",
)


@event.listens_for(BenchmarkProviderCallAttempt, "before_update")
def _prevent_benchmark_attempt_identity_mutation(
    _mapper: object, _connection: object, target: BenchmarkProviderCallAttempt
) -> None:
    state = inspect(target)
    if any(state.attrs[field].history.has_changes() for field in _IMMUTABLE_BENCHMARK_ATTEMPT_FIELDS):
        raise ValueError("Benchmark provider-call attempt identity is immutable")
