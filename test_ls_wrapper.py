from google import genai
from langsmith import wrappers
import sys

try:
    # Attempt to create a dummy client (no API key needed for init usually, but we pass dummy)
    client = genai.Client(api_key="AIzaDummyKey")
    
    # Attempt to wrap it
    wrapped_client = wrappers.wrap_gemini(client)
    
    print("SUCCESS: Client wrapped successfully.")
    print(f"Wrapped Type: {type(wrapped_client)}")
except Exception as e:
    print(f"FAILURE: {e}")
    sys.exit(1)
