from pydantic import BaseModel, Field, ValidationError


class StartAgentRequestBody(BaseModel):
    channel_name: str = Field(..., description="The name of the channel")
    uid: int = Field(..., description="The UID of the user")
    language: str = Field("en", description="The language of the agent")
    system_instruction: str = Field("", description="The system instruction for the agent")
    voice: str = Field("ballad", description="The voice of the agent")


class StopAgentRequestBody(BaseModel):
    channel_name: str = Field(..., description="The name of the channel")
