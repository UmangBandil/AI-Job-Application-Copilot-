"""Browser action schema — the ONLY thing allowed to drive the browser.

The LLM (and any other planner) never executes anything directly: it may
at most propose actions, and only these Pydantic-validated, allow-listed
action types ever reach the extension. Anything else is rejected at the
backend boundary.

Values are length-capped and stripped of control characters. There is
deliberately NO action type that can execute JavaScript, navigate to
arbitrary URLs, or touch the filesystem — the extension executor also
enforces the same allow-list independently (defense in depth).
"""

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

# Control characters (except \n, \t) and zero-width chars are stripped.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]")


class ActionType(str, Enum):
    """The complete allow-list of browser actions."""

    FILL = "FILL"
    SELECT = "SELECT"
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"
    CLICK = "CLICK"
    SCROLL = "SCROLL"
    WAIT = "WAIT"
    EXTRACT = "EXTRACT"
    UPLOAD = "UPLOAD"
    NEXT_PAGE = "NEXT_PAGE"
    STOP = "STOP"


class BrowserAction(BaseModel):
    """One validated, sandboxed browser action."""

    action: ActionType
    field_id: str | None = None
    selector: str | None = None
    value: str | None = None
    option_value: str | None = None
    checked: bool | None = None
    pixels: int | None = Field(default=None, ge=-100000, le=100000)
    milliseconds: int | None = Field(default=None, ge=0, le=30000)

    @field_validator("field_id", "selector", "value", "option_value")
    @classmethod
    def _clean_string(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _CONTROL_CHARS.sub("", v)
        if len(v) > 5000:
            raise ValueError("value too long (max 5000 chars)")
        return v

    @field_validator("selector", "field_id")
    @classmethod
    def _selector_sane(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if "\n" in v or v.strip() == "":
            raise ValueError("invalid selector")
        return v

    model_config = {"extra": "forbid"}  # unknown fields -> validation error


class ActionPlan(BaseModel):
    """An ordered list of validated actions (what the extension may run)."""

    actions: list[BrowserAction] = Field(default_factory=list, max_length=200)

    @property
    def allowed_types(self) -> set[str]:
        return {a.action.value for a in self.actions}
