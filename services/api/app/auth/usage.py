"""Who signed in and which briefs they generated. Two stores behind one
protocol: in memory for development and tests, Azure Table Storage for the
hosted app (reached with the managed identity, so no key in the app).

Rows hold a subject, an email, a brief id and a time. Never an address: the
brief id is a hash, and the address lives only inside the brief itself."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Protocol

USERS_TABLE = "users"
USAGE_TABLE = "usage"


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class UsageStore(Protocol):
    async def touch_user(self, subject: str, email: str) -> None: ...
    async def count_user_today(self, subject: str) -> int: ...
    async def count_global_today(self) -> int: ...
    async def record(self, subject: str | None, email: str | None, brief_id: str) -> None: ...


class MemoryUsageStore:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        # day -> list of (subject, brief_id)
        self.rows: dict[str, list[tuple[str | None, str]]] = defaultdict(list)

    async def touch_user(self, subject: str, email: str) -> None:
        row = self.users.setdefault(subject, {"email": email, "first_seen": _now_iso()})
        row["email"] = email
        row["last_seen"] = _now_iso()

    async def count_user_today(self, subject: str) -> int:
        return sum(1 for s, _ in self.rows[_today()] if s == subject)

    async def count_global_today(self) -> int:
        return len(self.rows[_today()])

    async def record(self, subject: str | None, email: str | None, brief_id: str) -> None:
        self.rows[_today()].append((subject, brief_id))


class TableUsageStore:
    """`users`: PartitionKey "user", RowKey = subject. `usage`: PartitionKey =
    UTC day, RowKey = "<time>-<brief id>". Counting a day is one partition
    query; the partitions are tiny (tens of rows)."""

    def __init__(self, account: str) -> None:
        if not account:
            raise RuntimeError("GRID_STORAGE_ACCOUNT is required with GRID_USAGE_STORE=table")
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        self._service = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        self._users = self._service.get_table_client(USERS_TABLE)
        self._usage = self._service.get_table_client(USAGE_TABLE)

    async def touch_user(self, subject: str, email: str) -> None:
        from azure.data.tables import UpdateMode

        def work() -> None:
            now = _now_iso()
            try:
                self._users.create_entity(
                    {
                        "PartitionKey": "user",
                        "RowKey": subject,
                        "email": email,
                        "first_seen": now,
                        "last_seen": now,
                    }
                )
            except Exception:  # noqa: BLE001  exists: merge the last_seen
                self._users.update_entity(
                    {"PartitionKey": "user", "RowKey": subject, "email": email, "last_seen": now},
                    mode=UpdateMode.MERGE,
                )

        await asyncio.to_thread(work)

    async def _count(self, extra_filter: str | None) -> int:
        day = _today()
        flt = f"PartitionKey eq '{day}'" + (f" and {extra_filter}" if extra_filter else "")

        def work() -> int:
            return sum(1 for _ in self._usage.query_entities(flt, select=["RowKey"]))

        return await asyncio.to_thread(work)

    async def count_user_today(self, subject: str) -> int:
        safe = subject.replace("'", "''")
        return await self._count(f"subject eq '{safe}'")

    async def count_global_today(self) -> int:
        return await self._count(None)

    async def record(self, subject: str | None, email: str | None, brief_id: str) -> None:
        def work() -> None:
            self._usage.create_entity(
                {
                    "PartitionKey": _today(),
                    "RowKey": f"{_now_iso()}-{brief_id}",
                    "subject": subject or "",
                    "email": email or "",
                    "brief_id": brief_id,
                }
            )

        await asyncio.to_thread(work)
