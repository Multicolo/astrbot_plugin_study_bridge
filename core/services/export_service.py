"""导出业务：全量 JSON（/export 与 GET /api/study/export 共用）。"""

from __future__ import annotations

from typing import Any

from ..principal import Principal
from ..util import iso, utcnow


class ExportService:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def dump(self, principal: Principal) -> dict[str, Any]:
        db = self.app.db
        pid = principal.id
        tasks = await db.fetch_all(
            "SELECT * FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "ORDER BY COALESCE(start_at, created_at) ASC",
            (pid,),
        )
        plans = await db.fetch_all(
            "SELECT * FROM plan WHERE owner_principal_id = ? ORDER BY created_at ASC", (pid,)
        )
        items = await db.fetch_all(
            "SELECT * FROM plan_item WHERE owner_principal_id = ? ORDER BY plan_id, seq", (pid,)
        )
        materials = await db.fetch_all(
            "SELECT * FROM material WHERE owner_principal_id = ? ORDER BY created_at ASC", (pid,)
        )
        notes = await db.fetch_all(
            "SELECT * FROM memory_note WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at ASC",
            (pid,),
        )
        mirrored = await db.fetch_all(
            "SELECT * FROM bot_memory_mirror WHERE owner_principal_id = ?", (pid,)
        )
        targets = await db.fetch_all(
            "SELECT id, umo, alias, enabled, created_at FROM push_target WHERE owner_principal_id = ?",
            (pid,),
        )
        settings = await db.fetch_all(
            "SELECT key, value, updated_at FROM setting WHERE owner_principal_id = ?", (pid,)
        )
        notifications = await db.fetch_all(
            "SELECT * FROM notification WHERE owner_principal_id = ? ORDER BY scheduled_at DESC LIMIT 500",
            (pid,),
        )
        return {
            "format": "study_bridge.export.v1",
            "generated_at": iso(utcnow()),
            "plugin_version": self.app.plugin_version,
            "principal": principal.to_dict(),
            "tasks": tasks,
            "plans": plans,
            "plan_items": items,
            "materials": materials,
            "memory_notes": notes,
            "bot_memory_mirror": mirrored,
            "push_targets": targets,
            "settings": settings,
            "notifications": notifications,
            "counts": {
                "tasks": len(tasks),
                "plans": len(plans),
                "materials": len(materials),
                "memory_notes": len(notes),
            },
        }
