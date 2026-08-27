from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Commentary(BaseModel):
    sentences: list[str] = Field(min_length=2, max_length=4)  # FR-703: 2~4문장
    source: Literal["llm", "fallback"]
    generated_at: datetime
