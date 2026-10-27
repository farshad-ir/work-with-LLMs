import json

from app.responses_adapter import (
    ResponsesStreamConverter,
    chat_to_responses_text,
    parse_chat_sse_event,
    responses_to_chat,
)


def test_responses_to_chat():
    result = responses_to_chat({
        "model": "test-model",
        "instructions": "Be concise.",
        "input": "Hello",
    })

    assert result["model"] == "test-model"
    assert result["messages"][0] == {
        "role": "system",
        "content": "Be concise.",
    }
    assert result["messages"][1] == {
        "role": "user",
        "content": "Hello",
    }


def test_chat_to_responses_text():
    result = chat_to_responses_text({
        "id": "chatcmpl-test",
        "model": "test-model",
        "choices": [{
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "total_tokens": 5,
        },
    })

    assert result["object"] == "response"
    assert result["status"] == "completed"
    assert result["output"][0]["content"][0]["text"] == "Hello!"
    assert result["usage"]["total_tokens"] == 5


def test_stream_text_conversion():
    converter = ResponsesStreamConverter()
    raw_events = [
        'data: {"id":"chatcmpl-test","model":"test-model","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-test","model":"test-model","choices":[{"index":0,"delta":{"content":" world!"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-test","model":"test-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
    ]

    output = []
    for raw in raw_events:
        parsed = parse_chat_sse_event(raw)
        if parsed:
            output.extend(converter.feed(parsed))

    assert converter.text == "Hello world!"
    assert any("event: response.output_text.delta" in item for item in output)
    assert any("event: response.completed" in item for item in output)


def test_stream_tool_conversion():
    converter = ResponsesStreamConverter()
    raw_events = [
        'data: {"id":"chatcmpl-tool","model":"test-model","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_123","type":"function","function":{"name":"get_weather","arguments":""}}]},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-tool","model":"test-model","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"city\\":\\"Berlin\\"}"}}]},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-tool","model":"test-model","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
    ]

    output = []
    for raw in raw_events:
        parsed = parse_chat_sse_event(raw)
        if parsed:
            output.extend(converter.feed(parsed))

    assert converter.tool_calls[0]["name"] == "get_weather"
    assert converter.tool_calls[0]["arguments"] == '{"city":"Berlin"}'
    assert any(
        "event: response.function_call_arguments.delta" in item
        for item in output
    )
    assert any("event: response.completed" in item for item in output)
