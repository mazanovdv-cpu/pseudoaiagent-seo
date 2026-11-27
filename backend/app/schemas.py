from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Пустое значение")
    return cleaned


class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class AgentDetail(AgentListItem):
    system_prompt: str


class AgentUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1, max_length=20000)

    @field_validator("name", "system_prompt")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _clean(value)


class AgentSaved(AgentDetail):
    action: Literal["created", "updated"]


class ReportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200000)
    title: str = Field(default="Отчет", max_length=200)

    @field_validator("text", "title")
    @classmethod
    def strip_report(cls, value: str) -> str:
        return _clean(value)


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return _clean(value)
