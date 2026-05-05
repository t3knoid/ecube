from __future__ import annotations

import hashlib
import json
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
    seed_payload = json.dumps(effective_values, sort_keys=True, separators=(",", ":")).encode("utf-8")

    characters: list[str] = []
    for index in range(target_length):
        pool = pools[index % len(pools)]
        attempt = 0
        while True:
            digest = hashlib.sha256(seed_payload + f":{index}:{attempt}".encode("utf-8")).digest()
            candidate = pool[digest[0] % len(pool)]
            if not characters or candidate != characters[-1]:
                characters.append(candidate)
                break
            attempt += 1

    return "".join(characters)