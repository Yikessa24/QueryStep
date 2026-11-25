"""Context selection for the already-authorized history of one practice item."""

import re
from unicodedata import normalize


RECENT_TUTOR_TURNS = 5
MAX_TUTOR_TURNS = 8
_TURN_REFERENCE = re.compile(r"第\s*([0-9]{1,3}|[零〇一二两三四五六七八九十])\s*轮")
_CHINESE_TURN_NUMBERS = dict(zip("零一二三四五六七八九十", range(11))) | {"〇": 0, "两": 2}


def referenced_turn(message: str) -> int | None:
    """Recognize a direct reference to a single, one-based turn."""
    numbers = {
        int(value) if value.isascii() else _CHINESE_TURN_NUMBERS[value]
        for value in _TURN_REFERENCE.findall(normalize("NFKC", message))
    }
    return numbers.pop() if len(numbers) == 1 else None


def redact(text: str) -> str:
    return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)", "[已隐藏]", text)


def turn_messages(turn: dict, mapped_lesson_note: str | None) -> list[dict[str, str]]:
    answer = turn["text"]
    if mapped_lesson_note is not None and turn["source"] == "template":
        answer = mapped_lesson_note
    return [
        {"role": "user", "content": redact(turn["message"])},
        {"role": "assistant", "content": redact(answer)},
    ]


def recent_turns(prior: list[dict]) -> list[dict]:
    return prior[-RECENT_TUTOR_TURNS:]


def recall_turn(prior: list[dict], number: int, mapped_lesson_note: str | None) -> dict:
    turn = prior[number - 1]
    return {
        "id": f"history-turn-{number}",
        "title": f"本题第 {number} 轮对话",
        "turn_number": number,
        "has_example": turn.get("action") == "show_example",
        "text": turn_messages(turn, mapped_lesson_note),
    }
