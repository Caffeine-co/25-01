import aiosqlite
import json
from src.plugins.living.config import chat_cfg
from src.plugins.living.utils import delete_temp_image


async def init_session_info_db() -> None:
    async with aiosqlite.connect(chat_cfg["session_info_db_path"]) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_info (
                group_id INTEGER PRIMARY KEY,
                group_name TEXT,
                member_count INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS friend_info (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT
            )
            """
        )
        await db.commit()

async def get_group_info(group_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["session_info_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                group_name,
                member_count
            FROM group_info
            WHERE group_id = ?
            """,
            (group_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_friend_info(user_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["session_info_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT nickname
            FROM friend_info
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def update_group_info(group_id: int, group_name: str, member_count: int) -> None:
    async with aiosqlite.connect(chat_cfg["session_info_db_path"]) as db:
        await db.execute(
            """
            INSERT INTO group_info (
                group_id,
                group_name,
                member_count
            )
            VALUES (?, ?, ?)
            ON CONFLICT(group_id)
            DO UPDATE SET
                group_name = excluded.group_name,
                member_count = excluded.member_count
            """,
            (
                group_id,
                group_name,
                member_count
            )
        )
        await db.commit()

async def update_friend_info(user_id: int, nickname: str) -> None:
    async with aiosqlite.connect(chat_cfg["session_info_db_path"]) as db:
        await db.execute(
            """
            INSERT INTO friend_info (
                user_id,
                nickname
            )
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET nickname = excluded.nickname
            """,
            (
                user_id,
                nickname
            )
        )
        await db.commit()

async def init_group_msg_table(db: aiosqlite.Connection, group_id: int) -> None:
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS group_{group_id} (
            id INTEGER PRIMARY KEY,
            time INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            nickname TEXT,
            content TEXT,
            image_data TEXT,
            from_me INTEGER DEFAULT 0,
            read_state INTEGER DEFAULT 0
        )
        """
    )

async def init_friend_msg_table(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_{user_id} (
            id INTEGER PRIMARY KEY,
            time INTEGER,
            message_id INTEGER,
            content TEXT,
            image_data TEXT,
            from_me INTEGER DEFAULT 0,
            read_state INTEGER DEFAULT 0
        )
        """
    )

async def cleanup_msg(db: aiosqlite.Connection, table_name: str) -> None:
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        f"""
        SELECT id, image_data
        FROM {table_name}
        WHERE id NOT IN (
            SELECT id
            FROM {table_name}
            ORDER BY id DESC
            LIMIT ?
        )
        """,
        (chat_cfg["max_msg_reserve_num"],)
    )
    rows = await cursor.fetchall()
    if not rows:
        return
    for row in rows:
        image_data = json.loads(row["image_data"])
        for image in image_data:
            await delete_temp_image(image)
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    await db.execute(
        f"""
        DELETE FROM {table_name}
        WHERE id IN ({placeholders})
        """,
        ids
    )

async def record_received_group_msg(group_id: int, message: dict) -> None:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        await init_group_msg_table(db, group_id)
        await db.execute(
            f"""
            INSERT INTO group_{group_id} (
                time,
                message_id,
                user_id,
                nickname,
                content,
                image_data
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message["time"],
                message["message_id"],
                message["user_id"],
                message["nickname"],
                message["content"],
                message["image_data"]
            )
        )
        await cleanup_msg(db, f"group_{group_id}")
        await db.commit()

async def record_received_friend_msg(user_id: int, message: dict) -> None:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        await init_friend_msg_table(db, user_id)
        await db.execute(
            f"""
            INSERT INTO user_{user_id} (
                time,
                message_id,
                content,
                image_data
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                message["time"],
                message["message_id"],
                message["content"],
                message["image_data"]
            )
        )
        await cleanup_msg(db, f"user_{user_id}")
        await db.commit()

async def record_self_msg(session: dict, message: dict) -> None:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        match session["type"]:
            case "group":
                await init_group_msg_table(db, session["id"])
                table_type = "group"
            case _:
                await init_friend_msg_table(db, session["id"])
                table_type = "user"
        await db.execute(
            f"""
            INSERT INTO {table_type}_{session["id"]} (
                time,
                message_id,
                content,
                image_data,
                from_me,
                read_state
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message["time"],
                message["message_id"],
                message["content"],
                message["image_data"],
                1,
                1
            )
        )
        await cleanup_msg(db, f"{table_type}_{session["id"]}")
        await db.commit()

async def get_group_msg_list(group_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        await init_group_msg_table(db, group_id)
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                user_id,
                nickname,
                content,
                image_data,
                from_me,
                read_state
            FROM group_{group_id}
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_cfg["max_msg_provide_num"],)
        )
        rows = await cursor.fetchall()
        rows = reversed(rows)
        msg_list = [dict(row)for row in rows]
        read_msg = []
        unread_msg = []
        for msg in msg_list:
            match msg["read_state"]:
                case 0:
                    unread_msg.append(msg)
                case 1:
                    read_msg.append(msg)
        return {
            "read_msg": read_msg,
            "unread_msg": unread_msg
        }

async def get_friend_msg_list(user_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        await init_friend_msg_table(db, user_id)
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                content,
                image_data,
                from_me,
                read_state
            FROM user_{user_id}
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_cfg["max_msg_provide_num"],),
        )
        rows = await cursor.fetchall()
        rows = reversed(rows)
        msg_list = [dict(row) for row in rows]
        read_msg = []
        unread_msg = []
        for msg in msg_list:
            match msg["read_state"]:
                case 0:
                    unread_msg.append(msg)
                case 1:
                    read_msg.append(msg)
        return {
            "read_msg": read_msg,
            "unread_msg": unread_msg
        }

async def update_msg_read_status(session: dict, message_id_list: list) -> None:
    if not message_id_list:
        return
    table_type = "group" if session["type"] == "group" else "user"
    placeholders = ",".join("?" for _ in message_id_list)
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        await db.execute(
            f"""
            UPDATE {table_type}_{session['id']}
            SET read_state = 1
            WHERE message_id IN ({placeholders})
            """,
            message_id_list
        )
        await db.commit()

async def get_latest_group_msg(group_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        await init_group_msg_table(db, group_id)
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                user_id,
                nickname,
                content,
                image_data,
                from_me,
                read_state
            FROM group_{group_id}
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_latest_friend_msg(user_id: int) -> dict:
    async with aiosqlite.connect(chat_cfg["message_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        await init_friend_msg_table(db, user_id)
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                content,
                image_data,
                from_me,
                read_state
            FROM user_{user_id}
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def init_memory_db() -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_impression (
                group_id INTEGER PRIMARY KEY,
                impression TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id INTEGER PRIMARY KEY,
                portrait TEXT,
                memory TEXT,
                impression TEXT
            )
            """
        )
        await db.commit()

async def get_user_list_in_memory() -> list[int]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT user_id
            FROM user_memory
            ORDER BY user_id
            """
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_group_impression(group_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT impression
            FROM group_impression
            WHERE group_id = ?
            """,
            (group_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def get_user_portrait(user_id: int) -> str:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT portrait
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else ""

async def get_user_memory(user_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT memory
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def get_user_impression(user_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT impression
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def update_group_impression(group_id: int, new_impression: list[dict], overwrite: bool) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        if overwrite:
            impression = new_impression
        else:
            cursor = await db.execute(
                """
                SELECT impression
                FROM group_impression
                WHERE group_id = ?
                """,
                (group_id,)
            )
            row = await cursor.fetchone()
            impression = json.loads(row[0]) if row and row[0] else []
            impression.extend(new_impression)
        await db.execute(
            """
            INSERT INTO group_impression (group_id, impression)
            VALUES (?, ?)
            ON CONFLICT(group_id)
            DO UPDATE SET impression = excluded.impression
            """,
            (group_id, json.dumps(impression, ensure_ascii=False))
        )
        await db.commit()

async def update_user_impression(user_id: int, new_impression: list[dict], overwrite: bool) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        if overwrite:
            impression = new_impression
        else:
            cursor = await db.execute(
                """
                SELECT impression
                FROM user_memory
                WHERE user_id = ?
                """,
                (user_id,)
            )
            row = await cursor.fetchone()
            impression = json.loads(row[0]) if row and row[0] else []
            impression.extend(new_impression)
        await db.execute(
            """
            INSERT INTO user_memory (user_id, impression)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET impression = excluded.impression
            """,
            (user_id, json.dumps(impression, ensure_ascii=False))
        )
        await db.commit()

async def get_user_all_memory(user_list: list[int]) -> list[dict]:
    if not user_list:
        return []
    placeholders = ", ".join("?" for _ in user_list)
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                user_id,
                impression,
                memory,
                portrait
            FROM user_memory
            WHERE user_id IN ({placeholders})
            ORDER BY user_id
            """,
            user_list
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row["user_id"],
                "portrait": row["portrait"] or "",
                "memory": json.loads(row["memory"]) if row["memory"] else [],
                "impression": json.loads(row["impression"]) if row["impression"] else []
            }
            for row in rows
        ]

async def update_user_all_memory(user_id: int, new_portrait: str, new_memory: list[dict]) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        await db.execute(
            """
            UPDATE user_memory
            SET
                portrait = ?,
                memory = ?,
                impression = ?
            WHERE user_id = ?
            """,
            (
                new_portrait,
                json.dumps(new_memory, ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                user_id
            )
        )
        await db.commit()