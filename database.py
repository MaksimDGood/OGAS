import sqlite3
from config import DB_NAME

def init_db():
    """Инициализация базы данных и создание всех необходимых таблиц"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица индивидуальных настроек каждого чата
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY,
        min_votes_percent INTEGER DEFAULT 30,       -- Процент голосов для прохождения кандидата (30%)
        min_quorum_percent INTEGER DEFAULT 15,      -- ПОРОГ ЯВКИ: минимум 15% участников чата должны проголосовать
        poll_duration_hours INTEGER DEFAULT 24,     -- ВРЕМЯ ГОЛОСОВАНИЯ: по умолчанию 24 часа
        auto_poll_period_months INTEGER DEFAULT 3,   -- Период автоматических выборов в месяцах
        last_auto_poll_timestamp TEXT
    )
    ''')

    # Таблица для регистрации кандидатов во время избирательной кампании
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        first_name TEXT NOT NULL
    )
    ''')

    # Таблица для отслеживания текущего состояния выборов администраторов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS election_state (
        chat_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,                        -- 'registration' (сбор заявок) или 'voting' (идет опрос)
        announcement_msg_id INTEGER,                 -- ID сообщения бота об объявлении сбора
        poll_id TEXT,                                -- ID самого опроса в Telegram
        poll_msg_id INTEGER                          -- ID сообщения с опросом в Telegram
    )
    ''')

    # Таблица для технических опросов по изменению настроек чата большинством
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config_polls (
        poll_id TEXT PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        config_type TEXT NOT NULL,                   -- 'threshold', 'quorum' или 'duration'
        new_value INTEGER NOT NULL
    )
    ''')

    conn.commit()
    conn.close()


def register_chat(chat_id: int):
    """Регистрация чата в базе данных с настройками по умолчанию, если его там нет"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO chats (chat_id) VALUES (?)', (chat_id,))
    conn.commit()
    conn.close()


def get_chat_settings(chat_id: int):
    """Получение текущих настроек конкретного чата"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT min_votes_percent, min_quorum_percent, poll_duration_hours, auto_poll_period_months 
        FROM chats WHERE chat_id = ?
    ''', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "threshold": row[0],
            "quorum_percent": row[1],
            "duration": row[2],
            "period": row[3]
        }
    return {"threshold": 30, "quorum_percent": 15, "duration": 24, "period": 3}


def update_chat_threshold(chat_id: int, new_threshold: int):
    """Обновление проходного порога для кандидатов в админы"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE chats SET min_votes_percent = ? WHERE chat_id = ?', (new_threshold, chat_id))
    conn.commit()
    conn.close()


def update_chat_quorum(chat_id: int, new_quorum_percent: int):
    """Обновление порога явки в процентах от числа участников чата"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE chats SET min_quorum_percent = ? WHERE chat_id = ?', (new_quorum_percent, chat_id))
    conn.commit()
    conn.close()


def update_chat_duration(chat_id: int, new_duration_hours: int):
    """Обновление длительности проведения опросов чата"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE chats SET poll_duration_hours = ? WHERE chat_id = ?', (new_duration_hours, chat_id))
    conn.commit()
    conn.close()


def add_candidate(chat_id: int, user_id: int, username: str, first_name: str) -> bool:
    """Добавление кандидата в список (возвращает False, если уже зарегистрирован)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM candidates WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    if cursor.fetchone():
        conn.close()
        return False
        
    cursor.execute('''
        INSERT INTO candidates (chat_id, user_id, username, first_name)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, user_id, username, first_name))
    conn.commit()
    conn.close()
    return True


def get_candidates(chat_id: int):
    """Получение упорядоченного списка кандидатов для формирования пунктов опроса"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, first_name FROM candidates WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"user_id": r[0], "first_name": r[1]} for r in rows]


def clear_candidates(chat_id: int):
    """Полная очистка состояния выборов и списка кандидатов после их окончания"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM candidates WHERE chat_id = ?', (chat_id,))
    cursor.execute('DELETE FROM election_state WHERE chat_id = ?', (chat_id,))
    conn.commit()
    conn.close()


def set_election_state(chat_id: int, status: str, msg_id: int = None, poll_id: str = None):
    """Сохранение или перезапись текущего статуса избирательного процесса"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO election_state (chat_id, status, announcement_msg_id, poll_id)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, status, msg_id, poll_id))
    conn.commit()
    conn.close()


def get_election_state(chat_id: int):
    """Получение текущего статуса выборов в конкретной группе"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT status, announcement_msg_id, poll_id FROM election_state WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"status": row[0], "msg_id": row[1], "poll_id": row[2]}
    return None


def save_config_poll(poll_id: str, chat_id: int, config_type: str, new_value: int):
    """Запись технического опроса настроек в базу данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO config_polls (poll_id, chat_id, config_type, new_value)
        VALUES (?, ?, ?, ?)
    ''', (poll_id, chat_id, config_type, new_value))
    conn.commit()
    conn.close()
