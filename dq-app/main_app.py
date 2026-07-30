from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
import pandas as pd



app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all (for dev)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules: UploadFile = File(...)
):
    try:
        # Read dataset
        df = pd.read_excel("sample_source_data.xlsx")

        # Read rules file
        rules_df = pd.read_excel("sample_rules.xlsx")

        return {
            "columns": list(df.columns),
            "rules": rules_df.to_dict(orient="records")
        }

    except Exception as e:
        return {"error": str(e)}