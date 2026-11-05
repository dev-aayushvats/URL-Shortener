from pydantic import BaseModel, HttpUrl


class ShortenRequest(BaseModel):
    target_url: HttpUrl


class ShortenResponse(BaseModel):
    short_code: str
    target_url: str
    short_url: str
