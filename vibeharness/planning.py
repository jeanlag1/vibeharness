"""Planning / TodoWrite-style tool.

Gives the model a stateful checklist for multi-step work. Empirically,
forcing the model to externalize and update a plan reduces "drift" on
long tasks.

State lives on the AgentPlan instance; the tool functions are bound to
one instance per Agent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pending", "in_progress", "done", "blocked"]
_VALID_STATUSES = {"pending", "in_progress", "done", "blocked"}


@dataclass
class PlanItem:
    id: str
    text: str
    status: Status = "pending"
    note: str = ""


@dataclass
class AgentPlan:
    items: list[PlanItem] = field(default_factory=list)
    last_updated: float = 0.0

    def set_plan(self, items: list[dict]) -> dict:
        """Replace the entire plan."""
        new = []
        for raw in items:
            if not isinstance(raw, dict):
                return {"error": "each item must be an object with id and text"}
            iid = str(raw.get("id") or "")
            text = str(raw.get("text") or "")
            if not iid or not text:
                return {"error": "each item needs non-empty 'id' and 'text'"}
            status = raw.get("status", "pending")
            if status not in _VALID_STATUSES:
                return {"error": f"invalid status '{status}'"}
            new.append(PlanItem(id=iid, text=text, status=status, note=str(raw.get("note", ""))))
        self.items = new
        self.last_updated = time.time()
        return self.snapshot()

    def update_item(self, id: str, status: str | None = None, note: str | None = None) -> dict:
        for it in self.items:
            if it.id == id:
                if status is not None:
                    if status not in _VALID_STATUSES:
                        return {"error": f"invalid status '{status}'"}
                    it.status = status  # type: ignore[assignment]
                if note is not None:
                    it.note = note
                self.last_updated = time.time()
                return self.snapshot()
        return {"error": f"no item with id '{id}'"}

    def get_plan(self) -> dict:
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "items": [
                {"id": i.id, "text": i.text, "status": i.status, "note": i.note}
                for i in self.items
            ],
            "summary": self._summary(),
        }

    def _summary(self) -> str:
        if not self.items:
            return "(empty plan)"
        counts = {s: sum(1 for i in self.items if i.status == s) for s in _VALID_STATUSES}
        return (
            f"{counts['done']} done, {counts['in_progress']} in_progress, "
            f"{counts['pending']} pending, {counts['blocked']} blocked"
        )


def make_plan_tools(plan: AgentPlan):
    """Return Tool definitions bound to the given AgentPlan instance."""
    from .tools import Tool

    return [
        Tool(
            name="set_plan",
            description=(
                "Replace your task plan with the given list of items. Use this at the start "
                "of a non-trivial task. Each item: {id, text, status?}. status defaults to "
                "'pending'. Keep ids short and stable (e.g. 'parse', 'tests')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "done", "blocked"],
                                },
                            },
                            "required": ["id", "text"],
                        },
                    }
                },
                "required": ["items"],
            },
            func=lambda **kw: plan.set_plan(**kw),
            mutating=False,
        ),
        Tool(
            name="update_plan_item",
            description=(
                "Update the status (and/or note) of a single plan item. Mark items "
                "in_progress before you start them and done as soon as they're complete."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "blocked"],
                    },
                    "note": {"type": "string"},
                },
                "required": ["id"],
            },
            func=lambda **kw: plan.update_item(**kw),
            mutating=False,
        ),
        Tool(
            name="get_plan",
            description="Return the current plan and a summary count.",
            input_schema={"type": "object", "properties": {}, "required": []},
            func=lambda **kw: plan.get_plan(),
            mutating=False,
        ),
    ]
