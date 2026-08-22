import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response

from orchestrator import run_research_pipeline

app = FastAPI(title="Stock Research Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


@app.options("/research/{ticker}")
async def research_ticker_preflight(ticker: str):
    return Response(status_code=200, headers=CORS_HEADERS)


@app.post("/research/{ticker}")
async def research_ticker(ticker: str):
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        **CORS_HEADERS,
    }
    return StreamingResponse(
        run_research_pipeline(ticker),
        media_type="text/event-stream",
        headers=headers,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "headers": CORS_HEADERS}
