from typing import Literal, Optional
from pydantic import BaseModel, Field

class Source(BaseModel):
    type: Literal["local", "http", "azure-sas"] = "local"
    path: Optional[str] = None
    url: Optional[str] = None
    checksum: str

class PrepareRequest(BaseModel):
    sessionId: str = Field(min_length=1)
    gameId: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source: Source

class LaunchRequest(BaseModel):
    sessionId: str = Field(min_length=1)
    gameId: str = Field(min_length=1)

class StopRequest(BaseModel):
    sessionId: str = Field(min_length=1)

class ErrorBody(BaseModel):
    code: str
    message: str

class ErrorResponse(BaseModel):
    error: ErrorBody
