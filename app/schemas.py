from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str
    model: str
