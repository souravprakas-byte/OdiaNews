from fastapi import FastAPI
from src.odisha_ai_news.pipeline import main

app = FastAPI()

@app.get("/")
def home():
    return {"status": "Odisha News Intelligence running"}

@app.get("/run")
def run_pipeline():
    result = main()
    return {"status": "completed", "result": result}
