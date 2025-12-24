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
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    model TEXT NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    response TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON token_usage (timestamp)
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

    def log_token_usage(self, session_id, model, tokens_in, tokens_out):
        """Log token usage and calculate cost"""
        # Cost per 1k tokens (approximate as of late 2024)
        rates = {
            'gpt-4o': {'in': 0.005, 'out': 0.015},
            'gpt-4-turbo': {'in': 0.01, 'out': 0.03},
            'gpt-3.5-turbo': {'in': 0.0005, 'out': 0.0015}
        }
        
        rate = rates.get(model, rates['gpt-4o']) # Default to gpt-4o rates
        cost = (tokens_in / 1000 * rate['in']) + (tokens_out / 1000 * rate['out'])
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO token_usage (session_id, model, tokens_in, tokens_out, cost)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session_id, model, tokens_in, tokens_out, cost))
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error logging token usage: {e}")
            return False

    def get_daily_cost(self):
        """Get total cost for the current day"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(cost) as total_cost 
                    FROM token_usage 
                    WHERE date(timestamp) = date('now')
                ''')
                result = cursor.fetchone()
                return result['total_cost'] or 0.0
        except Exception as e:
            print(f"❌ Error getting daily cost: {e}")
            return 0.0

    def get_cached_response(self, cache_key):
        """Retrieve a cached response"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT response FROM response_cache WHERE cache_key = ?', (cache_key,))
                row = cursor.fetchone()
                return row['response'] if row else None
        except Exception as e:
            print(f"❌ Error retrieving cached response: {e}")
            return None

    def save_cached_response(self, cache_key, response):
        """Save a response to the cache"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO response_cache (cache_key, response)
                    VALUES (?, ?)
                ''', (cache_key, response))
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error saving cached response: {e}")
            return False
