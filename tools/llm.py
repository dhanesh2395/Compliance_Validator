from crewai import  LLM
import os

def get_llm():
    return LLM(
        model="groq/llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0, # deterministic output
        base_url = "https://api.groq.com/openai/v1"
    )