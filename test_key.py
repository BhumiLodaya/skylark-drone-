import os
from langchain_google_genai import ChatGoogleGenerativeAI

TEST_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not TEST_KEY:
    print("Missing GEMINI_API_KEY or GOOGLE_API_KEY environment variable. Set one and retry.")
    raise SystemExit(1)

try:
    print("Testing connection...")
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", google_api_key=TEST_KEY)
    response = llm.invoke("Reply with just the word: Success")
    content = getattr(response, "content", str(response))
    print(f"Result: {content}")
except Exception as e:
    print(f"\nERROR: {e}")