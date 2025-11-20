import os
from dotenv import load_dotenv, find_dotenv

print(f"Current working directory: {os.getcwd()}")
env_file = find_dotenv()
print(f"Found .env file at: {env_file}")

load_dotenv()

api_key = os.environ.get('OPENAI_API_KEY')
print(f"OPENAI_API_KEY present: {bool(api_key)}")
if api_key:
    print(f"OPENAI_API_KEY length: {len(api_key)}")
    print(f"OPENAI_API_KEY start: {api_key[:10]}...")
    print(f"OPENAI_API_KEY end: ...{api_key[-5:]}")
else:
    print("OPENAI_API_KEY is None or empty")

# Check for other potential conflicting vars
print(f"FLASK_ENV: {os.environ.get('FLASK_ENV')}")
