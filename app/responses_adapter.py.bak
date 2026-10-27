import json
from typing import Any


def responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    """Convert a basic OpenAI Responses API request to Chat Completions format."""

    messages: list[dict[str, Any]] = []

    instructions = body.get("instructions")
    if instructions:
        messages.append({
            "role": "system",
            "content": instructions,
        })

    input_items = body.get("input", [])

    if isinstance(input_items, str):
        messages.append({
            "role": "user",
            "content": input_items,
        })
    elif isinstance(input_items, list):
        for item in input_items:
            if isinstance(item, str):
                messages.append({
                    "role": "user",
                    "content": item,
                })
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("type", "")

            if item_type == "message":
                role = item.get("role", "user")
                content = item.get("content", "")

                if isinstance(content, list):
                    converted_content = []
                    for part in content:
                        if not isinstance(part, dict):
                            continue

                        part_type = part.get("type", "")

                        if part_type in ("input_text", "text"):
                            converted_content.append({
                                "type": "text",
                                "text": part.get("text", ""),
                            })
                        elif part_type == "input_image":
                            image_url = part.get("image_url")
                            if image_url:
                                converted_content.append({
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                })

                    content = converted_content

                messages.append({
                    "role": role,
                    "content": content,
                })

            elif item_type == "function_call_output":
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id", ""),
                    "content": str(item.get("output", "")),
                })

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": messages,
        "stream": bool(body.get("stream", False)),
    }

    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_output_tokens", "max_tokens"),
        ("parallel_tool_calls", "parallel_tool_calls"),
        ("tools", "tools"),
        ("tool_choice", "tool_choice"),
        ("stop", "stop"),
        ("user", "user"),
    ):
        if source in body:
            result[target] = body[source]

    if "metadata" in body:
        result["metadata"] = body["metadata"]

    return result


def chat_to_responses_text(response: dict[str, Any]) -> dict[str, Any]:
    """Convert a non-streaming Chat Completions response to Responses format."""

    choices = response.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})
    content = message.get("content") or ""

    output: list[dict[str, Any]] = []

    if content:
        output.append({
            "id": "msg_" + str(response.get("id", "response")),
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": content,
                "annotations": [],
            }],
        })

    result: dict[str, Any] = {
        "id": "resp_" + str(response.get("id", "unknown")),
        "object": "response",
        "status": "completed",
        "model": response.get("model", ""),
        "output": output,
    }

    usage = response.get("usage")
    if usage:
        result["usage"] = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        result["status"] = "incomplete"
        result["incomplete_details"] = {"reason": "max_output_tokens"}

    return result


def parse_json_object(raw: bytes) -> dict[str, Any]:
    """Parse a JSON request body and ensure the root is an object."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value
