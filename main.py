import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app import create_app
from app.routes.main_routes import main_bp, db_service
from app.services.rag_service import rag_service
import threading
import socket

app = create_app()
app.register_blueprint(main_bp)

# Initialize Database
try:
    db_service.init_database()
    print("[OK] Database initialized successfully")
except Exception as e:
    print(f"[ERROR] Database initialization error: {e}")

# Initialize RAG in background


if __name__ == '__main__':
    # Production configuration for deployment
    port = int(os.environ.get('PORT', 8080))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'

    # Try different ports if default is occupied
    for attempt_port in [port, 8081, 8082, 5005, 5006]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', attempt_port))
                port = attempt_port
                break
        except OSError:
            continue

    print(f"[INFO] Starting Flask app on port {port} (debug: {debug_mode})")
    app.run(host='0.0.0.0', port=port, debug=debug_mode, threaded=True)