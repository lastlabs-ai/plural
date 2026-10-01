import json

import httpx
import respx

from plural.providers import GoogleProvider, OpenAIProvider
from plural.types import ChatRequest, Message


@respx.mock
def test_google_chat() -> None:
    provider = GoogleProvider("key", base_url="https://generativelanguage.googleapis.com/v1beta")
    respx.post(url__regex=r".*/models/gemini-2.5-flash:generateContent.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Hey"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
            },
        )
    )
    resp = provider.chat(
        ChatRequest(
            model="google/gemini-2.5-flash",
            messages=[Message(role="user", content="Hi")],
        )
    )
    assert resp.text == "Hey"


@respx.mock
def test_the_api_key_travels_in_a_header_never_the_url() -> None:
    provider = GoogleProvider("secret", base_url="https://generativelanguage.googleapis.com/v1beta")
    route = respx.post(url__regex=r".*/models/gemini-2.5-flash:generateContent.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Hey"}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
            },
        )
    )
    provider.chat(
        ChatRequest(model="google/gemini-2.5-flash", messages=[Message(role="user", content="Hi")])
    )
    sent = route.calls.last.request
    assert sent.headers["x-goog-api-key"] == "secret"
    assert "secret" not in str(sent.url)


@respx.mock
def test_a_thought_signature_survives_the_tool_call_round_trip() -> None:
    """Gemini 400s when a replayed function call lacks the signature it was made with."""
    route = respx.post(url__regex=r".*/models/gemini-3.7-flash:generateContent.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {"name": "guess", "args": {"word": "crane"}},
                                    "thoughtSignature": "sig-1",
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
            },
        )
    )
    provider = GoogleProvider("key", base_url="https://generativelanguage.googleapis.com/v1beta")
    first = provider.chat(
        ChatRequest(
            model="google/gemini-3.7-flash", messages=[Message(role="user", content="Play")]
        )
    )
    [call] = first.choices[0].message.tool_calls or []
    assert call.extra_content == {"google": {"thought_signature": "sig-1"}}

    # The gateway rebuilds the conversation from the harness's OpenAI-shaped JSON.
    replayed = Message.model_validate(first.choices[0].message.model_dump(mode="json"))
    provider.chat(
        ChatRequest(
            model="google/gemini-3.7-flash",
            messages=[
                Message(role="user", content="Play"),
                replayed,
                Message(role="tool", tool_call_id=call.id, name="guess", content="-?+--"),
            ],
        )
    )
    sent = json.loads(route.calls[-1].request.content)
    assert sent["contents"][1]["parts"][0]["thoughtSignature"] == "sig-1"
    provider.close()

    openai = OpenAIProvider("sk-test", transport="chat")
    payload = openai._encode_request(
        ChatRequest(
            model="openai/gpt-5", messages=[Message(role="user", content="Play"), replayed]
        ),
        stream=False,
    )
    assert "extra_content" not in payload["messages"][1]["tool_calls"][0]
    openai.close()


@respx.mock
def test_google_stream_is_openai_shaped() -> None:
    sse = (
        'data: {"responseId":"r1","candidates":[{"content":{"parts":[{"text":"He"}]}}]}\n\n'
        'data: {"responseId":"r1","candidates":[{"content":{"parts":[{"text":"y"}],'
        '"role":"model"},"finishReason":"STOP"}],'
        '"usageMetadata":{"promptTokenCount":2,"candidatesTokenCount":1}}\n\n'
    )
    respx.post(url__regex=r".*/models/gemini-2.5-flash:streamGenerateContent.*").mock(
        return_value=httpx.Response(
            200, content=sse.encode(), headers={"Content-Type": "text/event-stream"}
        )
    )
    provider = GoogleProvider("key", base_url="https://generativelanguage.googleapis.com/v1beta")
    chunks = list(
        provider.stream(
            ChatRequest(
                model="google/gemini-2.5-flash",
                messages=[Message(role="user", content="Hi")],
                stream=True,
            )
        )
    )
    assert "".join(c.delta.content or "" for c in chunks) == "Hey"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.prompt_tokens == 2
    payload = chunks[0].to_openai()
    assert payload["object"] == "chat.completion.chunk"
    assert payload["choices"][0]["delta"]["content"] == "He"
    assert "candidates" not in payload
    provider.close()
