from app.services.rag_service import rag_service
import sys

print("Initializing RAG service...")
rag_service.initialize()

query = "What is the secret code?"
print(f"Searching for: {query}")
results = rag_service.search(query)

print(f"Found {len(results)} results:")
for r in results:
    print(f"- {r['content'][:50]}... (Score: {r['similarity_score']})")

if any("ALPHA-TANGO-FOXTROT-99" in r['content'] for r in results):
    print("[SUCCESS] Secret code found!")
else:
    print("[FAILURE] Secret code NOT found.")
