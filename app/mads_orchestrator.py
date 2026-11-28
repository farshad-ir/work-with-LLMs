import json
import time
from datetime import datetime, timezone

import httpx

from app.config import get_env_value, load_config
from app.model_rotation import (
    select_next_model,
    record_request_result,
)
from app.mt5_sqlite import _connect
from app.LLM_SELQ import run_llm_selq


MAX_DEBATE_TURNS = 50
MAX_TOOL_CALLS_PER_TURN = 10
CONSUMER_ID = "mt5"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_provider_name(name):
    name = str(name).strip().lower()

    aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }

    return aliases.get(name, name)


# ============================================================
# Debate database
# ============================================================

def _append_debate(
    role,
    event_type,
    content,
    tool_call_id=None,
):
    if not isinstance(content, str):
        content = _json(content)

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM Debate
            """
        ).fetchone()

        sequence = row["next_sequence"]

        conn.execute(
            """
            INSERT INTO Debate (
                sequence,
                role,
                event_type,
                tool_call_id,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                role,
                event_type,
                tool_call_id,
                content,
                _now(),
            ),
        )

        conn.commit()
        return sequence

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def _load_debate():
    conn = _connect()

    try:
        rows = conn.execute(
            """
            SELECT
                sequence,
                role,
                event_type,
                tool_call_id,
                content,
                created_at
            FROM Debate
            ORDER BY sequence ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()
        
def _insert_final_opinion(reference_h1_id, final_result):
    if reference_h1_id is None:
        raise ValueError(
            "Cannot save Opinion: reference_h1_id is missing."
        )

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        cursor = conn.execute(
            """
            INSERT INTO Opinions (
                created_at,
                symbol,
                timeframe,
                candle_reference,
                opinion
            )
            SELECT
                ?,
                symbol,
                'H1',
                CAST(id AS TEXT),
                ?
            FROM h1Candles
            WHERE id = ?
            """,
            (
                _now(),
                final_result,
                reference_h1_id,
            ),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                f"H1 candle not found: {reference_h1_id}"
            )

        opinion_id = cursor.lastrowid
        conn.commit()

        return opinion_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
        
def _build_debate_report():
    events = _load_debate()

    lines = [
        "# MADS Debate Report",
        "",
        "## Debate",
        "",
    ]

    final_result = None

    for event in events:
        role = str(event["role"]).upper()
        event_type = str(event["event_type"]).upper()
        content = event["content"]

        if role not in ("BUYER", "SELLER", "CRITIC"):
            continue

        if event_type == "MESSAGE":
            lines.extend([
                f"### {role}",
                "",
                str(content),
                "",
            ])

        elif event_type == "FINAL_RESULT":
            final_result = str(content)

    lines.extend([
        "## FINAL RESULT",
        "",
        final_result or "No final result was recorded.",
        "",
    ])

    return "\n".join(lines).strip()

def _load_role_instructions(role):
    conn = _connect()

    try:
        rows = conn.execute(
            """
            SELECT prompt, trigger
            FROM Human_Intervention
            WHERE enabled = 1
              AND UPPER(COALESCE(role, '')) = ?
            ORDER BY id ASC
            """,
            (role.upper(),),
        ).fetchall()

        instructions = []

        for row in rows:
            prompt = str(row["prompt"] or "").strip()
            trigger = str(row["trigger"] or "").strip()

            if not prompt:
                continue

            item = prompt

            if trigger:
                item += "\n\nAdditional guidance:\n" + trigger

            instructions.append(item)

        return instructions

    finally:
        conn.close()


def _build_transcript():
    events = _load_debate()

    lines = []

    for event in events:
        sequence = event["sequence"]
        role = event["role"]
        event_type = event["event_type"]
        content = event["content"]

        line = (
            f"[{sequence}] "
            f"{role} / {event_type}: "
            f"{content}"
        )

        if event["tool_call_id"]:
            line += (
                f" [tool_call_id="
                f"{event['tool_call_id']}]"
            )

        lines.append(line)

    return "\n\n".join(lines)


# ============================================================
# Role prompts
# ============================================================

def _build_system_prompt(role, instruction=None):
    role = role.upper()

    instructions = _load_role_instructions(role)

    if not instructions:
        raise RuntimeError(
            f"No enabled Human_Intervention prompt found "
            f"for role {role}."
        )

    prompt = (
        f"You are acting as {role} in the "
        "MT5 Adversarial Deliberation System (MADS).\n\n"
        "Use the shared knowledge and the complete debate "
        "history provided to you.\n"
        "You may also use your general knowledge and reasoning. "
        "Distinguish market data from assumptions and general "
        "knowledge.\n\n"
        "Your role-specific instructions are:\n\n"
        + "\n\n---\n\n".join(instructions)
    )

    if instruction:
        prompt += (
            "\n\nInstruction from the debate controller:\n"
            f"{instruction}"
        )

    if role == "CRITIC":
        prompt += (
            "\n\nCONTROL REQUIREMENT:\n"
            "After evaluating the debate, you MUST call "
            "MADS-CONTROL to choose the next role or finish "
            "the debate.\n"
            "Do not choose the next role only in ordinary text.\n"
            "Use the instruction field to tell the next role "
            "what to do. You may specify how many H1 candles "
            "the role should request through LLM-SELQ.\n"
            "Use FINISH when the debate has reached a sufficient "
            "conclusion."
        )

    else:
        prompt += (
            "\n\nDATA REQUIREMENT:\n"
            "You may request market data using LLM-SELQ.\n"
            "Choose the number of recent H1 candles needed "
            "for your analysis.\n"
            "After receiving the tool result, continue your "
            "analysis using both the returned data and your "
            "general knowledge.\n"
            "When your analysis is complete, provide your "
            "conclusion in ordinary text."
        )

    return prompt


# ============================================================
# Tool definitions
# ============================================================

LLM_SELQ_TOOL = {
    "type": "function",
    "function": {
        "name": "LLM-SELQ",
        "description": (
            "Read recent H1 candles and the related H6 candles "
            "and successfully mapped SmallBoxes from SQLite. "
            "The limit is the number of recent H1 candles."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Number of recent H1 candles to retrieve."
                    ),
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
    },
}


MADS_CONTROL_TOOL = {
    "type": "function",
    "function": {
        "name": "MADS-CONTROL",
        "description": (
            "CRITIC only: choose the next role or finish "
            "the MADS debate. When choosing a role, provide "
            "clear instructions for that role."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["SPEAK", "FINISH"],
                },
                "next_role": {
                    "type": "string",
                    "enum": [
                        "BUYER",
                        "SELLER",
                        "CRITIC",
                        "NONE",
                    ],
                },
                "instruction": {
                    "type": "string",
                    "description": (
                        "Instructions for the next role. "
                        "May specify the number of H1 candles "
                        "it should request using LLM-SELQ."
                    ),
                },
                "reason": {
                    "type": "string",
                },
                "final_result": {
                    "type": "string",
                    "description": (
                        "Final conclusion when action is FINISH."
                    ),
                },
            },
            "required": [
                "action",
                "next_role",
                "instruction",
                "reason",
                "final_result",
            ],
            "additionalProperties": False,
        },
    },
}


# ============================================================
# Model rotation and provider call
# ============================================================

def _record_model_result(
    model_key,
    input_chars,
    output_chars=0,
    success=True,
    error_message=None,
):
    return record_request_result(
        model_key=model_key,
        input_chars=input_chars,
        output_chars=output_chars,
        success=success,
        ends_model_test=not success,
        error_type=(
            None if success else "mads_provider_error"
        ),
        error_message=error_message,
        consumer_id=CONSUMER_ID,
    )


def _get_provider_config(provider_name):
    config = load_config()
    providers = config.get("providers", {})

    for name, provider in providers.items():
        if (
            _normalize_provider_name(name)
            == provider_name
        ):
            return provider

    raise ValueError(
        f"Provider configuration not found: {provider_name}"
    )


def _call_model(messages, tools):
    while True:
        selected_model = select_next_model(CONSUMER_ID)

        if selected_model is None:
            raise RuntimeError(
                "No model is currently available for MADS."
            )

        provider_name = _normalize_provider_name(
            selected_model.get("provider", "")
        )

        model_id = str(selected_model.get("id", ""))

        model_key = str(
            selected_model.get("key")
            or f"{provider_name}:{model_id}"
        )

        request_body = {
            "model": model_id,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }

        input_chars = len(_json(request_body))

        try:
            provider = _get_provider_config(provider_name)

            base_url = str(
                provider.get("base_url", "")
            ).rstrip("/")

            api_key_name = provider.get("api_key_env", "")

            api_key = (
                get_env_value(api_key_name)
                if api_key_name
                else ""
            )

            if (
                not provider.get("enabled", False)
                or not base_url
                or not api_key
                or not model_id
            ):
                raise ValueError(
                    f"Provider '{provider_name}' "
                    "is disabled or not configured."
                )

            response = httpx.post(
                f"{base_url}/chat/completions",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(
                    180.0,
                    connect=15.0,
                ),
            )

            response.raise_for_status()

            payload = response.json()
            choices = payload.get("choices")

            if (
                not isinstance(choices, list)
                or not choices
                or not isinstance(choices[0], dict)
            ):
                raise ValueError(
                    "Invalid Chat Completions response."
                )

            message = choices[0].get("message")

            if not isinstance(message, dict):
                raise ValueError(
                    "Provider response has no message."
                )

            output_chars = len(_json(message))

            _record_model_result(
                model_key=model_key,
                input_chars=input_chars,
                output_chars=output_chars,
                success=True,
            )

            return message

        except Exception as exc:
            _record_model_result(
                model_key=model_key,
                input_chars=input_chars,
                success=False,
                error_message=str(exc)[:500],
            )

            time.sleep(1)


# ============================================================
# LLM-SELQ result summary
# ============================================================

def _summarize_selq(result):
    data = result.get("llm_selq", {})

    return {
        "requested_h1_count": data.get(
            "requested_h1_count", 0
        ),
        "h1_count": len(data.get("h1_candles", [])),
        "h6_count": len(data.get("h6_candles", [])),
        "small_box_count": len(data.get("small_boxes", [])),
    }


# ============================================================
# CRITIC control
# ============================================================

def _process_control(role, tool_call_id, arguments):
    if role != "CRITIC":
        raise ValueError(
            "MADS-CONTROL is available only to CRITIC."
        )

    action = str(
        arguments.get("action", "")
    ).upper()

    next_role = str(
        arguments.get("next_role", "")
    ).upper()

    instruction = str(
        arguments.get("instruction", "")
    ).strip()

    reason = str(
        arguments.get("reason", "")
    ).strip()

    final_result = str(
        arguments.get("final_result", "")
    ).strip()

    if action == "SPEAK":
        if next_role not in (
            "BUYER",
            "SELLER",
            "CRITIC",
        ):
            raise ValueError(
                "Invalid next_role for SPEAK."
            )

        request_content = {
            "name": "MADS-CONTROL",
            "arguments": arguments,
        }

        _append_debate(
            role="CRITIC",
            event_type="TOOL_REQUEST",
            content=request_content,
            tool_call_id=tool_call_id,
        )

        control_result = {
            "accepted": True,
            "action": "SPEAK",
            "next_role": next_role,
            "reason": reason,
        }

        _append_debate(
            role="CRITIC",
            event_type="TOOL_RESULT",
            content=control_result,
            tool_call_id=tool_call_id,
        )

        direction = (
            f"CRITIC selected {next_role} as the next role.\n"
            f"Reason: {reason}\n"
            f"Instructions: {instruction}"
        )

        _append_debate(
            role="SYSTEM",
            event_type="MESSAGE",
            content=direction,
        )

        return next_role

    if action == "FINISH":
        if next_role != "NONE":
            raise ValueError(
                "next_role must be NONE when action is FINISH."
            )

        if not final_result:
            raise ValueError(
                "CRITIC must provide final_result."
            )

        _append_debate(
            role="CRITIC",
            event_type="TOOL_REQUEST",
            content={
                "name": "MADS-CONTROL",
                "arguments": arguments,
            },
            tool_call_id=tool_call_id,
        )
        
        if reference_h1_id is None:
            raise ValueError(
                "Cannot finish debate without an H1 reference."
            )
        
        _append_debate(
            role="CRITIC",
            event_type="TOOL_RESULT",
            content={
                "accepted": True,
                "action": "FINISH",
                "reason": reason,
            },
            tool_call_id=tool_call_id,
        )

        _append_debate(
            role="CRITIC",
            event_type="FINAL_RESULT",
            content=final_result,
        )

        return None

    raise ValueError(
        f"Unsupported MADS-CONTROL action: {action}"
    )


# ============================================================
# One role turn
# ============================================================

def _run_role_turn(role, instruction=None, debate_context=None):
    role = role.upper()

    system_prompt = _build_system_prompt(
        role,
        instruction=instruction,
    )

    transcript = _build_transcript()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": (
                "Current MADS debate history:\n\n"
                + transcript
            ),
        },
    ]

    tools = [LLM_SELQ_TOOL]

    if role == "CRITIC":
        tools.append(MADS_CONTROL_TOOL)

    tool_call_count = 0

    while True:
        assistant_message = _call_model(
            messages=messages,
            tools=tools,
        )

        content = assistant_message.get("content")
        tool_calls = assistant_message.get("tool_calls") or []
        
        if role == "CRITIC":
            control_calls = [
                call
                for call in tool_calls
                if call.get("function", {}).get("name")
                == "MADS-CONTROL"
            ]

            if control_calls and len(tool_calls) != 1:
                raise RuntimeError(
                    "CRITIC must call MADS-CONTROL alone, "
                    "without other tool calls in the same response."
                )
                

        if content:
            _append_debate(
                role=role,
                event_type="MESSAGE",
                content=str(content),
            )

        if not tool_calls:
            if role == "CRITIC":
                raise RuntimeError(
                    "CRITIC did not call MADS-CONTROL. "
                    "The debate cannot continue safely."
                )

            if not content:
                raise RuntimeError(
                    f"{role} returned neither text nor tool calls."
                )

            # After BUYER or SELLER finishes,
            # CRITIC is automatically activated again.
            return "CRITIC"

        messages.append(assistant_message)

        for tool_call in tool_calls:
            tool_call_count += 1

            if tool_call_count > MAX_TOOL_CALLS_PER_TURN:
                raise RuntimeError(
                    f"{role} exceeded the tool-call limit."
                )

            tool_call_id = str(
                tool_call.get("id", "")
            )

            function = tool_call.get("function", {})
            tool_name = str(
                function.get("name", "")
            )

            raw_arguments = function.get("arguments", "{}")

            try:
                if isinstance(raw_arguments, str):
                    arguments = json.loads(raw_arguments)
                else:
                    arguments = raw_arguments

                if not isinstance(arguments, dict):
                    raise ValueError(
                        "Tool arguments must be a JSON object."
                    )

            except Exception as exc:
                error_result = {
                    "success": False,
                    "error": str(exc),
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _json(error_result),
                })

                continue

            if tool_name == "LLM-SELQ":
                limit = arguments.get("limit")

                if (
                    isinstance(limit, bool)
                    or not isinstance(limit, int)
                    or limit < 1
                ):
                    result = {
                        "success": False,
                        "error": (
                            "LLM-SELQ limit must be "
                            "a positive integer."
                        ),
                    }

                    _append_debate(
                        role=role,
                        event_type="TOOL_REQUEST",
                        content={
                            "name": tool_name,
                            "arguments": arguments,
                        },
                        tool_call_id=tool_call_id,
                    )

                    _append_debate(
                        role=role,
                        event_type="TOOL_RESULT",
                        content=result,
                        tool_call_id=tool_call_id,
                    )

                else:
                    _append_debate(
                        role=role,
                        event_type="TOOL_REQUEST",
                        content={
                            "name": tool_name,
                            "arguments": arguments,
                        },
                        tool_call_id=tool_call_id,
                    )

                    try:
                        result = run_llm_selq(limit)
                        
                        reference_h1_id = result.get(
                            "llm_selq", {}
                        ).get("reference_h1_id")

                        if reference_h1_id is not None:
                            debate_context["reference_h1_id"] = (
                                reference_h1_id
                            )

                        summary = _summarize_selq(result)

                        _append_debate(
                            role=role,
                            event_type="TOOL_RESULT",
                            content=summary,
                            tool_call_id=tool_call_id,
                        )

                    except Exception as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                        }

                        _append_debate(
                            role=role,
                            event_type="TOOL_RESULT",
                            content=result,
                            tool_call_id=tool_call_id,
                        )

                # Full data goes only to the requesting role.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _json(result),
                })

            elif tool_name == "MADS-CONTROL":
                def _process_control(
                    role,
                    tool_call_id,
                    arguments,
                    reference_h1_id=None,
                ):

                if arguments.get("action", "").upper() == "FINISH":
                    return None

                return str(
                    arguments.get("next_role", "")
                ).upper()

            else:
                result = {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _json(result),
                })


# ============================================================
# MADS Orchestrator
# ============================================================

def run_mads_debate(max_turns=MAX_DEBATE_TURNS):
    if (
        isinstance(max_turns, bool)
        or not isinstance(max_turns, int)
        or max_turns < 1
    ):
        raise ValueError(
            "max_turns must be a positive integer."
        )

    # The debate table must already have been created
    # and populated by the MT5 CHART-INIT operations.

    _append_debate(
        role="SYSTEM",
        event_type="MESSAGE",
        content=(
            "MADS orchestration started. "
            "CRITIC is activated first. "
            "CRITIC must choose the next role using MADS-CONTROL."
        ),
    )

    current_role = "CRITIC"
    instruction = (
        "You are activated first. Review the shared knowledge "
        "and begin the debate by choosing the next role."
    )

    for turn in range(1, max_turns + 1):
        next_role = _run_role_turn(
            role=current_role,
            instruction=instruction,
        )

        if next_role is None:
            return {
                "success": True,
                "turns": turn,
                "status": "FINISHED",
                "debate_report": _build_debate_report(),
            }

        current_role = next_role
        instruction = None

    _append_debate(
        role="SYSTEM",
        event_type="MESSAGE",
        content=(
            f"MADS stopped after reaching "
            f"the maximum of {max_turns} turns."
        ),
    )

    raise RuntimeError(
        f"MADS reached the maximum turn limit: {max_turns}."
    )
