from fastapi import FastAPI, UploadFile, File
import pandas as pd

app = FastAPI()

@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules: UploadFile = File(...)
):
    try:
        # Read dataset
        df = pd.read_excel(dataset.file)

        # Read rules file
        rules_df = pd.read_excel(rules.file)

        return {
            "columns": list(df.columns),
            "rules": rules_df.to_dict(orient="records")
        }

    except Exception as e:
        return {"error": str(e)}