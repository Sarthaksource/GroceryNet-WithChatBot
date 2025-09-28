import re

def extract_session_id(output_contexts: list) -> str:
    """Extracts the session ID from a list of output contexts."""
    if not output_contexts:
        return ""
    context_name = output_contexts[0].get('name', '')
    match = re.search(r"/sessions/(.*?)/contexts/", context_name)
    return match.group(1) if match else ""

def get_str_from_item_dict(item_dict: dict) -> str:
    """Converts a dictionary of items and quantities to a readable string."""
    return ", ".join([f"{int(value)} {key}" for key, value in item_dict.items()])

def get_context(output_contexts: list, context_name: str) -> dict:
    """Finds a specific context by name from the list of output contexts."""
    for context in output_contexts:
        if context_name in context.get('name', ''):
            return context
    return None