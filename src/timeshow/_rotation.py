"""Build saved display orders without maintaining separate seen/history lists."""

import secrets

def _shuffled(keys: set[str]) -> list[str]:
    order = sorted(keys)
    if len(order) > 1:
        secrets.SystemRandom().shuffle(order)
    return order


def _reconcile_order(state: dict, eligible: set[str], *, reshuffle: bool = False) -> tuple[list[str], int]:
    order = state.get("show_order", [])
    cursor = state.get("cursor", -1)
    prefix = [key for key in order[:cursor + 1] if key in eligible]
    if reshuffle:
        tail = _shuffled(eligible - set(prefix))
    else:
        tail = [key for key in order[cursor + 1:] if key in eligible]
        tail.extend(_shuffled(eligible - set(prefix) - set(tail)))
    return prefix + tail, len(prefix) - 1


def _next_cycle(order: list[str], eligible: set[str], last_shown: str | None) -> tuple[list[str], int]:
    if len(eligible) == 1 and order:
        return order, len(order) - 1
    tail = _shuffled(eligible)
    if len(tail) > 1 and tail[0] == last_shown:
        index = 1 + secrets.randbelow(len(tail) - 1)
        tail[0], tail[index] = tail[index], tail[0]
    return order + tail, len(order) - 1


def _migrate_order(state: dict, eligible: set[str]) -> None:
    if "show_order" not in state:
        history = state.get("history", [])
        cursor = state.get("cursor", -1)
        extra = sorted((set(state.get("seen", [])) - set(history)) & eligible)
        prefix = extra + [key for key in history[:cursor + 1] if key in eligible]
        tail = [key for key in history[cursor + 1:] if key in eligible]
        state["show_order"] = prefix + tail + _shuffled(eligible - set(prefix) - set(tail))
        state["cursor"] = len(prefix) - 1
    state.pop("seen", None)
    state.pop("history", None)
    state.pop("history_limit", None)
