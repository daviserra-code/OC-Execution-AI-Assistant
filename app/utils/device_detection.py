import re

def detect_device(user_agent):
    """
    Detects the device type from the user agent string.
    Returns: 'mobile', 'tablet', or 'desktop'
    """
    if not user_agent:
        return 'desktop'
        
    user_agent = user_agent.lower()
    
    # Tablet detection
    if 'tablet' in user_agent or 'ipad' in user_agent or ('android' in user_agent and 'mobile' not in user_agent):
        return 'tablet'
        
    # Mobile detection
    if 'mobile' in user_agent or 'iphone' in user_agent or 'android' in user_agent or 'webos' in user_agent:
        return 'mobile'
        
    # Default to desktop
    return 'desktop'
