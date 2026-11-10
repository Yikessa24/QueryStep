"""Probe a configured model with synthetic text only, without logging secrets."""

import argparse
import json
import os
import re

import httpx

from api.catalog import Catalog, DEFAULT_CATALOG
from tutor.agent import TOOLS, TutorAction, TutorAgent
from tutor.provider import ChatModel


def choose_gemini(models: list[str]) -> str:
    candidates = []
    for model in models:
        lower = model.lower()
        version = re.search(r"(?:^|/)gemini-(\d+)(?:\.(\d+))?-(flash|pro)(?:-|$)", lower)
        if not version or any(part in lower for part in (
                "embedding", "image", "audio", "live", "tts", "deep-research")):
            continue
        candidates.append(((not any(part in lower for part in ("preview", "experimental", "-exp")),
                            version[3] == "flash", int(version[1]), int(version[2] or 0),
                            "lite" not in lower, model), model))
    if not candidates:
        raise ValueError("No supported Gemini text model was listed; set an available model explicitly.")
    return max(candidates)[1]


def probe(model: ChatModel, timeout: float) -> dict:
    basic = model.reply([{"role": "user", "content": "用一句简短中文解释 SQL 的 WHERE。"}], [], timeout)
    if not isinstance(basic.get("content"), str) or not basic["content"].strip():
        raise ValueError("The provider returned no chat text.")

    tool_name = "retrieve_course_notes"
    request = [{"role": "user", "content": "先调用课程规则工具。"}]
    called = model.reply(request, TOOLS, timeout,
                         tool_choice={"type": "function", "function": {"name": tool_name}})
    calls = called.get("tool_calls") or []
    if (len(calls) != 1 or calls[0].get("type") != "function" or not calls[0].get("id")
            or calls[0]["function"]["name"] != tool_name
            or json.loads(calls[0]["function"]["arguments"]) != {}):
        raise ValueError("The provider returned no valid OpenAI-compatible tool call.")

    schema_prompt = [{"role": "user", "content": (
        '返回一个 JSON 对象，例如 {"action":"ask_clarifying","text":"你想筛选哪一行？","source_ids":[]}。'
        "只输出这个 JSON 对象。"
    )}]
    response = model.reply(schema_prompt, [], timeout)
    TutorAction.from_content(response.get("content") or "")
    try:
        response = model.reply(schema_prompt, [], timeout, response_format={"type": "json_object"})
        TutorAction.from_content(response.get("content") or "")
        native_json = True
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        native_json = False

    tutor = TutorAgent(model, timeout=timeout)
    item = Catalog.load(DEFAULT_CATALOG).items[2]
    first_message = "我分不清严格小于和小于等于。请先查课程规则再引导我。"
    first = tutor.respond(item, first_message, [])
    second = tutor.respond(item, "请查阅独立例题，给我看一个不同的例子。",
                           [{"message": first_message, **first}])
    return {"model": model.model, "chat": True, "tool_calling": True,
            "prompt_json_validated": True, "native_json_mode": native_json,
            "tutor_rounds": [
                {key: turn[key] for key in ("source", "action", "trace", "fallback_reason")}
                for turn in (first, second)
            ]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()
    model = None
    try:
        model = ChatModel(os.environ["QUERYSTEP_LLM_BASE_URL"], "",
                          os.environ.get("QUERYSTEP_LLM_API_KEY"),
                          allow_insecure_http=os.environ.get("QUERYSTEP_LLM_ALLOW_INSECURE_HTTP") == "1")
        timeout = float(os.environ.get("QUERYSTEP_LLM_TIMEOUT_SECONDS", "5"))
        if not 0.1 <= timeout <= 30:
            raise ValueError("Invalid timeout.")
        available = model.list_models(timeout)
        if args.list_only:
            print(json.dumps(available, ensure_ascii=False, indent=2))
            return
        model.model = os.environ.get("QUERYSTEP_LLM_MODEL") or choose_gemini(available)
        if model.model not in available:
            raise ValueError("Configured model is absent from the provider model list.")
        report = probe(model, timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        rounds = report["tutor_rounds"]
        if (any(turn["source"] != "llm" or not turn["trace"] for turn in rounds)
                or rounds[0]["action"] == rounds[1]["action"]):
            raise SystemExit("Provider capabilities passed, but the two-turn tutor case did not.")
    except httpx.HTTPStatusError as error:
        raise SystemExit(f"Provider probe failed with HTTP {error.response.status_code}.") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise SystemExit(f"Provider probe failed ({type(error).__name__}); check URL, model and credentials.") from None
    finally:
        if model:
            model.close()


if __name__ == "__main__":
    main()
