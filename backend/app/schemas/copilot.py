from pydantic import BaseModel, Field, field_validator


class CopilotQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question must not be blank.")
        return v
