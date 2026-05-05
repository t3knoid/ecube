from __future__ import annotations

import secrets
from typing import Mapping


WRITABLE_PASSWORD_POLICY_KEYS = (
    "minlen",
    "minclass",
    "maxrepeat",
    "maxsequence",
    "maxclassrepeat",
    "dictcheck",
    "usercheck",
    "difok",
    "retry",
)

DEFAULT_PASSWORD_POLICY_VALUES: dict[str, int] = {
    "minlen": 14,
    "minclass": 3,
    "maxrepeat": 3,
    "maxsequence": 4,
    "maxclassrepeat": 0,
    "dictcheck": 1,
    "usercheck": 1,
    "difok": 5,
    "retry": 3,
}

_LOWER_POOL = "bcdfghjkmnpqrstvwxyz"
_UPPER_POOL = "BCDFGHJKLMNPQRSTVWXYZ"
_DIGIT_POOL = "346789"
_SPECIAL_POOL = "@%+=_"


def parse_pwquality_value(raw_value: str) -> int | None:
    try:
        return int(raw_value.strip())
    except ValueError:
        return None


def parse_pwquality_policy_values(text: str) -> dict[str, int]:
    values = dict(DEFAULT_PASSWORD_POLICY_VALUES)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if key not in WRITABLE_PASSWORD_POLICY_KEYS:
            continue
        parsed = parse_pwquality_value(raw_value)
        if parsed is not None:
            values[key] = parsed
    return values


def build_policy_friendly_demo_password(policy_values: Mapping[str, int] | None = None) -> str:
    effective_values = dict(DEFAULT_PASSWORD_POLICY_VALUES)
    if policy_values:
        for key in WRITABLE_PASSWORD_POLICY_KEYS:
            if key in policy_values:
                effective_values[key] = int(policy_values[key])

    minlen = max(int(effective_values.get("minlen", DEFAULT_PASSWORD_POLICY_VALUES["minlen"])), 12)
    minclass = max(0, min(int(effective_values.get("minclass", DEFAULT_PASSWORD_POLICY_VALUES["minclass"])), 4))

    pools = [_LOWER_POOL, _UPPER_POOL, _DIGIT_POOL]
    if minclass >= 4:
        pools.append(_SPECIAL_POOL)

    target_length = max(minlen, 20)
    all_characters = "".join(pools)

    characters: list[str] = []
    for pool in pools:
        candidate = secrets.choice(pool)
        if characters and candidate == characters[-1]:
            choices = [char for char in pool if char != characters[-1]]
            if choices:
                candidate = secrets.choice(choices)
        characters.append(candidate)

    while len(characters) < target_length:
        candidate = secrets.choice(all_characters)
        if characters and candidate == characters[-1]:
            continue
        characters.append(candidate)

    for index in range(len(characters) - 1, 0, -1):
        swap_index = secrets.randbelow(index + 1)
        characters[index], characters[swap_index] = characters[swap_index], characters[index]

    for index in range(1, len(characters)):
        if characters[index] == characters[index - 1]:
            for swap_index in range(index + 1, len(characters)):
                if characters[swap_index] != characters[index - 1]:
                    characters[index], characters[swap_index] = characters[swap_index], characters[index]
                    break

    return "".join(characters)