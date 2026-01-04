import openai
import os
import json
from app.tools.search_tool import search_web
from app.tools.code_execution_tool import execute_python
from app.services.db_service import DBService
from app.config import DAILY_COST_LIMIT

db_service = DBService()

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
                    "name": "execute_python",
                    "description": "Execute Python code to perform calculations, data analysis, or generate visualizations. Use print() to output results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The Python code to execute."
                            }
                        },
                        "required": ["code"]
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
            elif function_name == "execute_python":
                tool_output = execute_python(function_args.get("code"))
                
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

    def get_chat_stream(self, messages, session_id=None, model="gpt-4o", temperature=0.7, max_tokens=3000):
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        # Check daily cost limit
        current_cost = db_service.get_daily_cost()
        if current_cost >= DAILY_COST_LIMIT:
            yield f"⚠️ **Daily Cost Limit Exceeded**\n\nYou have reached the daily limit of ${DAILY_COST_LIMIT:.2f}. Please contact the administrator or wait until tomorrow."
            return

        # First call to LLM with stream=True
        stream = openai.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=self.tools,
            tool_choice="auto",
            stream=True,
            stream_options={"include_usage": True}
        )

        tool_calls = []
        current_tool_call = None
        usage_data = None
        
        for chunk in stream:
            # Handle usage data if present (usually in the last chunk)
            if hasattr(chunk, 'usage') and chunk.usage:
                usage_data = chunk.usage
                continue

            if not chunk.choices:
                continue
                
            delta = chunk.choices[0].delta
            
            # Handle content (stream immediately)
            if delta.content:
                yield delta.content
            
            # Handle tool calls (aggregate)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.id: # New tool call
                        if current_tool_call:
                            tool_calls.append(current_tool_call)
                        current_tool_call = {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or ""
                            },
                            "type": "function"
                        }
                    elif current_tool_call: # Continuation of arguments
                        if tc.function.arguments:
                            current_tool_call["function"]["arguments"] += tc.function.arguments

        # Append last tool call if any
        if current_tool_call:
            tool_calls.append(current_tool_call)

        # Log usage for first call
        if usage_data:
             # We need a session ID to log usage properly. 
             # Since we don't have it passed here easily without changing signature, 
             # we'll use a placeholder or try to extract it if we refactor.
             # For now, let's assume we can get it or pass it. 
             # Ideally, get_chat_stream should accept session_id.
             # For this iteration, we'll log with 'unknown_session' or similar if not passed.
             # BUT, looking at main_routes, we can pass session_id.
             pass 
             # NOTE: I will update the method signature in a separate step to pass session_id
             # For now, let's just log it if we can, or skip session_id.
             db_service.log_token_usage(session_id, model, usage_data.prompt_tokens, usage_data.completion_tokens)

        # If we had tool calls, we need to execute them and recurse
        if tool_calls:
            # Create a proper assistant message object from our aggregated data
            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": []
            }
            
            for tc in tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"]
                })
                
            messages.append(assistant_msg)

            # Execute tools
            for tc in tool_calls:
                function_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                    
                    tool_output = None
                    if function_name == "search_web":
                        yield "\n\n*Searching the web...*\n\n"
                        tool_output = search_web(args.get("query"))
                    elif function_name == "execute_python":
                        yield "\n\n*Executing code...*\n\n"
                        tool_output = execute_python(args.get("code"))
                    
                    messages.append({
                        "tool_call_id": tc["id"],
                        "role": "tool",
                        "name": function_name,
                        "content": tool_output
                    })
                except Exception as e:
                    print(f"Error executing tool {function_name}: {e}")
                    messages.append({
                        "tool_call_id": tc["id"],
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error: {str(e)}"
                    })

            # Second call to LLM (Streamed)
            stream2 = openai.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True}
            )
            
            usage_data_2 = None
            for chunk in stream2:
                if hasattr(chunk, 'usage') and chunk.usage:
                    usage_data_2 = chunk.usage
                    continue

                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            
            # Log usage for second call
            if usage_data_2:
                db_service.log_token_usage(session_id, model, usage_data_2.prompt_tokens, usage_data_2.completion_tokens)

# Global instance
openai_service = OpenAIService()
