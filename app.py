import sys
import os
sys.path.append(os.path.abspath("src"))

import gradio as gr
from odisha_ai_news.pipeline import main

def run_pipeline():
    try:
        main()
        return "Odisha News Intelligence Pipeline ran successfully ✅"
    except Exception as e:
        return f"Error running pipeline: {str(e)}"

demo = gr.Interface(
    fn=run_pipeline,
    inputs=[],
    outputs="text"
)

demo.launch()
