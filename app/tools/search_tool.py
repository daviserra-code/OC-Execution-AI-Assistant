from duckduckgo_search import DDGS

def search_web(query, max_results=5):
    """
    Searches the web for the given query using DuckDuckGo.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            
        formatted_results = []
        for r in results:
            formatted_results.append(f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}")
            
        return "\n\n".join(formatted_results)
    except Exception as e:
        return f"Error searching web: {str(e)}"
