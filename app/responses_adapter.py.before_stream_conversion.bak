import json
from typing import Any


def responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    """Convert a Responses API request into Chat Completions format."""

    messages: list[dict[str, Any]] = []

    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": instructions})

    input_items = body.get("input", [])

    if isinstance(input_items, str):
        messages.append({"role": "user", "content": input_items})

    elif isinstance(input_items, list):
        for item in input_items:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
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

                        if part_type in ("input_text", "text", "output_text"):
                            converted_content.append({
                                "type": "text",
                                "text": part.get("text", ""),
                            })

                        elif part_type == "input_image":
                            image_url = part.get("image_url")

                            if isinstance(image_url, dict):
                                image_url = image_url.get("url")

                            if image_url:
                                converted_content.append({
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                })

                    content = converted_content

                messages.append({"role": role, "content": content})

            elif item_type == "function_call":
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": item.get("call_id", ""),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", "{}"),
                        },
                    }],
                })

            elif item_type == "function_call_output":
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id", ""),
                    "content": output_to_string(item.get("output", "")),
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
        ("stop", "stop"),
        ("user", "user"),
        ("seed", "seed"),
    ):
        if source in body:
            result[target] = body[source]

    tools = body.get("tools")
    if isinstance(tools, list):
        converted_tools = []

        for tool in tools:
            if not isinstance(tool, dict):
                continue

            if tool.get("type") == "function":
                function = {
                    key: tool[key]
                    for key in ("name", "description", "parameters", "strict")
                    if key in tool
                }

                converted_tools.append({
                    "type": "function",
                    "function": function,
                })

            elif tool.get("type") == "web_search_preview":
                # This tool is not directly supported by Chat Completions.
                continue

        if converted_tools:
            result["tools"] = converted_tools

    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        function_choice = tool_choice.get("function", {})
        function_name = (
            function_choice.get("name", "")
            if isinstance(function_choice, dict)
            else ""
        )
        function_name = function_name or tool_choice.get("name", "")

        result["tool_choice"] = {
            "type": "function",
            "function": {"name": function_name},
        }
    elif tool_choice is not None:
        result["tool_choice"] = tool_choice

    if body.get("stream") and isinstance(body.get("stream_options"), dict):
        result["stream_options"] = body["stream_options"]

    return result


def output_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def chat_to_responses_text(response: dict[str, Any]) -> dict[str, Any]:
    """Convert a non-streaming Chat Completions response to Responses format."""

    choices = response.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})
    output: list[dict[str, Any]] = []

    content = message.get("content")
    if isinstance(content, str) and content:
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

    for tool_call in message.get("tool_calls", []) or []:
        function = tool_call.get("function", {})
        output.append({
            "id": "fc_" + str(tool_call.get("id", "call")),
            "type": "function_call",
            "status": "completed",
            "call_id": tool_call.get("id", ""),
            "name": function.get("name", ""),
            "arguments": function.get("arguments", "{}"),
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

    elif finish_reason == "tool_calls":
        result["status"] = "completed"

    return result


def parse_json_object(raw: bytes) -> dict[str, Any]:
    """Parse JSON bytes and ensure the root value is an object."""

    value = json.loads(raw)

    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")

    return value


def parse_chat_sse_event(event_text: str) -> dict[str, Any] | None:
    """Parse one complete Server-Sent Events block from Chat Completions."""

    data_lines = []

    for line in event_text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if not data_lines:
        return None

    data = "\n".join(data_lines)

    if data.strip() == "[DONE]":
        return {"type": "done"}

    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return None

    if not isinstance(value, dict):
        return None

    choices = value.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return {
            "type": "metadata",
            "id": value.get("id"),
            "model": value.get("model"),
            "usage": value.get("usage"),
        }

    choice = choices[0]
    delta = choice.get("delta", {})

    result: dict[str, Any] = {
        "type": "delta",
        "id": value.get("id"),
        "model": value.get("model"),
        "content": delta.get("content"),
        "tool_calls": delta.get("tool_calls", []),
        "finish_reason": choice.get("finish_reason"),
    }

    return result
