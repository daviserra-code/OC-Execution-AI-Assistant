import sys
import io
import contextlib

def execute_python(code):
    """
    Executes the given Python code and returns the output.
    WARNING: This executes code locally. Ensure the code is safe.
    """
    # Capture stdout
    stdout_buffer = io.StringIO()
    
    try:
        with contextlib.redirect_stdout(stdout_buffer):
            # Create a restricted global scope if needed, but for now we use a clean dict
            # We can pre-import common libs like math, datetime, random
            exec_globals = {
                "__builtins__": __builtins__,
                "import": __builtins__['__import__'] # Allow imports
            }
            exec(code, exec_globals)
            
        output = stdout_buffer.getvalue()
        return output if output else "[No output]"
        
    except Exception as e:
        return f"Error executing code: {str(e)}"
