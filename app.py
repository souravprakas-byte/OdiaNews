import gradio as gr

def run_pipeline():
    return "Odisha News Intelligence Running ✅"

demo = gr.Interface(
    fn=run_pipeline,
    inputs=[],
    outputs="text"
)

demo.launch()
