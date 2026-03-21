"""
SpreadScope - Flask Dashboard Application
"""

import os
from flask import Flask

def create_app(config=None):
    """Create and configure the Flask app."""
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    # Default config
    app.config['SECRET_KEY'] = os.urandom(24)
    app.config['DB_AVAILABLE'] = False
    
    if config:
        app.config.update(config)
    
    # Register routes
    from .routes import register_routes
    register_routes(app)
    
    return app