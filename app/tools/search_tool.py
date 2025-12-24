from duckduckgo_search import DDGS
import json

def search_web(query: str, max_results: int = 5) -> str:
    """
    Perform a web search using DuckDuckGo.
    
    Args:
        query (str): The search query.
        max_results (int): Maximum number of results to return.
        
    Returns:
        str: JSON string containing search results.
    """
    try:
        print(f"[TOOL] Searching web for: {query}")
        with DDGS() as ddgs:
            try:
                results = list(ddgs.text(query, region='us-en', max_results=max_results))
            except Exception:
                results = []
            
        if not results:
            return json.dumps({"error": "No results found."})
            
        # Simplify results for the LLM
        simplified_results = []
        for r in results:
            simplified_results.append({
                "title": r.get("title"),
                "snippet": r.get("body"),
                "link": r.get("href")
            })
            
        return json.dumps(simplified_results, indent=2)
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        return json.dumps({"error": f"Search failed: {str(e)}"})
