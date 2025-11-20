import requests
import json

url = "http://localhost:8081/chat_stream"
headers = {"Content-Type": "application/json"}
data = {
    "message": "Who won the Super Bowl in 2024?",
    "session_id": "test_session",
    "mode": "general"
}

print(f"Sending request to {url}...")
try:
    response = requests.post(url, json=data, stream=True)
    print(f"Status Code: {response.status_code}")
    
    full_response = ""
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                content = decoded_line[6:]
                if content == "[DONE]":
                    break
                try:
                    json_content = json.loads(content)
                    if "content" in json_content:
                        full_response += json_content["content"]
                except:
                    pass
    
    print(f"Response: {full_response}")
    
    if "Chiefs" in full_response or "49ers" in full_response:
        print("[SUCCESS] Search tool worked (or fallback triggered).")
    else:
        print("[FAILURE] Search tool did not provide expected answer.")

except Exception as e:
    print(f"[ERROR] Request failed: {e}")
