"""Auth headers per side (PRD 0002): `Name: env:VAR`, values read from the environment at run time.

Literal values are rejected on purpose, so a secret can never be saved in a configuration or run file.
Only header names are recorded.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

API_USER_AGENT = "nParity/0.1 (https://github.com/oliviergerdi/aiskillsday)"
HEADER = re.compile(r"^\s*([A-Za-z0-9!#$%&'*+.^_`|~-]+)\s*:\s*env:([A-Za-z_][A-Za-z0-9_]*)\s*$")
FORM = "Use the form `Name: env:VAR`, e.g. `Authorization: env:OLD_TOKEN`. Literal header values are not allowed."


class HeaderError(ValueError):
    pass


def parse(spec: str) -> tuple[str, str]:
    m = HEADER.match(spec)
    if not m:
        raise HeaderError(f"Invalid header {spec.split(':', 1)[0].strip()!r}. {FORM}")
    return m.group(1), m.group(2)


def names(specs: list[str]) -> list[str]:
    return [parse(s)[0] for s in specs]


def resolve(specs: list[str], side: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Header name -> value. A missing or empty variable fails before any request, naming the variable."""
    env = os.environ if environ is None else environ
    out: dict[str, str] = {}
    for spec in specs:
        name, var = parse(spec)
        value = env.get(var, "")
        if not value.strip():
            raise HeaderError(f"Set {var} in the server environment for the {side} {name} header.")
        out[name] = value.strip()
    return out
