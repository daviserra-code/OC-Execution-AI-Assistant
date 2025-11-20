import openai
import os
import json
from app.tools import search_web, calculate

class OpenAIService:
    def __init__(self):
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        openai.api_key = self.api_key
        
        # Define tools schema
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the internet for current information, news, or facts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform a mathematical calculation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "The mathematical expression to evaluate (e.g., 'sqrt(144) * 25')."
                            }
                        },
                        "required": ["expression"]
                    }
                }
            }
        ]

    def get_chat_completion(self, messages, model="gpt-4o", temperature=0.7, max_tokens=3000):
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
            
        # First call to LLM
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=self.tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        # If no tool calls, return response as is
        if not tool_calls:
            return response
            
        # Handle tool calls
        messages.append(response_message)
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            tool_output = None
            if function_name == "search_web":
                tool_output = search_web(function_args.get("query"))
            elif function_name == "calculate":
                tool_output = calculate(function_args.get("expression"))
                
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": tool_output
            })
            
        # Second call to LLM with tool outputs
        return openai.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

    def get_chat_stream(self, messages, model="gpt-4o", temperature=0.7, max_tokens=3000):
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        # Note: Streaming with tools is complex. For simplicity in this iteration,
        # we will use non-streaming for tool calls or just basic streaming without tools for now
        # if the user didn't explicitly ask for a complex streaming tool implementation.
        # However, to support the requested feature in the UI which expects a stream,
        # we might need to handle this carefully.
        
        # Current strategy: Use standard completion for tool logic (blocking), 
        # then stream the FINAL response.
        
        # 1. Check if tools are needed (using a non-streaming check or just standard completion)
        # For efficiency, let's try to use the standard completion logic first if tools are likely,
        # OR we can just stream and if a tool call chunk arrives, we handle it.
        # Handling tool calls in stream is tricky.
        
        # SIMPLIFIED APPROACH:
        # We will use get_chat_completion logic to handle tools, then yield the result chunk by chunk
        # to mimic a stream for the frontend.
        
        completion = self.get_chat_completion(messages, model, temperature, max_tokens)
        content = completion.choices[0].message.content
        
        # Mock stream object
        class MockChunk:
            def __init__(self, content):
                self.choices = [type('obj', (object,), {'delta': type('obj', (object,), {'content': content})})]
        
        # Yield the whole content in a few chunks to simulate streaming
        chunk_size = 20
        for i in range(0, len(content), chunk_size):
            yield MockChunk(content[i:i+chunk_size])

# Global instance
openai_service = OpenAIService()
