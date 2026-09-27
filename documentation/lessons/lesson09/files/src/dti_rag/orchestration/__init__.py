"""The same pipeline in framework abstractions (Lesson 09). Evaluated, not shipped by default.

Frameworks are built from config.py values passed explicitly. Their Azure classes fall back
to environment variables (AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION) when a value is
missing, and a stale export in your shell would point them at another environment.
"""
