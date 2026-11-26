"""Specs for a synchronous screening call and its asynchronous replacement."""

from fastapi import FastAPI, Header
from pydantic import BaseModel

before = FastAPI(title="Screening flow before")
after = FastAPI(title="Screening flow after")


class Hits(BaseModel):
    hits: list[str]


class Token(BaseModel):
    accessToken: str


class Configuration(BaseModel):
    configurationId: str


class ScreeningInput(Configuration):
    callbackUrl: str


class Job(BaseModel):
    jobId: str


class Receipt(BaseModel):
    pageId: str


@before.post("/screenings", tags=["screening"], summary="Screen a person and return all hits")
def screen() -> Hits:
    return Hits(hits=["example hit"])


@before.get("/legacy-screening-statistics", summary="Read old screening statistics")
def legacy_statistics():
    return {"total": 1}


@before.get("/health", summary="Read service health")
@after.get("/health", summary="Read service health")
def health():
    return {"healthy": True}


@after.post("/token", summary="Get an access token for screening")
def token() -> Token:
    return Token(accessToken="toy-token")


@after.get("/screening-configurations", tags=["screening"], summary="Choose a screening configuration")
def configurations(accessToken: str = Header()) -> list[Configuration]:
    return [Configuration(configurationId="default")]


completion = {
    "screeningCompleted": {
        "{$request.body#/callbackUrl}": {
            "post": {
                "summary": "Receive the notification that screening completed",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["resultId"],
                    "properties": {"resultId": {"type": "string"}},
                }}}},
                "responses": {"204": {"description": "Notification received"}},
            },
        },
    },
}


@after.post("/screening-jobs", tags=["screening"], summary="Start screening with the selected configuration",
            openapi_extra={"callbacks": completion})
def start_screening(screening: ScreeningInput) -> Job:
    return Job(jobId="job-1")


@after.get("/screening-results/{resultId}", tags=["screening"], summary="Read the completed screening result receipt")
def read_receipt(resultId: str) -> Receipt:
    return Receipt(pageId="first")


@after.get("/screening-results/{resultId}/pages/{pageId}", tags=["screening"], summary="Read a page of screening hits")
def page(resultId: str, pageId: str, pageSize: int = 10) -> Hits:
    return Hits(hits=["example hit"])


@after.get("/service-metrics", summary="Read internal metrics")
def metrics():
    return {"uptime": 1}
