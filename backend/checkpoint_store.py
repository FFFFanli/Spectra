import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from backend.app_paths import CHECKPOINT_DB_PATH, ensure_directories

_saver: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None


async def init_checkpoint_store() -> None:
    global _saver, _conn
    ensure_directories()
    _conn = await aiosqlite.connect(str(CHECKPOINT_DB_PATH))
    _saver = AsyncSqliteSaver(conn=_conn)
    await _saver.setup()


def get_checkpointer() -> AsyncSqliteSaver:
    if _saver is None:
        raise RuntimeError(
            "Checkpoint store not initialized. Call init_checkpoint_store() at startup."
        )
    return _saver


async def close_checkpoint_store() -> None:
    global _saver, _conn
    if _conn is not None:
        await _conn.close()
        _saver = None
        _conn = None
