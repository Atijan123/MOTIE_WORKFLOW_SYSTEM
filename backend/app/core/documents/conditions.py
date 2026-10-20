"""The small condition language used by document requirements.

A condition is JSON: {"field": "hs_heading", "op": "equals", "value": "2523"}.
It is tested against the case's facts (a dict the module supplies, see facts.py).
Text is compared ignoring case and surrounding spaces. Nothing is ever eval()-ed:
only the two operators below exist, and the database refuses any other shape.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _text(value: Any) -> str:
    return str(value).strip().casefold()


OPERATORS = {
    "equals": lambda actual, expected: _text(actual) == _text(expected),
    "contains": lambda actual, expected: _text(expected) in _text(actual),
}


def holds(condition: dict[str, Any] | None, facts: dict[str, Any]) -> bool | None:
    """Does this requirement apply to a case with these facts?

    True or False, or None for "not known yet": the module supplies the fact,
    but it has no value yet (e.g. no HS code until an officer enters one).
    """
    if condition is None:
        return True
    field = condition["field"]
    if field not in facts:
        # A rule naming a fact the module doesn't supply is a set-up mistake.
        # Fail closed: require the document, and say so in the server log.
        logger.warning("Document condition uses unknown fact %r; treating it as required", field)
        return True
    if facts[field] is None:
        return None
    return OPERATORS[condition["op"]](facts[field], condition["value"])
