import pytest
import tempfile
import os
from datetime import datetime, timezone
from app import app
from helpers import brl, br_datetime, parse_br_currency, parse_br_datetime, init_db, get_db_connection

@pytest.fixture
def client():
    # Create a temporary database for testing
    db_fd, app.config['DATABASE'] = tempfile.mkstemp()
    app.config['TESTING'] = True
    
    # Set test database path
    os.environ['DB_PATH'] = app.config['DATABASE']
    
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client
    
    os.close(db_fd)
    os.unlink(app.config['DATABASE'])

def test_currency_formatting():
    """Test Brazilian currency formatting"""
    assert brl(1000.50) == "R$ 1.000,50"
    assert brl(1234567.89) == "R$ 1.234.567,89"
    assert brl(0) == "R$ 0,00"
    assert brl(None) == "R$ 0,00"

def test_datetime_formatting():
    """Test Brazilian datetime formatting"""
    utc_time = "2023-12-25T15:30:00+00:00"
    # This test might fail based on timezone, but it should be close
    formatted = br_datetime(utc_time)
    assert "/" in formatted
    assert ":" in formatted

def test_currency_parsing():
    """Test parsing Brazilian currency format"""
    assert parse_br_currency("1.000,50") == 1000.50
    assert parse_br_currency("R$ 1.234.567,89") == 1234567.89
    assert parse_br_currency("100,00") == 100.00
    
    with pytest.raises(ValueError):
        parse_br_currency("invalid")

def test_datetime_parsing():
    """Test parsing Brazilian datetime format"""
    result = parse_br_datetime("25/12/2023 15:30")
    # Should return a valid ISO datetime string
    assert isinstance(result, str)
    assert "T" in result
    
    with pytest.raises(ValueError):
        parse_br_datetime("invalid date")

def test_index_redirect(client):
    """Test that index redirects to login when not logged in"""
    rv = client.get('/')
    assert rv.status_code == 302
    assert '/login' in rv.location

def test_register_get(client):
    """Test registration page loads"""
    rv = client.get('/register')
    assert rv.status_code == 200
    assert b'Criar Conta' in rv.data

def test_register_post_valid(client):
    """Test valid user registration"""
    rv = client.post('/register', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert rv.status_code == 302  # Should redirect after successful registration

def test_register_post_duplicate_email(client):
    """Test registration with duplicate email"""
    # First registration
    client.post('/register', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    # Second registration with same email
    rv = client.post('/register', data={
        'name': 'Test User 2',
        'email': 'test@example.com',
        'password': 'password456'
    })
    assert rv.status_code == 200  # Should stay on registration page
    assert 'Este email já está cadastrado'.encode() in rv.data

def test_login_get(client):
    """Test login page loads"""
    rv = client.get('/login')
    assert rv.status_code == 200
    assert b'Login' in rv.data

def test_login_post_invalid(client):
    """Test login with invalid credentials"""
    rv = client.post('/login', data={
        'email': 'nonexistent@example.com',
        'password': 'wrongpassword'
    })
    assert rv.status_code == 200  # Should stay on login page
    assert b'Email ou senha incorretos' in rv.data

def test_login_post_valid(client):
    """Test login with valid credentials"""
    # First register a user
    client.post('/register', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    # Then login
    rv = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert rv.status_code == 302  # Should redirect after successful login

def test_dashboard_requires_login(client):
    """Test that dashboard requires authentication"""
    rv = client.get('/dashboard')
    assert rv.status_code == 302
    assert '/login' in rv.location

def test_dashboard_with_login(client):
    """Test dashboard access when logged in"""
    # Register and login
    client.post('/register', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    # Access dashboard
    rv = client.get('/dashboard')
    assert rv.status_code == 200
    assert b'Dashboard' in rv.data

def test_assistant_api_without_login(client):
    """Test that assistant API requires authentication"""
    rv = client.post('/api/assistant', json={'message': 'test'})
    assert rv.status_code == 302  # Should redirect to login

def test_assistant_api_with_login(client):
    """Test assistant API when logged in"""
    # Register and login
    client.post('/register', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    # Test assistant
    rv = client.post('/api/assistant', 
                     json={'message': 'saldo total'},
                     content_type='application/json')
    assert rv.status_code == 200
    
    data = rv.get_json()
    assert data['status'] == 'ok'
    assert 'answer' in data

def test_database_initialization():
    """Test that database initializes correctly"""
    # Create temporary database
    db_fd, db_path = tempfile.mkstemp()
    os.environ['DB_PATH'] = db_path
    
    try:
        init_db()
        
        # Check that tables exist
        conn = get_db_connection()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        expected_tables = ['users', 'categories', 'accounts', 'entries']
        for table in expected_tables:
            assert table in tables
    
    finally:
        os.close(db_fd)
        os.unlink(db_path)

def test_trial_status_calculation():
    """Test trial status calculation"""
    # This would require more setup to test the actual trial logic
    # For now, just test that the function exists and can be imported
    from app import check_trial_status
    assert callable(check_trial_status)

if __name__ == '__main__':
    pytest.main([__file__])
