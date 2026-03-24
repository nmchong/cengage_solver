from __future__ import annotations
import os
import re
import random
from typing import List, Optional, TYPE_CHECKING
from dotenv import load_dotenv

if TYPE_CHECKING:
    from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Global client for lazy initialization
_client: Optional[OpenAI] = None

def get_client() -> Optional[OpenAI]:
    """Lazily initializes and returns the OpenAI client."""
    global _client
    if _client is not None:
        return _client
        
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
        
    try:
        from openai import OpenAI as OpenAIClient
        _client = OpenAIClient(api_key=api_key)
        return _client
    except (ImportError, Exception) as e:
        print(f"Error initializing OpenAI client: {e}")
        return None

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Initialize rich console
console = Console()

def get_ranking(question: str, choices: List[str], page_context: str = "") -> List[int]:
    """
    Ranks the choices for a given question from most to least likely using an LLM.
    
    Args:
        question: The quiz question text.
        choices: A list of possible answers.
        page_context: Additional text context from the page.
        
    Returns:
        A list of 0-based indices of the choices, ordered by likelihood.
    """
    if not choices:
        return []

    # Mock mode support
    if os.getenv("LLM_MOCK") == "true":
        console.print("[yellow][LLM DEBUG][/yellow] Mock mode is active. Returning random ranking.")
        return random.sample(range(len(choices)), len(choices))

    # Explicit check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print("[red][LLM DEBUG][/red] No OPENAI_API_KEY found. Falling back to default order.")
        return list(range(len(choices)))
    else:
        key_preview = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "****"
        console.print(f"[green][LLM DEBUG][/green] Found API key: [cyan]{key_preview}[/cyan]")

    # Format choices with indices for the LLM
    formatted_choices = "\n".join([f"{i}: {choice}" for i, choice in enumerate(choices)])
    
    context_block = f"Additional Page Context:\n{page_context}\n\n" if page_context else ""
    
    prompt = (
        f"{context_block}"
        f"Question: {question}\n\n"
        f"Choices:\n{formatted_choices}\n\n"
        "Rank the choices from most likely to be correct to least likely. "
        "Return only the indices of the choices, separated by commas, in order from most likely to least likely. "
        "Do not include any other text or explanation."
    )

    debug_text = Text()
    debug_text.append("Sending prompt to LLM", style="bold magenta")
    if page_context:
        debug_text.append(f" (with {len(page_context)} chars context)", style="italic")
    
    console.print(Panel(prompt[:500] + "...", title="[magenta]LLM Prompt Preview[/magenta]", border_style="magenta"))

    try:
        client = get_client()
        if not client:
            console.print("[red][LLM DEBUG][/red] Could not initialize OpenAI client. Falling back.")
            return list(range(len(choices)))

        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-5.4-nano"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant that ranks quiz answers based on their likelihood of being correct."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        content = response.choices[0].message.content.strip()
        console.print(f"[green][LLM DEBUG][/green] Raw LLM response: [yellow]'{content}'[/yellow]")
        
        # Extract indices from the response
        # Expecting something like "1, 0, 2" or "1,0,2"
        indices = [int(idx.strip()) for idx in re.findall(r'\d+', content)]
        
        # Filter to ensure indices are within valid range and unique
        valid_indices = []
        for idx in indices:
            if 0 <= idx < len(choices) and idx not in valid_indices:
                valid_indices.append(idx)
        
        # If some indices are missing, append them at the end
        for i in range(len(choices)):
            if i not in valid_indices:
                valid_indices.append(i)
        
        console.print(f"[green][LLM DEBUG][/green] Final parsed ranking (choices): [cyan]{[i+1 for i in valid_indices]}[/cyan]")
        return valid_indices

    except Exception as e:
        console.print(f"[red][LLM DEBUG][/red] Error calling LLM: {e}")
        # Fallback: return indices in original order
        return list(range(len(choices)))

if __name__ == "__main__":
    # Basic CLI test
    test_question = "What is the capital of France?"
    test_choices = ["London", "Paris", "Berlin", "Madrid"]
    
    print(f"Question: {test_question}")
    print(f"Choices: {test_choices}")
    
    # Test mock mode
    os.environ["LLM_MOCK"] = "true"
    print(f"Mock Ranking: {get_ranking(test_question, test_choices)}")
    
    # Test real mode (will fallback if no key)
    os.environ["LLM_MOCK"] = "false"
    ranking = get_ranking(test_question, test_choices)
    print(f"Ranking (indices): {ranking}")
    print(f"Ranking (values): {[test_choices[i] for i in ranking]}")
