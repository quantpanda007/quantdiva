from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# serve static files
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# load UI
@app.get("/")
def load_ui():
    return FileResponse("frontend/templates/optima.html")