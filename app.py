import sys
import os
sys.path.append(os.path.abspath("src"))

import gradio as gr
from odisha_ai_news.pipeline import main

def run_pipeline():
    try:
        main()
        return 
