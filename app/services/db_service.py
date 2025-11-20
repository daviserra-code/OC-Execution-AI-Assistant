import sqlite3
from contextlib import contextmanager
import os

class DBService:
    def __init__(self, db_path='chat_history.db'):
        self.db_path = db_path

    def init_database(self):
        """Initialize the SQLite database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_exchanges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    mode TEXT DEFAULT 'general',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL UNIQUE,
                    custom_prompt TEXT NOT NULL,
                    modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_session_id ON chat_exchanges (session_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_exchanges (timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_mode ON system_prompts (mode)
            ''')
            conn.commit()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_session(self, session_id):
        """Create a new session in the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)',
                    (session_id,)
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error creating session in database: {e}")
            return False

    def save_exchange(self, session_id, user_message, assistant_response, mode='general'):
        """Save a chat exchange to the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Ensure session exists first
                cursor.execute('''
                    INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)
                ''', (session_id,))

                # Insert the chat exchange
                cursor.execute('''
                    INSERT INTO chat_exchanges (session_id, user_message, assistant_response, mode)
                    VALUES (?, ?, ?, ?)
                ''', (session_id, user_message, assistant_response, mode))

                # Update session last activity
                cursor.execute('''
                    UPDATE chat_sessions 
                    SET last_activity = CURRENT_TIMESTAMP 
                    WHERE session_id = ?
                ''', (session_id,))

                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error saving chat exchange: {e}")
            raise e

    def get_history(self, session_id, limit=50):
        """Load chat history from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_message, assistant_response, mode, timestamp
                    FROM chat_exchanges
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                ''', (session_id, limit))

                rows = cursor.fetchall()
                history = [
                    {
                        'user': row['user_message'],
                        'assistant': row['assistant_response'],
                        'mode': row['mode'] or 'general',
                        'timestamp': row['timestamp']
                    }
                    for row in rows
                ]
                return history
        except Exception as e:
            print(f"Error loading chat history from database: {e}")
            return []

    def clear_history(self, session_id):
        """Clear chat history for a specific session"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM chat_exchanges WHERE session_id = ?', (session_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error clearing history: {e}")
            return False

    def get_stats(self):
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) as count FROM chat_sessions')
                session_count = cursor.fetchone()['count']
                cursor.execute('SELECT COUNT(*) as count FROM chat_exchanges')
                exchange_count = cursor.fetchone()['count']
                return {'sessions': session_count, 'exchanges': exchange_count}
        except Exception as e:
            print(f"❌ Database stats error: {e}")
            return {'sessions': 0, 'exchanges': 0}
