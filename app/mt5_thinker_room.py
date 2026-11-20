import json
import time

import httpx

from app.config import get_env_value, load_config
from app.model_rotation import (
    select_next_model,
    record_request_result,
)


def _normalize_provider_name(name: str) -> str:
    name = str(name).strip().lower()

    aliases = {
        "nvidia_nim": "nvidia",
        "nvidia-nim": "nvidia",
        "tokenrouter": "token_router",
        "token-router": "token_router",
    }

    return aliases.get(name, name)


def _record_result(
    model_key: str,
    input_chars: int,
    success: bool,
    output_chars: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    record_request_result(
        model_key=model_key,
        input_chars=input_chars,
        output_chars=output_chars,
        success=success,
        ends_model_test=not success,
        error_type=error_type,
        error_message=error_message,
        consumer_id="mt5",
    )


def consult_mt5(
    inquiry: dict,
    select_result: dict | None = None,
) -> dict:

    question = inquiry["question"].strip()

    prompt = question

    if select_result is not None:
        data_text = json.dumps(
            select_result,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        prompt = (
            f"{question}\n\n"
            "SQLite data:\n"
            f"{data_text}"
        )

    input_chars = len(prompt)

    while True:

        selected_model = select_next_model("mt5")

        if selected_model is None:
            time.sleep(1)
            continue

        provider_name = _normalize_provider_name(
            selected_model.get("provider", "")
        )

        model_id = str(selected_model.get("id", ""))

        model_key = str(
            selected_model.get("key")
            or f"{provider_name}:{model_id}"
        )

        try:
            config = load_config()
            providers = config.get("providers", {})

            provider = next(
                (
                    value
                    for name, value in providers.items()
                    if _normalize_provider_name(name)
                    == provider_name
                ),
                {},
            )

            base_url = str(
                provider.get("base_url", "")
            ).rstrip("/")

            key_name = provider.get("api_key_env", "")
            api_key = (
                get_env_value(key_name)
                if key_name
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

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            request_body = {
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "stream": False,
            }

            response = httpx.post(
                f"{base_url}/chat/completions",
                json=request_body,
                headers=headers,
                timeout=httpx.Timeout(
                    180.0,
                    connect=15.0,
                ),
            )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Provider HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )

            provider_payload = response.json()

            choices = provider_payload.get("choices")

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

            answer = message.get("content")

            if not isinstance(answer, str):
                raise ValueError(
                    "Provider response content is not text."
                )

            output_chars = len(answer)

            _record_result(
                model_key=model_key,
                input_chars=input_chars,
                success=True,
                output_chars=output_chars,
            )

            return {
                "success": True,
                "model_key": model_key,
                "answer": answer,
            }

        except Exception as exc:

            try:
                _record_result(
                    model_key=model_key,
                    input_chars=input_chars,
                    success=False,
                    error_type="mt5_provider_error",
                    error_message=str(exc)[:500],
                )
            except Exception:
                pass

            time.sleep(0)
