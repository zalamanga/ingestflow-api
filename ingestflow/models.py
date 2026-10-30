from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Status = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]


class Job(BaseModel):
    id: UUID
    sequence: int
    status: Status
    attempts: int
    row_count: int
    applied_count: int
    error_count: int
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class JobPage(BaseModel):
    items: list[Job]
    next_cursor: int | None


class RowError(BaseModel):
    row: int = Field(description="1-based CSV record index, header is 1; 0 is a file-level error")
    field: str
    code: str


class ErrorReport(BaseModel):
    import_id: UUID
    status: Status
    failure_code: str | None
    error_count: int
    errors: list[RowError]
    truncated: bool


class Record(BaseModel):
    sku: str
    name: str
    quantity: int
    source_import_id: UUID
    updated_at: datetime


class RecordPage(BaseModel):
    items: list[Record]
    next_cursor: str | None


class Event(BaseModel):
    seq: int
    kind: str
    details: dict
    created_at: datetime


class EventPage(BaseModel):
    items: list[Event]


class ErrorDetail(BaseModel):
    code: str
    message: str


class Error(BaseModel):
    error: ErrorDetail
