from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class CategoryReport:
    category: str
    status: str  # ok | partial | failed | skipped
    items_ok: int = 0
    items_partial: int = 0
    items_failed: int = 0
    notes: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunReport:
    started_at: str
    finished_at: str | None = None
    backup_id: str = ""
    tool_version: str = ""
    schema_version: int | None = None
    categories: list[CategoryReport] = field(default_factory=list)

    def add(self, report: CategoryReport) -> CategoryReport:
        self.categories.append(report)
        return report

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "backup_id": self.backup_id,
            "tool_version": self.tool_version,
            "schema_version": self.schema_version,
            "categories": [c.to_dict() for c in self.categories],
            "overall": self.overall_status(),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def overall_status(self) -> str:
        if not self.categories:
            return "empty"
        statuses = {c.status for c in self.categories}
        if statuses <= {"ok", "skipped"}:
            return "ok" if "ok" in statuses else "skipped"
        if "failed" in statuses and "ok" not in statuses and "partial" not in statuses:
            return "failed"
        return "partial"
