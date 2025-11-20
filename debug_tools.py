from app.tools import search_web, calculate
import json

print("Testing Calculator...")
result = calculate("sqrt(144) * 25")
print(f"Calculator Result: {result}")

print("\nTesting Search...")
result = search_web("Who won the Super Bowl in 2024?")
print(f"Search Result: {result}")
