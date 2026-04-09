from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import httpx
import time
from config import settings


app = FastAPI(title="Qwen API", version="1.0.0")
security = HTTPBearer(auto_error=False)


def verify_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if not settings.api_keys:
        return
    if credentials is None or credentials.credentials not in settings.api_keys:
        raise HTTPException(status_code=401, detail="Unauthorized")


class Message(BaseModel):
    role: str
    content: str | list


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[Message]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None


def prepare_messages(messages: list[Message]) -> list[dict]:
    result = [{"role": m.role, "content": m.content} for m in messages]

    injected = ""
    if not settings.enable_thinking:
        injected = "/no_think"
    if settings.system_prompt:
        injected = (injected + "\n" + settings.system_prompt).strip()

    if not injected:
        return result

    for m in result:
        if m["role"] == "system":
            if not settings.enable_thinking and "/no_think" not in str(m["content"]):
                m["content"] = "/no_think\n" + m["content"]
            return result

    result.insert(0, {"role": "system", "content": injected})
    return result


def build_payload(request: ChatRequest) -> dict:
    payload: dict = {
        "model": request.model or settings.default_model,
        "messages": prepare_messages(request.messages),
        "stream": request.stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    return payload


async def stream_ollama(payload: dict):
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/v1/chat/completions",
            json=payload,
        ) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        ollama_ok = False
    return {"status": "ok", "ollama": ollama_ok}


@app.get("/v1/models", dependencies=[Depends(verify_key)])
async def list_models():
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
        except Exception:
            raise HTTPException(status_code=502, detail="Ollama unreachable")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Ollama error")
    data = resp.json()
    return {
        "object": "list",
        "data": [
            {
                "id": m["name"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local",
            }
            for m in data.get("models", [])
        ],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(verify_key)])
async def chat_completions(request: ChatRequest):
    payload = build_payload(request)

    if request.stream:
        return StreamingResponse(
            stream_ollama(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        try:
            resp = await client.post(
                f"{settings.ollama_base_url}/v1/chat/completions",
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Ollama request timed out")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return JSONResponse(content=resp.json())