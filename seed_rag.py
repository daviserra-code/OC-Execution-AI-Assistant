from app.services.rag_service import rag_service
import os
import time

# Content to seed
content = """
This is a test document for Teyra RAG persistence.
The secret code is: ALPHA-TANGO-FOXTROT-99.
If Teyra can recall this code after a restart, persistence is working.
"""

print("Initializing RAG service...")
rag_service.initialize()

print("Seeding RAG data...")
# Add a small delay to ensure initialization is complete
time.sleep(1)

success = rag_service.add_document(content, "test_rag.txt", ".txt")

if success:
    print("✅ Document added and saved.")
else:
    print("❌ Failed to add document.")
