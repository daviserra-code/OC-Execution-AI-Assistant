import json
import math

def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression safely.
    
    Args:
        expression (str): The mathematical expression to evaluate (e.g., "sqrt(144) * 25").
        
    Returns:
        str: The result of the calculation or an error message.
    """
    try:
        print(f"[TOOL] Calculating: {expression}")
        # Whitelist of safe functions/constants
        safe_dict = {
            'abs': abs,
            'round': round,
            'min': min,
            'max': max,
            'pow': pow,
            'sqrt': math.sqrt,
            'sin': math.sin,
            'cos': math.cos,
            'tan': math.tan,
            'pi': math.pi,
            'e': math.e
        }
        
        # Evaluate the expression in a restricted environment
        result = eval(expression, {"__builtins__": None}, safe_dict)
        return json.dumps({"result": result})
    except Exception as e:
        return json.dumps({"error": f"Calculation failed: {str(e)}"})
