#!/usr/bin/env python3
"""
Main entry point for the Brazilian Financial SaaS application.
"""

import os
from app import app
from helpers import init_db

if __name__ == '__main__':
    # Initialize database if it doesn't exist
    if not os.path.exists('./database.db'):
        print("Database not found. Initializing...")
        init_db()
        print("Database initialized successfully!")
    
    # Run in debug mode for development
    app.run(host='0.0.0.0', port=5000, debug=True)
else:
    # Production mode - initialize database if needed
    if not os.path.exists('./database.db'):
        init_db()