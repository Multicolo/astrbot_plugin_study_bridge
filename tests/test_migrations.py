"""迁移：空库建表、旧库升级、失败拒绝启动、并发写不报 locked。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from core.db import Database, MigrationError

pytestmark = pytest.mark.asyncio

MIGRATIONS = Path(__file__).resolve().parent.parent / "core" / "migrations"


async def test_fresh_database(tmp_path):
    db = Database(tmp_path / "study.db")
    await db.open()
    try:
        assert db.version == 2
        tables = {
            row["name"]
            for row in await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for expected in (
            "task",
            "plan",
            "plan_item",
            "notification",
            "push_target",
            "memory_note",
            "memory_sync",
            "sync_outbox",
            "chat_session",
            "chat_message",
            "ai_action_log",
            "command_log",
            "usage_counter",
        ):
            assert expected in tables
        mode = await db.scalar("PRAGMA journal_mode", default="")
        assert str(mode).lower() == "wal"
    finally:
        await db.close()


async def test_upgrade_from_v1(tmp_path):
    path = tmp_path / "study.db"
    db = Database(path)
    await db.open(target_version=1)
    assert db.version == 1
    await db.close()

    db2 = Database(path)
    await db2.open()
    try:
        assert db2.version == 2
        rows = await db2.fetch_all("SELECT version FROM schema_version ORDER BY version")
        assert [row["version"] for row in rows] == [1, 2]
        indexes = {
            row["name"]
            for row in await db2.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_ai_action_created" in indexes
    finally:
        await db2.close()


async def test_failed_migration_refuses_to_start(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    shutil.copy(MIGRATIONS / "001_init.sql", migrations / "001_init.sql")
    (migrations / "002_broken.sql").write_text(
        "CREATE TABLE ok_table (id TEXT);\nCREATE TABLE broken_table (", encoding="utf-8"
    )
    db = Database(tmp_path / "study.db", migrations_dir=migrations)
    with pytest.raises(MigrationError) as exc:
        await db.open()
    assert "拒绝启动" in str(exc.value)
    # 不留半迁移状态：schema_version 只到 1，坏表不存在
    await db.close()
    check = Database(tmp_path / "study.db", migrations_dir=migrations)
    await check.open(target_version=1)
    try:
        assert check.version == 1
        tables = {
            row["name"]
            for row in await check.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "broken_table" not in tables
        assert "ok_table" not in tables  # 同一迁移里的前一条语句也回滚了
    finally:
        await check.close()


async def test_concurrent_writes_do_not_lock(tmp_path):
    db = Database(tmp_path / "study.db")
    await db.open()
    try:

        async def writer(index: int) -> None:
            await db.execute(
                "INSERT INTO usage_counter (owner_principal_id, kind, day, count) "
                "VALUES (?, 'test', '2026-11-17', 1)",
                (f"p{index}",),
            )

        await asyncio.gather(*[writer(i) for i in range(30)])
        total = await db.scalar("SELECT COUNT(*) FROM usage_counter")
        assert total == 30
    finally:
        await db.close()


async def test_transaction_rolls_back(tmp_path):
    db = Database(tmp_path / "study.db")
    await db.open()
    try:
        with pytest.raises(RuntimeError):
            async with db.transaction() as tx:
                await tx.execute(
                    "INSERT INTO usage_counter (owner_principal_id, kind, day, count) "
                    "VALUES ('t', 'x', '2026-11-17', 1)"
                )
                raise RuntimeError("boom")
        assert await db.scalar("SELECT COUNT(*) FROM usage_counter") == 0
    finally:
        await db.close()
