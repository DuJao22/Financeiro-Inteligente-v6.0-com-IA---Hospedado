import sqlite3
import sqlitecloud
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# SQLite Cloud configuration
SQLITECLOUD_URL = os.environ.get("SQLITECLOUD_URL", "sqlitecloud://cmq6frwshz.g4.sqlite.cloud:8860/database.db?apikey=Dor8OwUECYmrbcS5vWfsdGpjCpdm9ecSDJtywgvRw8k")
USE_SQLITE_CLOUD = os.environ.get("USE_SQLITE_CLOUD", "true").lower() == "true"
DB_PATH = os.environ.get("DB_PATH", "./database.db")

def brl(value):
    """Format value as Brazilian currency"""
    if value is None:
        value = 0
    s = f"{float(value):,.2f}"
    return "R$ " + s.replace(',', 'X').replace('.', ',').replace('X', '.')

def br_datetime(utc_iso_string):
    """Convert UTC ISO string to Brazilian datetime format"""
    if not utc_iso_string:
        return ""
    
    try:
        # Parse UTC datetime
        dt_utc = datetime.fromisoformat(utc_iso_string.replace('Z', '+00:00'))
        
        # Convert to Brazilian timezone
        dt_br = dt_utc.astimezone(ZoneInfo('America/Sao_Paulo'))
        
        # Format as DD/MM/YYYY HH:MM
        return dt_br.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return utc_iso_string

def parse_br_currency(value_str):
    """Parse Brazilian currency format to float"""
    if not value_str:
        return 0.0
    
    # Remove R$ and spaces
    value_str = value_str.replace('R$', '').strip()
    
    # Handle Brazilian format: 1.234.567,89
    # Remove thousands separators (dots)
    value_str = value_str.replace('.', '')
    
    # Replace decimal comma with dot
    value_str = value_str.replace(',', '.')
    
    try:
        return float(value_str)
    except ValueError:
        raise ValueError("Formato de valor inválido")

def parse_br_datetime(datetime_str):
    """Parse datetime to UTC ISO format - accepts both Brazilian DD/MM/YYYY HH:MM and HTML5 YYYY-MM-DDTHH:MM formats"""
    if not datetime_str:
        # Default to now
        return datetime.now(timezone.utc).isoformat()
    
    try:
        datetime_str = datetime_str.strip()
        
        # Check if it's HTML5 datetime-local format (YYYY-MM-DDTHH:MM)
        if 'T' in datetime_str:
            # HTML5 datetime-local format - treat as local São Paulo time
            dt = datetime.fromisoformat(datetime_str)
            # Set Brazilian timezone
            dt_br = dt.replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
        else:
            # Brazilian format DD/MM/YYYY or DD/MM/YYYY HH:MM
            if len(datetime_str) == 10:  # DD/MM/YYYY
                datetime_str += ' 12:00'  # Default to noon
            
            # Parse Brazilian format
            dt_br = datetime.strptime(datetime_str, '%d/%m/%Y %H:%M')
            # Set Brazilian timezone
            dt_br = dt_br.replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
        
        # Convert to UTC
        dt_utc = dt_br.astimezone(timezone.utc)
        
        return dt_utc.isoformat()
    except ValueError:
        raise ValueError("Formato de data inválido")

class DictRow:
    """Simple row class that acts like both dict and has attribute access"""
    def __init__(self, cursor, row):
        self._data = {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]
        
    def __getattr__(self, key):
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")
    
    def keys(self):
        return self._data.keys()
    
    def values(self):
        return self._data.values()
    
    def items(self):
        return self._data.items()

def get_db_connection():
    """Get database connection with row factory"""
    if USE_SQLITE_CLOUD:
        # SQLite Cloud connection
        conn = sqlitecloud.connect(SQLITECLOUD_URL)
        # Custom row factory for SQLite Cloud compatibility
        conn.row_factory = DictRow
    else:
        # Local SQLite connection
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    """Initialize database with schema"""
    if USE_SQLITE_CLOUD:
        print("Connecting to SQLite Cloud database...")
    else:
        if not os.path.exists(DB_PATH):
            print("Creating local database...")
        
    conn = get_db_connection()
    
    # Read and execute schema
    with open('schema.sql', 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    
    # For SQLite Cloud, we need to execute statements individually
    if USE_SQLITE_CLOUD:
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
        for statement in statements:
            try:
                conn.execute(statement)
            except Exception as e:
                print(f"Error executing statement: {statement[:50]}... - {e}")
    else:
        conn.executescript(schema_sql)
    
    conn.commit()
    conn.close()
    
    db_type = "SQLite Cloud" if USE_SQLITE_CLOUD else "Local SQLite"
    print(f"{db_type} database initialized successfully!")

def seed_categories(conn, user_id):
    """Create default categories for a user"""
    default_categories = [
        # Receitas
        ('Salário', 'receita'),
        ('Freelance', 'receita'),
        ('Vendas', 'receita'),
        ('Investimentos', 'receita'),
        ('Outros Ganhos', 'receita'),
        
        # Despesas
        ('Alimentação', 'despesa'),
        ('Transporte', 'despesa'),
        ('Moradia', 'despesa'),
        ('Saúde', 'despesa'),
        ('Educação', 'despesa'),
        ('Lazer', 'despesa'),
        ('Roupas', 'despesa'),
        ('Serviços', 'despesa'),
        ('Impostos', 'despesa'),
        ('Outros Gastos', 'despesa'),
    ]
    
    for name, cat_type in default_categories:
        conn.execute(
            'INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)',
            (user_id, name, cat_type)
        )
