"""Prompt Loader — load LLM prompts from external text files.

This module makes it easy for users to find and edit the AI prompts.
It looks for .txt files in the `prompts/` directory at the project root.
If a file doesn't exist, it uses the provided default prompt and writes 
it to the file system so the user can edit it later.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Base directory for prompt files
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')

def get_prompt(prompt_name: str, default_text: str) -> str:
    """Load a prompt from a text file, creating it with default text if missing.
    
    Args:
        prompt_name: The base name of the file (e.g., 'chat_agent').
        default_text: The default prompt text to use and save if missing.
        
    Returns:
        The loaded prompt string.
    """
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    file_path = os.path.join(PROMPTS_DIR, f"{prompt_name}.txt")
    
    # Return from file if it exists
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.error(f"[prompt_loader] Failed to read {file_path}: {e}")
            
    # File doesn't exist or is empty, create it with the default text
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(default_text.strip() + "\n")
        logger.info(f"[prompt_loader] Created default prompt file: {file_path}")
    except Exception as e:
        logger.error(f"[prompt_loader] Failed to write default prompt to {file_path}: {e}")
        
    return default_text.strip()
