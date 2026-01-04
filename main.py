import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app import create_app
from app.routes.main_routes import db_service
from app.services.rag_service import rag_service
import threading
import socket

app = create_app()
# Initialize Database
try:
    db_service.init_database()
    
    # Create default admin user if not exists
    if not db_service.verify_user('admin', 'admin123'):
        # Check if admin exists at all (verify_user checks password too)
        # We need to rely on create_user failing if user exists, or check explicitly.
        # create_user handles unique constraint, but won't update password if exists.
        # Let's try to create it.
        if db_service.create_user('admin', 'admin123', 'admin'):
            print("[INFO] Default admin user created (admin/admin123)")
        else:
            print("[INFO] Admin user already exists or creation failed")
            
    print("[OK] Database initialized successfully")
except Exception as e:
    print(f"[ERROR] Database initialization error: {e}")

# Initialize RAG in background


if __name__ == '__main__':
    # Production configuration for deployment
    port = int(os.environ.get('PORT', 8080))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'

    print(f"[INFO] Starting Flask app on port {port} (debug: {debug_mode})")
    app.run(host='0.0.0.0', port=port, debug=debug_mode, threaded=True)