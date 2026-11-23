import base64
import json

import httpx

from epp.appconfig import OllamaEndpoint


class OllamaError(RuntimeError):
    pass


def _timeout(read: float) -> httpx.Timeout:
    return httpx.Timeout(connect=5.0, read=read, write=30.0, pool=5.0)


def list_models(endpoint: OllamaEndpoint) -> list[str]:
    try:
        resp = httpx.get(f"{endpoint.base_url}/api/tags", timeout=_timeout(10.0))
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise OllamaError(f"Ollama at {endpoint.base_url} not reachable: {e}") from e
    return sorted(m["name"] for m in resp.json().get("models", []))


def chat(
    endpoint: OllamaEndpoint,
    prompt: str,
    *,
    system: str | None = None,
    images: list[bytes] | None = None,
    schema: dict | str | None = None,
    num_ctx: int = 16384,
    num_predict: int = 8192,
    think: bool | None = None,
    timeout: float = 900.0,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    user: dict = {"role": "user", "content": prompt}
    if images:
        user["images"] = [base64.b64encode(img).decode("ascii") for img in images]
    messages.append(user)

    body: dict = {
        "model": endpoint.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict},
    }
    # Some vision models (e.g. qwen3-vl) misbehave with an explicit think=false, so it is opt-in.
    if think is not None:
        body["think"] = think
    if schema:
        body["format"] = schema
    try:
        resp = httpx.post(f"{endpoint.base_url}/api/chat", json=body, timeout=_timeout(timeout))
    except httpx.HTTPError as e:
        raise OllamaError(f"Ollama at {endpoint.base_url} not reachable: {e}") from e
    if resp.status_code != 200:
        raise OllamaError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    if data.get("done_reason") == "length":
        if not content.strip():
            raise OllamaError(f"{endpoint.model} used its whole token budget without answering (thinking model?)")
        if schema:
            raise OllamaError(f"{endpoint.model} output was cut off at the token limit")
    return content


def chat_json(endpoint: OllamaEndpoint, prompt: str, schema: dict | str, attempts: int = 2, **kwargs) -> dict:
    error: OllamaError | None = None
    for _ in range(attempts):
        try:
            content = chat(endpoint, prompt, schema=schema, **kwargs)
            return json.loads(content)
        except json.JSONDecodeError:
            error = OllamaError(f"Model did not return valid JSON: {content[:300]}")
        except OllamaError as e:
            if "not reachable" in str(e):
                raise
            error = e
    raise error
