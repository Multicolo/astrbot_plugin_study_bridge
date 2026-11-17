"""SQLite 访问层：WAL、单写锁、按版本执行迁移。

关键设计：
- **单连接 + 单把 asyncio 锁**：所有读写串行化，避免 SQLite 的 ``database is locked``，
  同时保证「迁移要么全成功要么全回滚」。
- 所有阻塞调用走 ``asyncio.to_thread``，不阻塞事件循环。
- 迁移按 ``core/migrations/NNN_*.sql`` 文件名排序执行；任一语句失败 -> 回滚 + 抛
  ``MigrationError``，由调用方决定拒绝启动。
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

MIGRATION_RE = re.compile(r"^(\d+)_[A-Za-z0-9_\-]+\.sql$")


class MigrationError(RuntimeError):
    """迁移失败：调用方必须拒绝启动，不允许带着半迁移状态运行。"""


class Database:
    def __init__(self, path: str | Path, migrations_dir: str | Path | None = None) -> None:
        self.path = Path(path)
        default_dir = Path(__file__).resolve().parent / "migrations"
        self.migrations_dir = Path(migrations_dir) if migrations_dir else default_dir
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self.version = 0

    # ------------------------------------------------------------ 生命周期
    async def open(self, *, migrate: bool = True, target_version: int | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await asyncio.to_thread(self._connect)
        if migrate:
            await self.migrate(target_version=target_version)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await asyncio.to_thread(conn.close)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database 未打开")
        return self._conn

    # ------------------------------------------------------------ 迁移
    def pending_migrations(self, target_version: int | None = None) -> list[Path]:
        files: list[tuple[int, Path]] = []
        if not self.migrations_dir.is_dir():
            raise MigrationError(f"迁移目录不存在: {self.migrations_dir}")
        for item in sorted(self.migrations_dir.iterdir()):
            m = MIGRATION_RE.match(item.name)
            if not m:
                continue
            version = int(m.group(1))
            if target_version is not None and version > target_version:
                continue
            files.append((version, item))
        files.sort(key=lambda pair: pair[0])
        return [path for _, path in files]

    async def migrate(self, target_version: int | None = None) -> int:
        """执行所有未应用的迁移，返回最终 schema_version。失败抛 MigrationError。"""
        async with self._lock:
            current = await self._current_version()
            for path in self.pending_migrations(target_version):
                version = int(MIGRATION_RE.match(path.name).group(1))  # type: ignore[union-attr]
                if version <= current:
                    continue
                try:
                    await self._apply_migration(path, version)
                except Exception as exc:  # noqa: BLE001 - 统一转成 MigrationError
                    raise MigrationError(
                        f"迁移 {path.name} 失败，已回滚，拒绝启动：{exc}"
                    ) from exc
                current = version
            self.version = current
            return current

    async def _current_version(self) -> int:
        conn = self.conn
        exists = await asyncio.to_thread(
            conn.execute,
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'",
        )
        row = await asyncio.to_thread(exists.fetchone)
        if row is None:
            return 0
        cur = await asyncio.to_thread(
            conn.execute, "SELECT COALESCE(MAX(version), 0) AS v FROM schema_version"
        )
        row = await asyncio.to_thread(cur.fetchone)
        return int(row["v"]) if row else 0

    async def _apply_migration(self, path: Path, version: int) -> None:
        sql = path.read_text(encoding="utf-8")
        statements = [s.strip() for s in _split_statements(sql) if s.strip()]
        conn = self.conn
        await asyncio.to_thread(conn.execute, "BEGIN IMMEDIATE")
        try:
            for statement in statements:
                await asyncio.to_thread(conn.execute, statement)
            await asyncio.to_thread(
                conn.execute,
                "INSERT INTO schema_version (version, applied_at) VALUES (?, "
                "strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (version,),
            )
            await asyncio.to_thread(conn.execute, "COMMIT")
        except BaseException:
            await asyncio.to_thread(conn.execute, "ROLLBACK")
            raise

    # ------------------------------------------------------------ 查询
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
            return cur.rowcount

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> int:
        rows = [tuple(item) for item in seq]
        if not rows:
            return 0
        async with self._lock:
            cur = await asyncio.to_thread(self.conn.executemany, sql, rows)
            return cur.rowcount

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
            return int(cur.lastrowid or 0)

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        async with self._lock:
            cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
            rows = await asyncio.to_thread(cur.fetchall)
            return [dict(row) for row in rows]

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        async with self._lock:
            cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
            row = await asyncio.to_thread(cur.fetchone)
            return dict(row) if row else None

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = await self.fetch_one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Tx"]:
        """单写事务：期间独占写锁，任一步抛异常整体回滚。"""
        await self._lock.acquire()
        conn = self.conn
        try:
            await asyncio.to_thread(conn.execute, "BEGIN IMMEDIATE")
            yield Tx(conn)
            await asyncio.to_thread(conn.execute, "COMMIT")
        except BaseException:
            try:
                await asyncio.to_thread(conn.execute, "ROLLBACK")
            except Exception:  # pragma: no cover - 回滚失败时保留原始异常
                pass
            raise
        finally:
            self._lock.release()


class Tx:
    """事务内句柄：方法都是 async，但不会再去抢锁（外层已持有）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
        return cur.rowcount

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
        return int(cur.lastrowid or 0)

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
        rows = await asyncio.to_thread(cur.fetchall)
        return [dict(row) for row in rows]

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = await asyncio.to_thread(self.conn.execute, sql, _norm(params))
        row = await asyncio.to_thread(cur.fetchone)
        return dict(row) if row else None


def _norm(params: Sequence[Any] | dict[str, Any]) -> Any:
    """sqlite3 支持 dict（命名参数）与序列（位置参数）；这里不能一律 tuple() 化。"""
    return params if isinstance(params, dict) else tuple(params)


def _split_statements(sql: str) -> list[str]:
    """按分号切分 SQL。

    迁移脚本里不允许出现触发器/存储过程（需要 BEGIN...END 的语法），
    这样简单切分是安全的；注释行会被剔除。
    """
    cleaned: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).split(";")
