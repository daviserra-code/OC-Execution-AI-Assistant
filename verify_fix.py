import os
from dotenv import load_dotenv

# Simulate the fixed main.py order
load_dotenv()

# Import the service which should now pick up the key
from app.services.openai_service import openai_service

print(f"Service initialized: {openai_service}")
if openai_service.api_key and len(openai_service.api_key) > 10:
    print(f"✅ SUCCESS: Key loaded in service: {openai_service.api_key[:8]}...{openai_service.api_key[-4:]}")
else:
    print(f"❌ FAILURE: Key not loaded. Value: '{openai_service.api_key}'")
