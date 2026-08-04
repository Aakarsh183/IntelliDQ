'''import os
import sys
 
os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.functions import col , monotonically_increasing_id
from pyspark.sql.functions import countDistinct
import pandas as pd
import uuid
from grok_client import GrokClient
from column_resolver import ColumnResolver
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all (for dev)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = GrokClient()

DATA_STORE = {}

@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules: UploadFile = File(...)
):

    try:
        spark = SparkSession.builder.appName("DQ_ENGINE").getOrCreate()

        excel_data = pd.read_excel(dataset.file, sheet_name=None, engine="openpyxl")
        
        session_id = str(uuid.uuid4())
        if(len(excel_data) == 1):
            pdf = pd.read_excel(dataset.file, engine="openpyxl")
            df = spark.createDataFrame(pdf)
            rules_df = pd.read_excel(rules.file, engine="openpyxl")
            column_resolver = ColumnResolver(df.columns)
            column_list = []
            for _, row in rules_df.iterrows():

                rule = {
                    "name": row["name"],
                    "description": row["description"],
                    "business_rule": row["business_rule"],
                    "complexity": row["complexity"],
                    "category": row["category"]
                }
                output = column_resolver.extract_entity_and_conversion(rule)
                lt = []
                for json in output:
                    lt.append(json["entity"])
                column_list.append(lt)
            rules_df["entities"] = column_list

            

            
            DATA_STORE[session_id] = {
                "df": df,
                "rules_df": rules_df,
                "columns": df.columns,
                "schema": "\n".join(df.columns)
            }
            
            return {
                "session_id": session_id,
                "columns": list(df.columns),
                "rules": rules_df.to_dict(orient="records")
            }
        
        else:
            tables = {}
            schema = {}

            for sheet_name, pdf in excel_data.items():
                df = spark.createDataFrame(pdf)
                tables[sheet_name] = df
                schema[sheet_name] = list(df.columns)

            rules_df = pd.read_excel(rules.file, engine="openpyxl")

            # 🔥 FLATTEN schema for entity extraction
            flat_columns = [
                f"{table}.{col}"
                for table, cols in schema.items()
                for col in cols
            ]

            column_resolver = ColumnResolver(flat_columns)

            column_list = []
            for _, row in rules_df.iterrows():
                rule = {
                    "name": row["name"],
                    "description": row["description"],
                    "business_rule": row["business_rule"],
                    "complexity": row["complexity"],
                    "category": row["category"]
                }

                output = column_resolver.extract_entity_and_conversion(rule)
                column_list.append([json["entity"] for json in output])

            rules_df["entities"] = column_list

            DATA_STORE[session_id] = {
                "mode": "multi",
                "tables": tables,
                "rules_df": rules_df,
                "schema_dict": schema,
                "columns": flat_columns,
                "schema": str(schema)
            }

            return {
                "session_id": session_id,
                "mode": "multi",
                "schema": schema,
                "rules": rules_df.to_dict(orient="records")
            }


    except Exception as e:
        return {"error": str(e)}

@app.post("/generate_code")
async def generate_code(payload: dict):
    print("Incoming payload:", payload)
    session_id = payload["session_id"]
    session = DATA_STORE.get(session_id)
    rule = payload["rule"]
    weights = payload.get("weights")
    print("Session ID:", session_id)     # 👈 ADD THIS
    print("Available sessions:", DATA_STORE.keys())  # 👈 ADD THIS
    mapped_dict = session.get("mapped_dict")
    print(mapped_dict)
    
    if not session:
        return {"error": "Invalid session_id. Please upload again."}
    
    
    
    if not session:
        return {"error": "Invalid session"}
    if session["mode"] == "single":
        response = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict
        )
    else:
         response = client.generate_pyspark_code_multi(
            tables=session["tables"],
            schema=session["schema_dict"],
            rule=rule,
            mapped_dict=mapped_dict
        )
    response["mapped_dict"] = mapped_dict

    return response

@app.post("/regenerate_code")
async def regenerate_code(payload: dict):

    session_id = payload.get("session_id")
    rule = payload.get("rule")
    columns = payload.get("columns")
    weights = payload.get("weights")

    session = DATA_STORE.get(session_id)

    if not session:
        return {"error": "Invalid session"}
    
    entities = rule.get("entities",[])
    
    mapped_dict = session.get("mapped_dict")
    print(mapped_dict)

    if session["mode"] == "single":
        for e,c in zip(entities,columns):
            mapped_dict[e] = c
        print(mapped_dict)
        response = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict
        )
    else:
        for e,c in zip(entities,columns):
            mapped_dict[e] = c
        print(mapped_dict)
        response = client.generate_pyspark_code_multi(
            tables=session["tables"],
            schema=session["schema_dict"],
            rule=rule,
            mapped_dict=mapped_dict
        )
    response["mapped_dict"] = mapped_dict
    return response

@app.post("/suggest_columns")
async def suggest_columns(payload: dict):

    session_id = payload.get("session_id")
    rule = payload.get("rule")
    weights = payload.get("weights")

    session = DATA_STORE.get(session_id)

    if not session:
        return {"error": "Invalid session"}
    
    rules = session["rules_df"]
    columns = session["columns"]
    entities = rule.get("entities", [])
    column_resolver = ColumnResolver(columns)
    mapped_dict = column_resolver.resolve(rules,weights)
    
    suggestions = []
    for i in entities:
        suggestions.append(mapped_dict[i])

    return {"suggested_columns": suggestions}

class ExecuteRequest(BaseModel):
    session_id: str
    pyspark_code: str


@app.post("/execute_code")
async def execute_code(req: ExecuteRequest):
    try:
        session = DATA_STORE.get(req.session_id)

        if not session:
            return {"status": "error", "error": "Invalid session"}
        if session["mode"] == "single":
            df = session["df"]

            
            

            local_vars = {
                "df": df
            }
        else:
            for name, df in session["tables"].items():
                local_vars[name] = df
        # 🔥 Execute generated code
        exec(req.pyspark_code, local_vars)

        result = local_vars.get("result", {})

        return {
            "status": "success",
            "result": result
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
    
@app.post("/get_mappings")
async def get_mappings(payload: dict):

    session_id = payload.get("session_id")
    weights = payload.get("weights")

    session = DATA_STORE.get(session_id)

    if not session:
        return {"error": "Invalid session"}

    rules = session["rules_df"]
    dataset_columns = session["columns"]

    column_resolver = ColumnResolver(dataset_columns)

    
    mapped_dict = column_resolver.resolve(rules, weights)

    session["mapped_dict"] = mapped_dict

    return {
        "mapped_dict": mapped_dict
    }

class RuleInput(BaseModel):
    session_id: str
    name: str
    description: str
    business_rule: str
    complexity: str
    category: str

@app.post("/add_rule")
async def add_rule(payload: RuleInput):

    session = DATA_STORE.get(payload.session_id)

    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]

    if "Id" in rules_df.columns:
        new_id = int(rules_df["id"].max()) + 1 if not rules_df.empty else 1
    else:
        new_id = None

    # Create rule dict
    new_rule = {
        "Id": new_id,
        "name": payload.name,
        "description": payload.description,
        "business_rule": payload.business_rule,
        "complexity": payload.complexity,
        "category": payload.category
    }

    # Extract entities
    column_resolver = ColumnResolver(session["columns"])
    entities_output = column_resolver.extract_entity_and_conversion(new_rule)
    
    entities = [e["entity"] for e in entities_output]
    print(entities)
    new_rule["entities"] = entities

    # Ensure column alignment
    for col in rules_df.columns:
        if col not in new_rule:
            new_rule[col] = None

    # Convert to DataFrame with SAME columns order
    new_row = pd.DataFrame([new_rule])[rules_df.columns]

    # Append safely
    session["rules_df"] = pd.concat([rules_df, new_row], ignore_index=True)

    return {
        "message": "Rule added successfully",
        "rule": new_rule,
        "rules": session["rules_df"].to_dict(orient="records")
    }

@app.post("/recommend_rules")
async def recommend_rules(payload: dict):

    session = DATA_STORE.get(payload["session_id"])

    if not session:
        return {"error": "Invalid session"}

    schema = session["schema"]
    rules_df = session["rules_df"]
 
    existing_rules = rules_df["business_rule"].tolist()

    ai_rules = client.generate_ai_rules(schema, existing_rules)

    return {
        "recommended_rules": ai_rules
    }

'''

'''
import os
import sys

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, monotonically_increasing_id, countDistinct
import pandas as pd
import uuid
import io
from grok_client import GrokClient
from column_resolver import ColumnResolver
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = GrokClient()
DATA_STORE = {}


def get_spark():
    return SparkSession.builder.appName("DQ_ENGINE").getOrCreate()


# ─────────────────────────────────────────────────────────────────────────────
# /upload
# Auto-detects single vs multi-table based on sheet count.
# Single sheet  → existing behavior, returns flat "columns" list.
# Multi sheet   → returns "tables" dict, stores dfs per sheet.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules:   UploadFile = File(...)
):
    try:
        spark = get_spark()

        # Read rules file (unchanged)
        rules_df = pd.read_excel(rules.file, engine="openpyxl")

        # Read dataset — check how many sheets
        dataset_bytes = await dataset.read()
        excel_file    = pd.ExcelFile(io.BytesIO(dataset_bytes), engine="openpyxl")
        sheet_names   = excel_file.sheet_names

        session_id = str(uuid.uuid4())

        # ── SINGLE TABLE (existing behavior, zero changes) ────────────────────
        if len(sheet_names) == 1:
            pdf      = pd.read_excel(excel_file, sheet_name=sheet_names[0])
            df       = spark.createDataFrame(pdf)
            resolver = ColumnResolver(list(df.columns))

            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            DATA_STORE[session_id] = {
                "is_multi_table": False,
                "df":             df,
                "rules_df":       rules_df,
                "columns":        list(df.columns),
                "schema":         "\n".join(df.columns),
            }

            return {
                "session_id":     session_id,
                "is_multi_table": False,
                "columns":        list(df.columns),          # existing shape
                "rules":          rules_df.to_dict(orient="records"),
            }

        # ── MULTI TABLE ───────────────────────────────────────────────────────
        else:
            dfs         = {}
            tables_meta = {}
            all_columns_flat = []   # "SheetName.column" qualified names

            for sheet in sheet_names:
                pdf      = pd.read_excel(excel_file, sheet_name=sheet)
                spark_df = spark.createDataFrame(pdf)
                dfs[sheet]         = spark_df
                cols               = list(spark_df.columns)
                tables_meta[sheet] = {"columns": cols}
                all_columns_flat.extend([f"{sheet}.{c}" for c in cols])

            # Entity extraction uses qualified pool so LLM returns
            # e.g. "Orders.amount" — tells us which sheet each entity belongs to
            print(all_columns_flat)
            resolver    = ColumnResolver(all_columns_flat)
            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            print(column_list)
            rules_df["entities"] = column_list

            schema_lines = [
                f"[{sheet}]: " + ", ".join(meta["columns"])
                for sheet, meta in tables_meta.items()
            ]

            DATA_STORE[session_id] = {
                "is_multi_table": True,
                "dfs":            dfs,
                "rules_df":       rules_df,
                "tables_meta":    tables_meta,
                "all_columns":    all_columns_flat,
                "schema":         "\n".join(schema_lines),
            }

            return {
                "session_id":     session_id,
                "is_multi_table": True,
                "tables":         tables_meta,               # new shape for frontend
                "columns":        all_columns_flat,
                "rules":          rules_df.to_dict(orient="records"),
            }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /get_mappings
# Single table → original logic unchanged.
# Multi table  → resolves each entity against the full qualified pool,
#                so mapped values come back as "SheetName.column".
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/get_mappings")
async def get_mappings(payload: dict):
    session_id = payload.get("session_id")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]

    # ── SINGLE TABLE (original logic) ────────────────────────────────────────
    if not session["is_multi_table"]:
        dataset_columns = session["columns"]
        column_resolver = ColumnResolver(dataset_columns)
        mapped_dict     = column_resolver.resolve(rules_df, weights)
        session["mapped_dict"] = mapped_dict
        return {"mapped_dict": mapped_dict}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    all_columns     = session["all_columns"]
    column_resolver = ColumnResolver(all_columns)
    mapped_dict     = column_resolver.resolve(rules_df, weights)
    session["mapped_dict"] = mapped_dict
    return {"mapped_dict": mapped_dict}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_code
# Single table → original logic unchanged.
# Multi table  → infers which tables are needed from the mapped_dict values,
#                builds a joined DataFrame if entities span multiple sheets,
#                passes table context to the LLM prompt.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_code")
async def generate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id. Please upload again."}

    mapped_dict = session.get("mapped_dict", {})

    # ── SINGLE TABLE (original logic) ────────────────────────────────────────
    if not session["is_multi_table"]:
        response = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        return response

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    dfs         = session["dfs"]
    tables_meta = session["tables_meta"]

    # Figure out which tables this rule touches by inspecting the mapped values.
    # mapped_dict values for multi-table look like "Orders.amount",
    # so we extract the sheet name prefix.
    entities      = rule.get("entities", [])
    touched_tables = _get_touched_tables(entities, mapped_dict, dfs)

    df = _build_dataframe(touched_tables, dfs)

    response = client.generate_pyspark_code_multi(
        df=df,
        rule=rule,
        mapped_dict=mapped_dict,
        touched_tables=touched_tables
    )
    response["mapped_dict"] = mapped_dict
    return response


# ─────────────────────────────────────────────────────────────────────────────
# /regenerate_code
# Single table → original logic unchanged.
# Multi table  → same table-inference as generate_code after applying overrides.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/regenerate_code")
async def regenerate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    columns    = payload.get("columns")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    mapped_dict = dict(session.get("mapped_dict", {}))
    entities    = rule.get("entities", [])

    # Apply manual overrides
    for e, c in zip(entities, columns):
        mapped_dict[e] = c

    # ── SINGLE TABLE (original logic) ────────────────────────────────────────
    if not session["is_multi_table"]:
        response = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        return response

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    dfs            = session["dfs"]
    touched_tables = _get_touched_tables(entities, mapped_dict, dfs)
    df             = _build_dataframe(touched_tables, dfs)

    response = client.generate_pyspark_code_multi(
        df=df,
        rule=rule,
        mapped_dict=mapped_dict,
        touched_tables=touched_tables
    )
    response["mapped_dict"] = mapped_dict
    return response


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_columns
# Single table → original logic unchanged.
# Multi table  → resolves against the full qualified pool.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/suggest_columns")
async def suggest_columns(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    entities = rule.get("entities", [])

    # ── SINGLE TABLE (original logic) ────────────────────────────────────────
    if not session["is_multi_table"]:
        columns         = session["columns"]
        column_resolver = ColumnResolver(columns)
        mapped_dict     = column_resolver.resolve(
            pd.DataFrame([_rule_from_payload(rule)]), weights
        )
        suggestions = [mapped_dict.get(e, "") for e in entities]
        return {"suggested_columns": suggestions}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    all_columns     = session["all_columns"]
    column_resolver = ColumnResolver(all_columns)
    mapped_dict     = column_resolver.resolve(
        pd.DataFrame([_rule_from_payload(rule)]), weights
    )
    suggestions = [mapped_dict.get(e, "") for e in entities]
    return {"suggested_columns": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_code
# Single table → injects `df` only (original behavior).
# Multi table  → injects both `df` (first sheet, backward compat)
#                and `dfs` dict so generated code can reference any sheet.
# ─────────────────────────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    session_id:   str
    pyspark_code: str


@app.post("/execute_code")
async def execute_code(req: ExecuteRequest):
    try:
        session = DATA_STORE.get(req.session_id)
        if not session:
            return {"status": "error", "error": "Invalid session"}

        # ── SINGLE TABLE (original logic) ──────────────────────────────────
        if not session["is_multi_table"]:
            local_vars = {"df": session["df"]}
            exec(req.pyspark_code, local_vars)
            result = local_vars.get("result", {})
            return {"status": "success", "result": result}

        # ── MULTI TABLE ────────────────────────────────────────────────────
        dfs        = session["dfs"]
        primary_df = next(iter(dfs.values()))
        local_vars = {
            "df":  primary_df,   # keeps single-table generated code working
            "dfs": dfs,          # cross-table code can do dfs["Orders"] etc.
        }
        exec(req.pyspark_code, local_vars)
        result = local_vars.get("result", {})
        return {"status": "success", "result": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /add_rule  (unchanged — rule structure is exactly the same)
# ─────────────────────────────────────────────────────────────────────────────
class RuleInput(BaseModel):
    session_id:    str
    name:          str
    description:   str
    business_rule: str
    complexity:    str
    category:      str


@app.post("/add_rule")
async def add_rule(payload: RuleInput):
    session = DATA_STORE.get(payload.session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]

    new_rule = {
        "name":          payload.name,
        "description":   payload.description,
        "business_rule": payload.business_rule,
        "complexity":    payload.complexity,
        "category":      payload.category,
    }

    # Pick column pool based on dataset type
    if session["is_multi_table"]:
        pool = session["all_columns"]
    else:
        pool = session["columns"]

    column_resolver      = ColumnResolver(pool)
    entities_output      = column_resolver.extract_entity_and_conversion(new_rule)
    new_rule["entities"] = [e["entity"] for e in entities_output]

    for col_name in rules_df.columns:
        if col_name not in new_rule:
            new_rule[col_name] = None

    new_row = pd.DataFrame([new_rule])
    for col_name in new_row.columns:
        if col_name not in rules_df.columns:
            rules_df[col_name] = None

    session["rules_df"] = pd.concat(
        [rules_df, new_row[rules_df.columns]], ignore_index=True
    )

    return {
        "message": "Rule added successfully",
        "rule":    new_rule,
        "rules":   session["rules_df"].to_dict(orient="records"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /recommend_rules  (unchanged — just passes richer schema for multi-table)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/recommend_rules")
async def recommend_rules(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    schema         = session["schema"]
    rules_df       = session["rules_df"]
    existing_rules = rules_df["business_rule"].tolist()

    ai_rules = client.generate_ai_rules(schema, existing_rules)
    return {"recommended_rules": ai_rules}


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_rule(row):
    return {
        "name":          row["name"],
        "description":   row["description"],
        "business_rule": row["business_rule"],
        "complexity":    row["complexity"],
        "category":      row["category"],
    }

def _rule_from_payload(rule):
    return {
        "name":          rule.get("name", ""),
        "description":   rule.get("description", ""),
        "business_rule": rule.get("business_rule", ""),
        "complexity":    rule.get("complexity", ""),
        "category":      rule.get("category", ""),
    }

def _get_touched_tables(entities, mapped_dict, dfs):
    """
    Figures out which sheets a rule touches by inspecting mapped_dict values.
    Only treats "X.Y" as table-qualified if X is an actual sheet name in dfs.
    This prevents column names like "Rep.QTD Target USD" (dot is part of the
    column name) from being mistaken for a table separator.
    """
    touched     = set()
    sheet_names = set(dfs.keys())

    for entity in entities:
        mapped_col = mapped_dict.get(entity, "")
        if "." in mapped_col:
            prefix = mapped_col.split(".")[0]
            if prefix in sheet_names:
                touched.add(prefix)

    # Fallback: use the first sheet
    if not touched:
        touched = {next(iter(dfs.keys()))}

    return list(touched)

def _build_dataframe(touched_tables, dfs):
    """
    If only one table is touched → return it directly.
    If multiple → join them on any common columns (inner join),
    falling back to crossJoin if no common columns exist.
    """
    df_list = [dfs[t] for t in touched_tables if t in dfs]
    if not df_list:
        return next(iter(dfs.values()))

    df = df_list[0]
    for other_df in df_list[1:]:
        common = list(set(df.columns) & set(other_df.columns))
        if common:
            df = df.join(other_df, on=common, how="inner")
        else:
            df = df.crossJoin(other_df)
    return df
'''
'''
import os
import sys
import re

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from pyspark.sql import SparkSession
from fastapi.responses import StreamingResponse
from pyspark.sql.functions import col, monotonically_increasing_id, countDistinct
import pandas as pd
import uuid
import io
import math
from grok_client import GrokClient
from column_resolver import ColumnResolver
from datetime import datetime
from pydantic import BaseModel
from rag import get_or_create_rag, RAG_STORE

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = GrokClient()
DATA_STORE = {}


def get_spark():
    return SparkSession.builder.appName("DQ_ENGINE").getOrCreate()

def _sanitize_for_json(records: list) -> list:
    """
    Replace NaN / Infinity / -Infinity float values with None
    so the response is always JSON-serializable.
    """
    sanitized = []
    for row in records:
        clean_row = {}
        for key, value in row.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean_row[key] = None
            else:
                clean_row[key] = value
        sanitized.append(clean_row)
    return sanitized



def _sanitize_columns(pdf):
    """Replace dots and spaces in column names with underscores."""
    mapping  = {}
    new_cols = []
    for c in pdf.columns:
        safe = re.sub(r"[.\s]+", "_", c)
        mapping[c] = safe
        new_cols.append(safe)
    pdf.columns = new_cols
    return pdf, mapping


def _row_to_rule(row):
    return {
        "name":          row["name"],
        "description":   row["description"],
        "business_rule": row["business_rule"],
        "complexity":    row["complexity"],
        "category":      row["category"],
    }


def _rule_from_payload(rule):
    return {
        "name":          rule.get("name", ""),
        "description":   rule.get("description", ""),
        "business_rule": rule.get("business_rule", ""),
        "complexity":    rule.get("complexity", ""),
        "category":      rule.get("category", ""),
    }


def _strip_id_column_assignment(code: str) -> str:
    """Remove any line where the LLM has assigned id_column = '...'"""
    cleaned_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if re.match(r"^id_column\s*=\s*['\"]", stripped):
            print(f"⚠️ Stripped LLM id_column assignment: {stripped}")
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def _propagate_generated_id(joined_df, involved_tables, dfs, id_column):
    """
    When get_or_create_primary_key adds generated_id to a joined DataFrame,
    the individual sheet DataFrames in dfs don't have it.
    We add a monotonically_increasing_id to each involved sheet so that
    df_SheetName variables in exec() also carry the id_column.

    Note: the IDs won't match the joined df's IDs exactly — this is only
    used for failed_ids extraction which just needs a stable unique identifier
    per row within each sheet.
    """
    from pyspark.sql.functions import monotonically_increasing_id as _mii
    for sheet in involved_tables:
        if sheet in dfs and id_column not in dfs[sheet].columns:
            dfs[sheet] = dfs[sheet].withColumn(id_column, _mii())
            print(f"✅ Added {id_column} to sheet '{sheet}'")

# ─────────────────────────────────────────────────────────────────────────────
# /upload
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules:   UploadFile = File(...)
):
    try:
        spark = get_spark()

        rules_df      = pd.read_excel(rules.file, engine="openpyxl")
        dataset_bytes = await dataset.read()
        excel_file    = pd.ExcelFile(io.BytesIO(dataset_bytes), engine="openpyxl")
        sheet_names   = excel_file.sheet_names

        session_id = str(uuid.uuid4())

        # ── SINGLE TABLE ──────────────────────────────────────────────────────
        if len(sheet_names) == 1:
            raw_pdf          = pd.read_excel(excel_file, sheet_name=sheet_names[0])
            pdf, col_mapping = _sanitize_columns(raw_pdf)
            df               = spark.createDataFrame(pdf)
            resolver         = ColumnResolver(list(df.columns))

            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            DATA_STORE[session_id] = {
                "is_multi_table": False,
                "df":             df,
                "rules_df":       rules_df,
                "columns":        list(df.columns),
                "schema":         "\n".join(df.columns),
                "col_mapping":    col_mapping,
                "executed_rules": set(),
                "rule_metrics":   {},
                "result":         {},
                "timestamp":      {}
            }
            
            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": False,
                "columns":        list(df.columns),
                "rules":          rules_df.to_dict(orient="records"),
            }

        # ── MULTI TABLE ───────────────────────────────────────────────────────
        else:
            dfs              = {}
            tables_meta      = {}
            all_col_mappings = {}

            for sheet in sheet_names:
                raw_pdf              = pd.read_excel(excel_file, sheet_name=sheet)
                pdf, col_mapping     = _sanitize_columns(raw_pdf)
                spark_df             = spark.createDataFrame(pdf)
                dfs[sheet]           = spark_df
                cols                 = list(spark_df.columns)
                tables_meta[sheet]   = {"columns": cols}
                all_col_mappings[sheet] = col_mapping

            # For entity extraction at upload time, use all columns flat
            # (just to get entities — proper scoped resolve happens in /get_mappings)
            all_columns_flat = []
            for sheet, meta in tables_meta.items():
                all_columns_flat.extend(meta["columns"])

            resolver    = ColumnResolver(all_columns_flat)
            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            print(column_list)
            rules_df["entities"] = column_list

            schema_lines = [
                f"[{sheet}]: " + ", ".join(meta["columns"])
                for sheet, meta in tables_meta.items()
            ]

            DATA_STORE[session_id] = {
                "is_multi_table":  True,
                "dfs":             dfs,
                "rules_df":        rules_df,
                "tables_meta":     tables_meta,
                "schema":          "\n".join(schema_lines),
                "col_mappings":    all_col_mappings,
                # These get populated during /get_mappings:
                "mapped_dict":     {},
                "rule_table_map":  {},  # { rule_name: [involved tables] }
                "executed_rules":  set(),
                "rule_metrics":    {},
                "result":          {},
                "timestamp":       {}
            }

            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": True,
                "tables":         tables_meta,
                "columns":        list(tables_meta.items()),
                "rules":          rules_df.to_dict(orient="records"),
            }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /get_mappings
# Single table → original behavior
# Multi table  → for each rule:
#   1. LLM identifies involved tables
#   2. Similarity runs against those tables' columns only
#   3. Stores which tables each rule involves
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/get_mappings")
async def get_mappings(payload: dict):
    session_id = payload.get("session_id")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]

    # ── SINGLE TABLE (original behavior) ─────────────────────────────────────
    if not session["is_multi_table"]:
        column_resolver = ColumnResolver(session["columns"])
        mapped_dict, ranked_scores     = column_resolver.resolve(rules_df, weights)
        session["mapped_dict"] = mapped_dict
        session["ranked_scores"] = ranked_scores
        try:
            rag = get_or_create_rag(session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        return {"mapped_dict": mapped_dict, "ranked_scores": ranked_scores}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    tables_meta    = session["tables_meta"]
    mapped_dict    = {}
    ranked_scores =  {}
    rule_table_map = {}   # { rule_name: [involved_tables] }

    # Use a fresh resolver per rule (resolve_for_rule re-inits the column pool)
    resolver = ColumnResolver([])   # columns will be set per-rule inside resolve_for_rule

    for _, row in rules_df.iterrows():
        rule = _row_to_rule(row)
        rule_name = rule["name"]

        print(f"\n🔍 Processing rule: {rule_name}")

        try:
            rule_mapped, rule_ranked, involved_tables = resolver.resolve_for_rule(
                rule, tables_meta, weights
            )
            mapped_dict.update(rule_mapped)
            ranked_scores.update(rule_ranked)
            rule_table_map[rule_name] = involved_tables

        except Exception as e:
            print(f"❌ Failed mapping for rule '{rule_name}': {e}")
            rule_table_map[rule_name] = list(tables_meta.keys())

        

    session["mapped_dict"]    = mapped_dict
    session["ranked_scores"]  = ranked_scores
    session["rule_table_map"] = rule_table_map

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {"mapped_dict": mapped_dict,"ranked_scores": ranked_scores, "rule_table_map": rule_table_map}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_code
# Single table → original behavior
# Multi table  → looks up which tables the rule involves from rule_table_map,
#                builds the right DF (with join if needed),
#                passes full table context to LLM
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/generate_code")
async def generate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id. Please upload again."}

    rule_name  = rule.get("name", "")
    code_cache = session.get("code_cache", {})

    # ── Cache hit: return stored response immediately, no LLM call ────────────
    if rule_name in code_cache:
        print(f"✅ Cache hit for rule '{rule_name}' — skipping LLM")
        return code_cache[rule_name]

    # ── Cache miss: generate via LLM (existing logic unchanged) ──────────────
    mapped_dict = session.get("mapped_dict", {})

    if not session["is_multi_table"]:
        response, dataset = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["df"]           = dataset
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return response

    dfs            = session["dfs"]
    tables_meta    = session["tables_meta"]
    rule_table_map = session.get("rule_table_map", {})
    involved_tables = rule_table_map.get(rule_name)

    if not involved_tables:
        resolver = ColumnResolver([])
        involved_tables = resolver.identify_tables_for_rule(
            _rule_from_payload(rule),
            list(tables_meta.keys()),
            tables_meta=tables_meta,
        )

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        response, dataset = client.generate_pyspark_code(
            df=dfs[tbl],
            rule=rule,
            mapped_dict=mapped_dict,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["dfs"][tbl]     = dataset
    else:
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule,
            mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta,
            dfs=dfs,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df

    session.setdefault("code_cache", {})[rule_name] = response

    try:
        rag = get_or_create_rag(payload.get("session_id"))
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return response
# ─────────────────────────────────────────────────────────────────────────────
# /regenerate_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/regenerate_code")
async def regenerate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    columns    = payload.get("columns")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    mapped_dict = dict(session.get("mapped_dict", {}))
    entities    = rule.get("entities", [])

    for e, c in zip(entities, columns):
        mapped_dict[e] = c

    # ── SINGLE TABLE (unchanged) ──────────────────────────────────────────────
    if not session["is_multi_table"]:
        response, dataset = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["df"]           = dataset
        rule_name = rule.get("name", "")
        session.setdefault("code_cache", {})[rule_name] = response
        return response

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    dfs            = session["dfs"]
    tables_meta    = session["tables_meta"]
    rule_table_map = session.get("rule_table_map", {})
    rule_name      = rule.get("name", "")

    involved_tables = rule_table_map.get(rule_name)
    if not involved_tables:
        resolver = ColumnResolver([])
        involved_tables = resolver.identify_tables_for_rule(
            _rule_from_payload(rule), list(tables_meta.keys())
        )

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        response, dataset = client.generate_pyspark_code(
            df=dfs[tbl],
            rule=rule,
            mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["dfs"][tbl]     = dataset
        session["table"]        = tbl
        session.setdefault("code_catche",{})[rule_name] = response
        return response

    else:
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule,
            mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta,
            dfs=dfs
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")

        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df
            
        session.setdefault("code_catche",{})[rule_name] = response
        return response


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_columns
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/suggest_columns")
async def suggest_columns(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    entities = rule.get("entities", [])
    rule_obj = _rule_from_payload(rule)

    # ── SINGLE TABLE ──────────────────────────────────────────────────────────
    if not session["is_multi_table"]:
        column_resolver = ColumnResolver(session["columns"])
        rule_df         = pd.DataFrame([rule_obj])
        mapped_dict     = column_resolver.resolve(rule_df, weights)
        suggestions     = [mapped_dict.get(e, "") for e in entities]
        return {"suggested_columns": suggestions}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    tables_meta = session["tables_meta"]
    resolver    = ColumnResolver([])

    rule_mapped, _ = resolver.resolve_for_rule(rule_obj, tables_meta, weights)
    suggestions    = [rule_mapped.get(e, "") for e in entities]
    return {"suggested_columns": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_code
# ─────────────────────────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    session_id:   str
    pyspark_code: str
    rule_name: str


@app.post("/execute_code")
async def execute_code(req: ExecuteRequest):
    try:
        session = DATA_STORE.get(req.session_id)
        if not session:
            return {"status": "error", "error": "Invalid session"}

        clean_code = _strip_id_column_assignment(req.pyspark_code)
        id_column  = session.get("id_column")
        session["executed_rules"].add(req.rule_name)

        # ── SINGLE TABLE (unchanged) ──────────────────────────────────────────
        if not session["is_multi_table"]:
            local_vars = {
                "df":        session["df"],
                "id_column": id_column,
            }
            exec(clean_code, local_vars)
            result = local_vars.get("result", {})
            session["last_passed_df"] = local_vars.get("passed_df")
            session["last_failed_df"] = local_vars.get("failed_df")
            session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
            metrics       = session["rule_metrics"]
            avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
            session["result"][req.rule_name] = result
            session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')
            try:
                rag = get_or_create_rag(req.session_id)
                rag.update_index(session)
            except Exception as e:
                print(f"⚠️ RAG update failed: {e}")

            return {
                "status":        "success",
                "result":        result,
                "rules_executed": len(session["executed_rules"]),
                "avg_pass_rate": round(avg_pass_rate, 4),
            }

        # ── MULTI TABLE ───────────────────────────────────────────────────────
        # Each df in session["dfs"] may already have generated_id added
        # by generate_pyspark_code_multi (written back via updated_dfs).
        # Inject every sheet as df_SheetName — the generated code picks
        # the ones it needs and joins them itself.
        dfs = session["dfs"]
        table  = session.get("table"," ")
        local_vars = {
            "id_column": id_column,
            # also expose df and dfs for backward compatibility
            "df": dfs[table] if table != " " else next(iter(dfs.values())),
            "dfs": dfs,
        }

        for sheet_name, spark_df in dfs.items():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sheet_name)
            local_vars[f"df_{safe_name}"] = spark_df

        print("🔍 df.columns:", local_vars["df"].columns if "df" in local_vars else "NO DF")
        for k, v in local_vars.items():
            if k.startswith("df_"):
                print(f"🔍 {k}.columns:", v.columns)

        exec(clean_code, local_vars)

        result    = local_vars.get("result", {})
        passed_df = local_vars.get("passed_df")
        failed_df = local_vars.get("failed_df")
        
        if passed_df is not None:
            session["last_passed_df"] = passed_df
        if failed_df is not None:
            session["last_failed_df"] = failed_df

        session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
        metrics       = session["rule_metrics"]
        avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
        session["result"][req.rule_name] = result
        session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')
        print(result)

        try:
            rag = get_or_create_rag(req.session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return {
            "status":        "success",
            "result":        result,
            "rules_executed": len(session["executed_rules"]),
            "avg_pass_rate": round(avg_pass_rate, 4),
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# /add_rule
# ─────────────────────────────────────────────────────────────────────────────
class RuleInput(BaseModel):
    session_id:    str
    name:          str
    description:   str
    business_rule: str
    complexity:    str
    category:      str


@app.post("/add_rule")
async def add_rule(payload: RuleInput):
    session = DATA_STORE.get(payload.session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]
    new_rule = {
        "name":          payload.name,
        "description":   payload.description,
        "business_rule": payload.business_rule,
        "complexity":    payload.complexity,
        "category":      payload.category,
    }

    if session["is_multi_table"]:
        # Use all columns flat for entity extraction at add time
        all_cols = []
        for meta in session["tables_meta"].values():
            all_cols.extend(meta["columns"])
        pool = all_cols
    else:
        pool = session["columns"]

    column_resolver      = ColumnResolver(pool)
    entities_output      = column_resolver.extract_entity_and_conversion(new_rule)
    new_rule["entities"] = [e["entity"] for e in entities_output]

    for col_name in rules_df.columns:
        if col_name not in new_rule:
            new_rule[col_name] = None

    new_row = pd.DataFrame([new_rule])
    for col_name in new_row.columns:
        if col_name not in rules_df.columns:
            rules_df[col_name] = None

    session["rules_df"] = pd.concat(
        [rules_df, new_row[rules_df.columns]], ignore_index=True
    )
    
    try:
        rag = get_or_create_rag(payload.session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "message": "Rule added successfully",
        "rule":    new_rule,
        "rules":   session["rules_df"].to_dict(orient="records"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /recommend_rules
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/recommend_rules")
async def recommend_rules(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    schema         = session["schema"]
    rules_df       = session["rules_df"]
    existing_rules = rules_df["business_rule"].tolist()

    ai_rules = client.generate_ai_rules(schema, existing_rules)
    return {"recommended_rules": ai_rules}

@app.post("/generate_remediation")
async def generate_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    rule        = payload.get("rule")
    failed_ids  = payload.get("failed_ids", [])      # ← ADD: pass from frontend
    failed_count = payload.get("failed_count", 0)    # ← ADD: pass from frontend
    mapped_dict = session.get("mapped_dict", {})

    suggestions = client.generate_remediation(
        rule, mapped_dict, failed_ids, failed_count   # ← pass context
    )
    return {"suggestions": suggestions}

@app.post("/generate_remediation_code")
async def generate_remediation_code(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    failed_ids  = payload.get("failed_ids", [])
    id_column   = session.get("id_column")
    logic       = payload.get("logic")
    mapped_dict = session.get("mapped_dict", {})

    # ── SINGLE TABLE (unchanged) ──────────────────────────────────────────────
    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}
        try:
            code = client.generate_remediation_code(
                df, logic, mapped_dict, failed_ids, id_column
            )
            return code
        except Exception as e:
            return {"error": str(e)}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    dfs            = session["dfs"]
    tables_meta    = session["tables_meta"]
    rule_table_map = session.get("rule_table_map", {})

    # Determine which tables are involved — use the last executed rule's
    # table map. If unavailable, fall back to all tables.
   

    involved_tables = session["involved_tables"]

    if len(involved_tables) == 1:
        # ── SINGLE INVOLVED TABLE: use existing single-table method ───────────
        tbl = involved_tables[0]
        df  = dfs.get(tbl)
        if df is None:
            return {"error": f"Table '{tbl}' not found in session"}
        try:
            code = client.generate_remediation_code(
                df, logic, mapped_dict, failed_ids, id_column
            )
            return code
        except Exception as e:
            return {"error": str(e)}

    else:
        # ── MULTIPLE INVOLVED TABLES: use new multi-table method ──────────────
        try:
            code = client.generate_remediation_code_multi(
                dfs=dfs,
                involved_tables=involved_tables,
                tables_meta=tables_meta,
                remediation_logic=logic,
                mapped_dict=mapped_dict,
                failed_ids=failed_ids,
                id_column=id_column,
            )
            return code
        except Exception as e:
            return {"error": str(e)}

@app.post("/execute_remediation")
async def execute_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    code        = payload.get("pyspark_code")
    failed_ids  = payload.get("failed_ids", [])
    id_column   = session.get("id_column")

    # ── SINGLE TABLE (unchanged) ──────────────────────────────────────────────
    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}

        try:
            local_vars = {"df": df}
            exec(code, local_vars)
            remediated_df = local_vars.get("df")

            if remediated_df is None:
                return {"error": "Remediation code did not return df"}

            from pyspark.sql.functions import col as spark_col

            if id_column and id_column in df.columns and failed_ids:
                rows_affected = df.filter(
                    spark_col(id_column).isin(failed_ids)
                ).count()
                preview_df = df.filter(
                    spark_col(id_column).isin(failed_ids)
                ).limit(10)
            else:
                rows_affected = abs(remediated_df.count() - df.count())
                preview_df    = remediated_df.limit(10)

            raw_records = preview_df.toPandas().to_dict(orient="records")
            preview     = _sanitize_for_json(raw_records)

            session["remediated_df"] = remediated_df
            session.setdefault("remediation_log", []).append({
                "logic":         payload.get("logic", ""),
                "rows_affected": rows_affected,
                "failed_ids":    failed_ids,
            })

            return {
                "rows_affected": rows_affected,
                "preview":       preview,
                "audit":         session["remediation_log"][-1],
            }

        except Exception as e:
            return {"error": str(e)}

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    dfs       = session["dfs"]
    tables_meta = session["tables_meta"]
    table       =    session.get("table"," ")

    try:
        from pyspark.sql.functions import col as spark_col

        # Inject all df_TableName variables + id_column into exec scope
        local_vars = {
            "id_column": id_column,
            "df":        dfs[table] if table != " " else next(iter(dfs.values())),   # fallback
            "dfs":       dfs,
        }
        for sheet_name, spark_df in dfs.items():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sheet_name)
            local_vars[f"df_{safe_name}"] = spark_df

        exec(code, local_vars)

        # The remediation code assigns its result to `df`
        remediated_df = local_vars.get("df")

        if remediated_df is None:
            return {"error": "Remediation code did not return df"}

        # Compute rows affected
        if id_column and failed_ids:
            # Check if id_column exists in remediated_df
            if id_column in remediated_df.columns:
                rows_affected = remediated_df.filter(
                    spark_col(id_column).isin(failed_ids)
                ).count()
                preview_df = remediated_df.filter(
                    spark_col(id_column).isin(failed_ids)
                ).limit(10)
            else:
                rows_affected = remediated_df.count()
                preview_df    = remediated_df.limit(10)
        else:
            rows_affected = remediated_df.count()
            preview_df    = remediated_df.limit(10)

        raw_records = preview_df.toPandas().to_dict(orient="records")
        preview     = _sanitize_for_json(raw_records)

        # Write updated sheet dfs back to session
        # The remediation code may have updated individual df_TableName vars
        for sheet_name in dfs.keys():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sheet_name)
            updated = local_vars.get(f"df_{safe_name}")
            if updated is not None:
                session["dfs"][sheet_name] = updated

        session["remediated_df"] = remediated_df
        session.setdefault("remediation_log", []).append({
            "logic":         payload.get("logic", ""),
            "rows_affected": rows_affected,
            "failed_ids":    failed_ids,
        })

        return {
            "rows_affected": rows_affected,
            "preview":       preview,
            "audit":         session["remediation_log"][-1],
        }

    except Exception as e:
        return {"error": str(e)}
    
@app.post("/export_failed")
async def export_failed(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        failed_df      = session.get("last_failed_df")
        failed_ids = payload.get("failed_ids", [])
        id_column  = session.get("id_column")
        
        print("ID column:", id_column)
        print("Failed IDs:", failed_ids[:10])
        if failed_df is None:
            return {"error": "No failed records found. Please upload first."}

        if not failed_ids:
            return {"error": "No failed IDs provided."}

        if not id_column or id_column not in failed_df.columns:
            return {"error": f"ID column '{id_column}' not found in dataset."}

        # Filter to only the failed records
       
        failed_pd = failed_df.toPandas()
        # Write to CSV in memory
        buffer = io.StringIO()
        failed_pd.to_csv(buffer, index=False)
        buffer.seek(0)

        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )

    except Exception as e:
        return {"error": str(e)}
    
@app.post("/enrich_rule")
async def enrich_rule_api(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))

    schema = session["schema"]
    rule = payload.get("newRule")
    enriched = client.enrich_rule(rule, schema)

    return enriched

@app.post("/export_failed_remediations")
async def export_failed_remediations(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        remediated_df      = session.get("remediated_df")

        # Filter to only the failed records
       
        remediated_pd = remediated_df.toPandas()
        # Write to CSV in memory
        buffer = io.StringIO()
        remediated_pd.to_csv(buffer, index=False)
        buffer.seek(0)

        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )

    except Exception as e:
        return {"error": str(e)}
    
@app.post("/generate_all_codes")
async def generate_all_codes(payload: dict):
    session_id = payload.get("session_id")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id"}

    rules_df    = session["rules_df"]
    mapped_dict = session.get("mapped_dict", {})
    rules       = rules_df.to_dict(orient="records")

    # Initialize the cache dict if not present
    session.setdefault("code_cache", {})

    errors      = []
    generated   = []

    for rule in rules:
        rule_name = rule.get("name", "")
        try:
            if not session["is_multi_table"]:
                response, dataset = client.generate_pyspark_code(
                    df=session["df"],
                    rule=rule,
                    mapped_dict=mapped_dict,
                )
                response["mapped_dict"] = mapped_dict
                session["id_column"]    = response.get("id_column")
                session["df"]           = dataset

            else:
                dfs            = session["dfs"]
                tables_meta    = session["tables_meta"]
                rule_table_map = session.get("rule_table_map", {})
                involved_tables = rule_table_map.get(rule_name)

                if not involved_tables:
                    resolver = ColumnResolver([])
                    involved_tables = resolver.identify_tables_for_rule(
                        _rule_from_payload(rule),
                        list(tables_meta.keys()),
                        tables_meta=tables_meta,
                    )

                if len(involved_tables) == 1:
                    tbl = involved_tables[0]
                    response, dataset = client.generate_pyspark_code(
                        df=dfs[tbl],
                        rule=rule,
                        mapped_dict=mapped_dict,
                    )
                    response["mapped_dict"] = mapped_dict
                    session["id_column"]    = response.get("id_column")
                    session["dfs"][tbl]     = dataset
                else:
                    response, updated_dfs = client.generate_pyspark_code_multi(
                        rule=rule,
                        mapped_dict=mapped_dict,
                        involved_tables=involved_tables,
                        tables_meta=tables_meta,
                        dfs=dfs,
                    )
                    response["mapped_dict"] = mapped_dict
                    session["id_column"]    = response.get("id_column")
                    for tbl, enriched_df in updated_dfs.items():
                        session["dfs"][tbl] = enriched_df

            # Store full response in cache keyed by rule name
            session["code_cache"][rule_name] = response
            generated.append(rule_name)

        except Exception as e:
            errors.append({"rule": rule_name, "error": str(e)})
            print(f"❌ Failed to generate code for rule '{rule_name}': {e}")

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
        print(f"✅ RAG updated with {len(session['code_cache'])} generated codes")
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "generated":  generated,
        "failed":     errors,
        "total":      len(rules),
        "cached":     len(generated),
    }


class RAGQueryRequest(BaseModel):
    session_id:   str
    question:     str
    chat_history: list = []   # ← ADD: last N messages for context


@app.post("/rag_query")
async def rag_query(req: RAGQueryRequest):
    session = DATA_STORE.get(req.session_id)
    if not session:
        return {"error": "Invalid session. Please upload your dataset first."}

    rag = get_or_create_rag(req.session_id)

    if not rag.is_ready():
        try:
            rag.build_index(session, req.session_id)
        except Exception as e:
            return {"error": f"RAG not ready: {str(e)}"}

    # Pass chat history for context-aware classification and answering
    result = rag.query(req.question, chat_history=req.chat_history, session=session)

    return {
        "answer":    result["answer"],
        "intent":    result["intent"],
        "doc_types": result.get("doc_types"),
        "sources":   result["sources"],
    }
'''
'''
import os
import sys
import re
import json

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from pyspark.sql import SparkSession
from fastapi.responses import StreamingResponse
from pyspark.sql.functions import col, monotonically_increasing_id, countDistinct
import pandas as pd
import uuid
import io
import math
from grok_client import GrokClient
from column_resolver import ColumnResolver
from datetime import datetime
from pydantic import BaseModel
from rag import get_or_create_rag, RAG_STORE
from typing import Optional

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = GrokClient()
DATA_STORE = {}


def get_spark():
    return SparkSession.builder.appName("DQ_ENGINE").getOrCreate()


def _sanitize_for_json(records: list) -> list:
    sanitized = []
    for row in records:
        clean_row = {}
        for key, value in row.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean_row[key] = None
            else:
                clean_row[key] = value
        sanitized.append(clean_row)
    return sanitized


def _sanitize_columns(pdf):
    mapping  = {}
    new_cols = []
    for c in pdf.columns:
        safe = re.sub(r"[.\s]+", "_", c)
        mapping[c] = safe
        new_cols.append(safe)
    pdf.columns = new_cols
    return pdf, mapping


def _row_to_rule(row):
    return {
        "name":          row["name"],
        "description":   row["description"],
        "business_rule": row["business_rule"],
        "complexity":    row["complexity"],
        "category":      row["category"],
    }


def _rule_from_payload(rule):
    return {
        "name":          rule.get("name", ""),
        "description":   rule.get("description", ""),
        "business_rule": rule.get("business_rule", ""),
        "complexity":    rule.get("complexity", ""),
        "category":      rule.get("category", ""),
    }


def _strip_id_column_assignment(code: str) -> str:
    cleaned_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if re.match(r"^id_column\s*=\s*['\"]", stripped):
            print(f"⚠️ Stripped LLM id_column assignment: {stripped}")
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _propagate_generated_id(joined_df, involved_tables, dfs, id_column):
    from pyspark.sql.functions import monotonically_increasing_id as _mii
    for sheet in involved_tables:
        if sheet in dfs and id_column not in dfs[sheet].columns:
            dfs[sheet] = dfs[sheet].withColumn(id_column, _mii())
            print(f"✅ Added {id_column} to sheet '{sheet}'")


def _build_schema_rag_doc(target_schema: list,length: int) -> str:
    """
    Render the target schema as a structured Markdown document for RAG indexing.
    Grouped by category; each column shows name and data type.
    Wire this into rag.build_index / rag.update_index by reading
    session.get("schema_doc", "") as an additional document source.
    """
    if not target_schema:
        return ""

    lines = ["# Target Schema Reference\n"]
    lines.append("Unified target columns that all vendor data maps to.\n")
    
    if length == 1:
        by_category: dict = {}
        for col_def in target_schema:
            cat = col_def.get("category", "other")
            by_category.setdefault(cat, []).append(col_def)

        for category, cols in sorted(by_category.items()):
            lines.append(f"\n## Category: {category.upper()}")
            for col_def in cols:
                name  = col_def.get("name", "")
                dtype = col_def.get("type", "string")
                table  = col_def.get("table_name", "")
                lines.append(f"  - {name}  [type: {dtype}")
    else:
       by_table: dict = {}
       for col_def in target_schema:
            table = col_def.get("table_name", "")   # ← correct field name
            by_table.setdefault(table, []).append(col_def)

       for table_name, cols in sorted(by_table.items()):
            lines.append(f"\n## Table: {table_name}")

            by_category: dict = {}
            for col_def in cols:
                cat = col_def.get("category", "other")
                by_category.setdefault(cat, []).append(col_def)

            for category, cat_cols in sorted(by_category.items()):
                lines.append(f"\n  ### Category: {category.upper()}")
                for col_def in cat_cols:
                    name  = col_def.get("name", "")
                    dtype = col_def.get("type", "string")
                    lines.append(f"    - {name}  [type: {dtype}]")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# /upload
# Accepts an optional `schema` file (JSON) alongside dataset + rules.
# When schema is supplied the two-hop mapping chain is activated in /get_mappings:
#   entity → target schema column → dataset column
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules:   UploadFile = File(...),
    schema:  Optional[UploadFile] = File(None),
):
    try:
        spark = get_spark()

        rules_df      = pd.read_excel(rules.file, engine="openpyxl")
        dataset_bytes = await dataset.read()
        excel_file    = pd.ExcelFile(io.BytesIO(dataset_bytes), engine="openpyxl")
        sheet_names   = excel_file.sheet_names

        # ── Parse target schema (optional) ───────────────────────────────────
        target_schema = []
        if schema is not None:
            try:
                schema_bytes  = await schema.read()
                schema_json   = json.loads(schema_bytes.decode("utf-8"))
                target_schema = schema_json.get("target_columns", [])
                print(f"✅ Loaded target schema with {len(target_schema)} columns")
            except Exception as e:
                print(f"⚠️ Could not parse schema file: {e}")

        session_id = str(uuid.uuid4())

        # ── SINGLE TABLE ──────────────────────────────────────────────────────
        if len(sheet_names) == 1:
            raw_pdf          = pd.read_excel(excel_file, sheet_name=sheet_names[0])
            pdf, col_mapping = _sanitize_columns(raw_pdf)
            df               = spark.createDataFrame(pdf)

            # Entity extraction at upload time uses dataset columns directly
            resolver = ColumnResolver(list(df.columns), target_schema=None)

            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            DATA_STORE[session_id] = {
                "is_multi_table": False,
                "df":             df,
                "rules_df":       rules_df,
                "columns":        list(df.columns),
                "schema":         "\n".join(df.columns),
                "col_mapping":    col_mapping,
                "target_schema":  target_schema,
                "schema_doc":     _build_schema_rag_doc(target_schema,len(sheet_names)),
                "executed_rules": set(),
                "rule_metrics":   {},
                "result":         {},
                "timestamp":      {}
            }

            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": False,
                "columns":        list(df.columns),
                "rules":          rules_df.to_dict(orient="records"),
                "has_schema":     bool(target_schema),
                "schema_columns": [c["name"] for c in target_schema],
            }

        # ── MULTI TABLE ───────────────────────────────────────────────────────
        else:
            dfs              = {}
            tables_meta      = {}
            all_col_mappings = {}

            for sheet in sheet_names:
                raw_pdf                 = pd.read_excel(excel_file, sheet_name=sheet)
                pdf, col_mapping        = _sanitize_columns(raw_pdf)
                spark_df                = spark.createDataFrame(pdf)
                dfs[sheet]              = spark_df
                cols                    = list(spark_df.columns)
                tables_meta[sheet]      = {"columns": cols}
                all_col_mappings[sheet] = col_mapping

            all_columns_flat = []
            for sheet, meta in tables_meta.items():
                all_columns_flat.extend(meta["columns"])

            resolver    = ColumnResolver(all_columns_flat, target_schema=None)
            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            schema_lines = [
                f"[{sheet}]: " + ", ".join(meta["columns"])
                for sheet, meta in tables_meta.items()
            ]

            DATA_STORE[session_id] = {
                "is_multi_table":  True,
                "dfs":             dfs,
                "rules_df":        rules_df,
                "tables_meta":     tables_meta,
                "schema":          "\n".join(schema_lines),
                "col_mappings":    all_col_mappings,
                "target_schema":   target_schema,
                "schema_doc":      _build_schema_rag_doc(target_schema, len(sheet_names)),
                "mapped_dict":     {},
                "hop1_mapping":    {},
                "hop2_mapping":    {},
                "rule_table_map":  {},
                "executed_rules":  set(),
                "rule_metrics":    {},
                "result":          {},
                "timestamp":       {}
            }

            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": True,
                "tables":         tables_meta,
                "columns":        all_columns_flat,
                "rules":          rules_df.to_dict(orient="records"),
                "has_schema":     bool(target_schema),
                "schema_columns": [c["name"] for c in target_schema],
            }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /get_mappings
# When target_schema is present runs the two-hop chain:
#   Hop 1: entity → target schema column  (fuzzy + cosine + LLM vs. schema names)
#   Hop 2: schema column → dataset column (fuzzy + cosine + LLM vs. dataset cols)
#   Final: entity → dataset column        (composition)
# Returns all three mappings so the frontend can display the full chain.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/get_mappings")
async def get_mappings(payload: dict):
    session_id = payload.get("session_id")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df      = session["rules_df"]
    target_schema = session.get("target_schema", [])

    # ── SINGLE TABLE ─────────────────────────────────────────────────────────
    if not session["is_multi_table"]:
        column_resolver = ColumnResolver(session["columns"], target_schema=target_schema)
        mapped_dict, ranked_scores, extra = column_resolver.resolve(rules_df, weights)

        session["mapped_dict"]   = mapped_dict
        session["ranked_scores"] = ranked_scores
        session["hop1_mapping"]  = extra.get("hop1_mapping", {})
        session["hop2_mapping"]  = extra.get("hop2_mapping", {})

        try:
            rag = get_or_create_rag(session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        
        print(mapped_dict)
        return {
            "mapped_dict":   mapped_dict,
            "ranked_scores": ranked_scores,
            "hop1_mapping":  session["hop1_mapping"],
            "hop2_mapping":  session["hop2_mapping"],
        }

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    tables_meta    = session["tables_meta"]
    all_columns_flat = [c for meta in tables_meta.values() for c in meta["columns"]]

    mapped_dict    = {}
    ranked_scores  = {}
    rule_table_map = {}
    hop1_mapping   = {}
    hop2_mapping   = {}

    if target_schema:
        # Run global two-hop pass over all columns, then do table identification per rule
        print("\n🔀 Multi-table + schema: running scoped two-hop mapping")
        column_resolver = ColumnResolver(all_columns_flat, target_schema=target_schema, tables_meta=tables_meta)        # ← key change: enables per-rule scoping
       
        mapped_dict, ranked_scores, extra = column_resolver.resolve(rules_df, weights)
        hop1_mapping.update(extra.get("hop1_mapping", {}))
        hop2_mapping.update(extra.get("hop2_mapping", {}))

        # Table identification per rule (still needed for code generation routing).
        # Reuse the same resolver instance — no extra LLM calls for rules whose
        # scoped pool was already computed inside _resolve_two_hop.
        for _, row in rules_df.iterrows():
            rule      = _row_to_rule(row)
            rule_name = rule["name"]
            try:
                involved = column_resolver.identify_tables_for_rule(
                    rule, list(tables_meta.keys())
                )
                rule_table_map[rule_name] = involved
            except Exception as e:
                print(f"❌ Table identification failed for '{rule_name}': {e}")
                rule_table_map[rule_name] = list(tables_meta.keys())

    else:
        # Original per-rule scoped resolve (no schema)
        resolver = ColumnResolver([])
        for _, row in rules_df.iterrows():
            rule      = _row_to_rule(row)
            rule_name = rule["name"]
            print(f"\n🔍 Processing rule: {rule_name}")
            try:
                rule_mapped, rule_ranked, involved_tables = resolver.resolve_for_rule(
                    rule, tables_meta, weights
                )
                mapped_dict.update(rule_mapped)
                ranked_scores.update(rule_ranked)
                rule_table_map[rule_name] = involved_tables
            except Exception as e:
                print(f"❌ Failed mapping for rule '{rule_name}': {e}")
                rule_table_map[rule_name] = list(tables_meta.keys())
    print(mapped_dict)
    session["mapped_dict"]    = mapped_dict
    session["ranked_scores"]  = ranked_scores
    session["rule_table_map"] = rule_table_map
    session["hop1_mapping"]   = hop1_mapping
    session["hop2_mapping"]   = hop2_mapping

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "mapped_dict":    mapped_dict,
        "ranked_scores":  ranked_scores,
        "rule_table_map": rule_table_map,
        "hop1_mapping":   hop1_mapping,
        "hop2_mapping":   hop2_mapping,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_schema
# Returns a candidate target schema for the uploaded dataset.
# Works for both single-table and multi-table uploads.
@app.post("/suggest_schema")
async def suggest_schema(payload: dict):
    session_id = payload.get("session_id")
    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    if not session["is_multi_table"]:
        columns = session.get("columns", [])
        suggested = [
            {"name": col, "type": "string", "category": "default"}
            for col in columns
        ]
    else:
        suggested = []
        for table_name, meta in session.get("tables_meta", {}).items():
            for col in meta.get("columns", []):
                suggested.append({
                    "name": col,
                    "type": "string",
                    "category": table_name,
                })

    return {"suggested_schema": suggested}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_code")
async def generate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id. Please upload again."}

    rule_name  = rule.get("name", "")
    code_cache = session.get("code_cache", {})

    if rule_name in code_cache:
        print(f"✅ Cache hit for rule '{rule_name}' — skipping LLM")
        return code_cache[rule_name]

    mapped_dict = session.get("mapped_dict", {})

    if not session["is_multi_table"]:
        response, dataset = client.generate_pyspark_code(
            df=session["df"],
            rule=rule,
            mapped_dict=mapped_dict,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["df"]           = dataset
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return response

    dfs             = session["dfs"]
    tables_meta     = session["tables_meta"]
    rule_table_map  = session.get("rule_table_map", {})
    involved_tables = rule_table_map.get(rule_name)

    if not involved_tables:
        resolver = ColumnResolver([],tables_meta=tables_meta)
        involved_tables = resolver.identify_tables_for_rule(
            _rule_from_payload(rule), list(tables_meta.keys())
        )

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        response, dataset = client.generate_pyspark_code(
            df=dfs[tbl], rule=rule, mapped_dict=mapped_dict,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["dfs"][tbl]     = dataset
    else:
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule, mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta, dfs=dfs,
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df

    session.setdefault("code_cache", {})[rule_name] = response

    try:
        rag = get_or_create_rag(payload.get("session_id"))
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return response


# ─────────────────────────────────────────────────────────────────────────────
# /regenerate_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/regenerate_code")
async def regenerate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    columns    = payload.get("columns")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    mapped_dict = dict(session.get("mapped_dict", {}))
    entities    = rule.get("entities", [])

    for e, c in zip(entities, columns):
        mapped_dict[e] = c

    session["mapped_dict"] = mapped_dict
    
    if not session["is_multi_table"]:
        response, dataset = client.generate_pyspark_code(
            df=session["df"], rule=rule, mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["df"]           = dataset
        session.setdefault("code_cache", {})[rule.get("name", "")] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
            
        return response

    dfs             = session["dfs"]
    tables_meta     = session["tables_meta"]
    rule_table_map  = session.get("rule_table_map", {})
    rule_name       = rule.get("name", "")
    involved_tables = rule_table_map.get(rule_name)

    if not involved_tables:
        resolver = ColumnResolver([],tables_meta=tables_meta)
        involved_tables = resolver.identify_tables_for_rule(
            _rule_from_payload(rule), list(tables_meta.keys())
        )

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        response, dataset = client.generate_pyspark_code(
            df=dfs[tbl], rule=rule, mapped_dict=mapped_dict
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        session["dfs"][tbl]     = dataset
        session["table"]        = tbl
        session.setdefault("code_cache", {})[rule_name] = response
        return response
    else:
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule, mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta, dfs=dfs
        )
        response["mapped_dict"] = mapped_dict
        session["id_column"]    = response.get("id_column")
        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        return response


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_columns
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/suggest_columns")
async def suggest_columns(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    entities      = rule.get("entities", [])
    rule_obj      = _rule_from_payload(rule)
    rule_obj["entities"] = entities
    target_schema = session.get("target_schema", [])

    if not session["is_multi_table"]:
        column_resolver   = ColumnResolver(session["columns"], target_schema=target_schema)
        mapped_dict, _, _ = column_resolver.resolve(pd.DataFrame([rule_obj]), weights)
        suggestions       = [mapped_dict.get(e, "") for e in entities]
        return {"suggested_columns": suggestions}
    
    tables_meta      = session["tables_meta"]
    all_columns_flat = [c for meta in tables_meta.values() for c in meta["columns"]]
    if target_schema:
        # Use the scoped two-hop resolver so hop-2 draws from the right table's
        # column pool (mirrors the logic in /get_mappings).
        column_resolver   = ColumnResolver(
            all_columns_flat,
            target_schema=target_schema,
            tables_meta=tables_meta,
        )
        mapped_dict, _, _ = column_resolver.resolve(pd.DataFrame([rule_obj]), weights)
        suggestions       = [mapped_dict.get(e, "") for e in entities]
    else:
        resolver       = ColumnResolver(all_columns_flat, target_schema=None)
        rule_mapped, _, _ = resolver.resolve_for_rule(rule_obj, tables_meta, weights)
        suggestions    = [rule_mapped.get(e, "") for e in entities]
    return {"suggested_columns": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_code
# ─────────────────────────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    session_id:   str
    pyspark_code: str
    rule_name:    str


@app.post("/execute_code")
async def execute_code(req: ExecuteRequest):
    try:
        session = DATA_STORE.get(req.session_id)
        if not session:
            return {"status": "error", "error": "Invalid session"}

        clean_code = _strip_id_column_assignment(req.pyspark_code)
        id_column  = session.get("id_column")
        session["executed_rules"].add(req.rule_name)

        if not session["is_multi_table"]:
            local_vars = {"df": session["df"], "id_column": id_column}
            exec(clean_code, local_vars)
            result = local_vars.get("result", {})
            session["last_passed_df"] = local_vars.get("passed_df")
            session["last_failed_df"] = local_vars.get("failed_df")
            session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
            metrics       = session["rule_metrics"]
            avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
            session["result"][req.rule_name]    = result
            session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')
            try:
                rag = get_or_create_rag(req.session_id)
                rag.update_index(session)
            except Exception as e:
                print(f"⚠️ RAG update failed: {e}")
            return {
                "status":         "success",
                "result":         result,
                "rules_executed": len(session["executed_rules"]),
                "avg_pass_rate":  round(avg_pass_rate, 4),
            }

        dfs        = session["dfs"]
        table      = session.get("table", " ")
        local_vars = {
            "id_column": id_column,
            "df":        dfs[table] if table != " " else next(iter(dfs.values())),
            "dfs":       dfs,
        }
        for sheet_name, spark_df in dfs.items():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sheet_name)
            local_vars[f"df_{safe_name}"] = spark_df

        exec(clean_code, local_vars)

        result    = local_vars.get("result", {})
        passed_df = local_vars.get("passed_df")
        failed_df = local_vars.get("failed_df")
        if passed_df is not None:
            session["last_passed_df"] = passed_df
        if failed_df is not None:
            session["last_failed_df"] = failed_df

        session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
        metrics       = session["rule_metrics"]
        avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
        session["result"][req.rule_name]    = result
        session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')

        try:
            rag = get_or_create_rag(req.session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return {
            "status":         "success",
            "result":         result,
            "rules_executed": len(session["executed_rules"]),
            "avg_pass_rate":  round(avg_pass_rate, 4),
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /add_rule
# ─────────────────────────────────────────────────────────────────────────────
class RuleInput(BaseModel):
    session_id:    str
    name:          str
    description:   str
    business_rule: str
    complexity:    str
    category:      str


@app.post("/add_rule")
async def add_rule(payload: RuleInput):
    session = DATA_STORE.get(payload.session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]
    new_rule = {
        "name":          payload.name,
        "description":   payload.description,
        "business_rule": payload.business_rule,
        "complexity":    payload.complexity,
        "category":      payload.category,
    }

    pool = (
        [c for meta in session["tables_meta"].values() for c in meta["columns"]]
        if session["is_multi_table"] else session["columns"]
    )

    # Entity extraction at add-time: dataset columns directly (no two-hop)
    column_resolver      = ColumnResolver(pool, target_schema=None)
    entities_output      = column_resolver.extract_entity_and_conversion(new_rule)
    new_rule["entities"] = [e["entity"] for e in entities_output]

    for col_name in rules_df.columns:
        if col_name not in new_rule:
            new_rule[col_name] = None

    new_row = pd.DataFrame([new_rule])
    for col_name in new_row.columns:
        if col_name not in rules_df.columns:
            rules_df[col_name] = None

    session["rules_df"] = pd.concat(
        [rules_df, new_row[rules_df.columns]], ignore_index=True
    )

    try:
        rag = get_or_create_rag(payload.session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "message": "Rule added successfully",
        "rule":    new_rule,
        "rules":   session["rules_df"].to_dict(orient="records"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /recommend_rules
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/recommend_rules")
async def recommend_rules(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}
    ai_rules = client.generate_ai_rules(session["schema"], session["rules_df"]["business_rule"].tolist())
    return {"recommended_rules": ai_rules}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_remediation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_remediation")
async def generate_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    rule = payload.get("rule") or {}
    failed_ids = payload.get("failed_ids", [])
    failed_count = payload.get("failed_count", 0)
    mapped_dict = session.get("mapped_dict", {})
    id_column = session.get("id_column")
    failed_records_context = _build_failed_records_context(
        failed_df=session.get("last_failed_df"),
        rule=rule,
        mapped_dict=mapped_dict,
        id_column=id_column,
        failed_ids=failed_ids,
    )

    suggestions = client.generate_remediation(
        rule,
        mapped_dict,
        failed_ids,
        failed_count,
        failed_records_context=failed_records_context,
    )
    return {
        "suggestions": suggestions,
        "failed_records_context": failed_records_context,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /generate_remediation_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_remediation_code")
async def generate_remediation_code(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    failed_ids  = payload.get("failed_ids", [])
    id_column   = session.get("id_column")
    logic       = payload.get("logic")
    rule        = payload.get("rule") or {}
    remediation = payload.get("remediation") or {}
    if logic and not remediation:
        remediation = {
            "title": "Custom remediation",
            "logic": logic,
            "action_type": "custom",
            "target_columns": [],
        }
    logic = remediation.get("logic") or logic
    mapped_dict = session.get("mapped_dict", {})
    failed_records_context = _build_failed_records_context(
        failed_df=session.get("last_failed_df"),
        rule=rule,
        mapped_dict=mapped_dict,
        id_column=id_column,
        failed_ids=failed_ids,
    )

    if not failed_ids:
        return {"error": "No failed IDs provided. Remediation code must target failed records only."}
    if not id_column:
        return {"error": "No ID column found in session. Execute the rule before generating remediation code."}

    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}
        try:
            return client.generate_remediation_code(
                df,
                logic,
                mapped_dict,
                failed_ids,
                id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}

    dfs             = session["dfs"]
    tables_meta     = session["tables_meta"]
    involved_tables = _resolve_involved_tables_for_rule(session, rule, payload)

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        df  = dfs.get(tbl)
        if df is None:
            return {"error": f"Table '{tbl}' not found in session"}
        try:
            return client.generate_remediation_code(
                df,
                logic,
                mapped_dict,
                failed_ids,
                id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}
    else:
        try:
            return client.generate_remediation_code_multi(
                dfs=dfs, involved_tables=involved_tables,
                tables_meta=tables_meta, remediation_logic=logic,
                mapped_dict=mapped_dict, failed_ids=failed_ids, id_column=id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_remediation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/execute_remediation")
async def execute_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    code       = payload.get("pyspark_code")
    failed_ids = payload.get("failed_ids", [])
    id_column  = session.get("id_column")

    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}
        try:
            from pyspark.sql.functions import col as spark_col
            local_vars = {"df": df}
            exec(code, local_vars)
            remediated_df = local_vars.get("df")
            if remediated_df is None:
                return {"error": "Remediation code did not return df"}
            if id_column and id_column in df.columns and failed_ids:
                rows_affected = remediated_df.filter(spark_col(id_column).isin(failed_ids)).count()
                preview_df    = remediated_df.filter(spark_col(id_column).isin(failed_ids)).limit(10)
            else:
                rows_affected = abs(remediated_df.count() - df.count())
                preview_df    = remediated_df.limit(10)
            preview = _sanitize_for_json(preview_df.toPandas().to_dict(orient="records"))
            session["remediated_df"] = remediated_df
            session.setdefault("remediation_log", []).append({
                "logic": payload.get("logic", ""), "rows_affected": rows_affected, "failed_ids": failed_ids,
            })
            try:
                rag = get_or_create_rag(payload.session_id)
                rag.update_index(session)
            except Exception as e:
                print(f"⚠️ RAG update failed: {e}")
            return {"rows_affected": rows_affected, "preview": preview, "audit": session["remediation_log"][-1]}
        except Exception as e:
            return {"error": str(e)}

    dfs = session["dfs"]
    try:
        from pyspark.sql.functions import col as spark_col
        rule = payload.get("rule") or {}
        involved_tables = _resolve_involved_tables_for_rule(session, rule, payload)
        table = payload.get("table") or session.get("table")
        if not table and len(involved_tables) == 1:
            table = involved_tables[0]
        if table and table not in dfs:
            return {"error": f"Table '{table}' not found in session"}

        primary_df = dfs[table] if table else next(iter(dfs.values()))
        local_vars = {
            "id_column": id_column,
            "df":        primary_df,
            "dfs":       dfs,
        }
        for sheet_name, spark_df in dfs.items():
            local_vars[f"df_{re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)}"] = spark_df

        exec(code, local_vars)
        remediated_df = local_vars.get("df")
        if remediated_df is None:
            return {"error": "Remediation code did not return df"}

        if id_column and failed_ids and id_column in remediated_df.columns:
            rows_affected = remediated_df.filter(spark_col(id_column).isin(failed_ids)).count()
            preview_df    = remediated_df.filter(spark_col(id_column).isin(failed_ids)).limit(10)
        else:
            rows_affected = remediated_df.count()
            preview_df    = remediated_df.limit(10)

        preview = _sanitize_for_json(preview_df.toPandas().to_dict(orient="records"))

        if table and local_vars.get("df") is not primary_df:
            session["dfs"][table] = remediated_df

        for sheet_name in dfs.keys():
            updated = local_vars.get(f"df_{re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)}")
            if updated is not None:
                session["dfs"][sheet_name] = updated

        session["remediated_df"] = remediated_df
        session.setdefault("remediation_log", []).append({
            "logic": payload.get("logic", ""), "rows_affected": rows_affected, "failed_ids": failed_ids,"rule_name": payload.get("rule_name", ""),   # ← add this
            "timestamp":  datetime.now().strftime('%d %b %Y %H:%M:%S'),
        })
        try:
            rag = get_or_create_rag(payload.session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        return {"rows_affected": rows_affected, "preview": preview, "audit": session["remediation_log"][-1]}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /export_failed
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/export_failed")
async def export_failed(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        failed_df  = session.get("last_failed_df")
        failed_ids = payload.get("failed_ids", [])
        id_column  = session.get("id_column")
        if failed_df is None:
            return {"error": "No failed records found."}
        if not failed_ids:
            return {"error": "No failed IDs provided."}
        if not id_column or id_column not in failed_df.columns:
            return {"error": f"ID column '{id_column}' not found in dataset."}
        buffer = io.StringIO()
        failed_df.toPandas().to_csv(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /export_failed_remediations
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/export_failed_remediations")
async def export_failed_remediations(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        buffer = io.StringIO()
        session.get("remediated_df").toPandas().to_csv(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_all_codes
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_all_codes")
async def generate_all_codes(payload: dict):
    session_id = payload.get("session_id")
    session    = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id"}

    rules       = session["rules_df"].to_dict(orient="records")
    mapped_dict = session.get("mapped_dict", {})
    session.setdefault("code_cache", {})
    errors, generated = [], []

    for rule in rules:
        rule_name = rule.get("name", "")
        try:
            if not session["is_multi_table"]:
                response, dataset = client.generate_pyspark_code(
                    df=session["df"], rule=rule, mapped_dict=mapped_dict,
                )
                response["mapped_dict"] = mapped_dict
                session["id_column"]    = response.get("id_column")
                session["df"]           = dataset
            else:
                dfs             = session["dfs"]
                tables_meta     = session["tables_meta"]
                involved_tables = session.get("rule_table_map", {}).get(rule_name)
                if not involved_tables:
                    resolver = ColumnResolver([],tables_meta=tables_meta)
                    involved_tables = resolver.identify_tables_for_rule(
                        _rule_from_payload(rule), list(tables_meta.keys())
                    )
                if len(involved_tables) == 1:
                    tbl = involved_tables[0]
                    response, dataset = client.generate_pyspark_code(
                        df=dfs[tbl], rule=rule, mapped_dict=mapped_dict,
                    )
                    response["mapped_dict"] = mapped_dict
                    session["id_column"]    = response.get("id_column")
                    session["dfs"][tbl]     = dataset
                else:
                    response, updated_dfs = client.generate_pyspark_code_multi(
                        rule=rule, mapped_dict=mapped_dict,
                        involved_tables=involved_tables,
                        tables_meta=tables_meta, dfs=dfs,
                    )
                    response["mapped_dict"] = mapped_dict
                    session["id_column"]    = response.get("id_column")
                    for tbl, enriched_df in updated_dfs.items():
                        session["dfs"][tbl] = enriched_df

            session["code_cache"][rule_name] = response
            generated.append(rule_name)
        except Exception as e:
            errors.append({"rule": rule_name, "error": str(e)})
            print(f"❌ Failed to generate code for rule '{rule_name}': {e}")

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {"generated": generated, "failed": errors, "total": len(rules), "cached": len(generated)}


# ─────────────────────────────────────────────────────────────────────────────
# /enrich_rule
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/enrich_rule")
async def enrich_rule_api(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    return client.enrich_rule(payload.get("newRule"), session["schema"])


# ─────────────────────────────────────────────────────────────────────────────
# /rag_query
# RAG index automatically receives typed schema via session["schema_doc"].
# In rag.py, add session.get("schema_doc", "") as an additional indexed document.
# ─────────────────────────────────────────────────────────────────────────────
class RAGQueryRequest(BaseModel):
    session_id:   str
    question:     str
    chat_history: list = []


@app.post("/rag_query")
async def rag_query(req: RAGQueryRequest):
    session = DATA_STORE.get(req.session_id)
    if not session:
        return {"error": "Invalid session. Please upload your dataset first."}

    rag = get_or_create_rag(req.session_id)
    if not rag.is_ready():
        try:
            rag.build_index(session, req.session_id)
        except Exception as e:
            return {"error": f"RAG not ready: {str(e)}"}

    result = rag.query(req.question, chat_history=req.chat_history, session=session)
    return {
        "answer":    result["answer"],
        "intent":    result["intent"],
        "doc_types": result.get("doc_types"),
        "sources":   result["sources"],
    }
'''

import os
import sys
import re
import json

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from pyspark.sql import SparkSession
from fastapi.responses import StreamingResponse
from pyspark.sql.functions import col, monotonically_increasing_id, countDistinct
import pandas as pd
import uuid
import io
import math
from grok_client import GrokClient
from column_resolver import ColumnResolver
from datetime import datetime
from pydantic import BaseModel
from rag import get_or_create_rag, RAG_STORE
from typing import Optional

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = GrokClient()
DATA_STORE = {}


def get_spark():
    return SparkSession.builder.appName("DQ_ENGINE").getOrCreate()


def _sanitize_for_json(records: list) -> list:
    sanitized = []
    for row in records:
        clean_row = {}
        for key, value in row.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean_row[key] = None
            else:
                clean_row[key] = value
        sanitized.append(clean_row)
    return sanitized


def _sanitize_columns(pdf):
    mapping  = {}
    new_cols = []
    for c in pdf.columns:
        safe = re.sub(r"[.\s]+", "_", c)
        mapping[c] = safe
        new_cols.append(safe)
    pdf.columns = new_cols
    return pdf, mapping


def _row_to_rule(row):
    return {
        "name":          row["name"],
        "description":   row["description"],
        "business_rule": row["business_rule"],
        "complexity":    row["complexity"],
        "category":      row["category"],
    }


def _rule_from_payload(rule):
    return {
        "name":          rule.get("name", ""),
        "description":   rule.get("description", ""),
        "business_rule": rule.get("business_rule", ""),
        "complexity":    rule.get("complexity", ""),
        "category":      rule.get("category", ""),
    }


def _strip_id_column_assignment(code: str) -> str:
    cleaned_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if re.match(r"^id_column\s*=\s*['\"]", stripped):
            print(f"⚠️ Stripped LLM id_column assignment: {stripped}")
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _propagate_generated_id(joined_df, involved_tables, dfs, id_column):
    from pyspark.sql.functions import monotonically_increasing_id as _mii
    for sheet in involved_tables:
        if sheet in dfs and id_column not in dfs[sheet].columns:
            dfs[sheet] = dfs[sheet].withColumn(id_column, _mii())
            print(f"✅ Added {id_column} to sheet '{sheet}'")


def _build_schema_rag_doc(target_schema: list, length: int) -> str:
    if not target_schema:
        return ""

    lines = ["# Target Schema Reference\n"]
    lines.append("Unified target columns that all vendor data maps to.\n")

    if length == 1:
        by_category: dict = {}
        for col_def in target_schema:
            cat = col_def.get("category", "other")
            by_category.setdefault(cat, []).append(col_def)

        for category, cols in sorted(by_category.items()):
            lines.append(f"\n## Category: {category.upper()}")
            for col_def in cols:
                name  = col_def.get("name", "")
                dtype = col_def.get("type", "string")
                lines.append(f"  - {name}  [type: {dtype}]")
    else:
        by_table: dict = {}
        for col_def in target_schema:
            table = col_def.get("table_name", "")
            by_table.setdefault(table, []).append(col_def)

        for table_name, cols in sorted(by_table.items()):
            lines.append(f"\n## Table: {table_name}")

            by_category: dict = {}
            for col_def in cols:
                cat = col_def.get("category", "other")
                by_category.setdefault(cat, []).append(col_def)

            for category, cat_cols in sorted(by_category.items()):
                lines.append(f"\n  ### Category: {category.upper()}")
                for col_def in cat_cols:
                    name  = col_def.get("name", "")
                    dtype = col_def.get("type", "string")
                    lines.append(f"    - {name}  [type: {dtype}]")

    return "\n".join(lines)


def _json_safe_value(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _get_rule_columns(rule: dict, mapped_dict: dict, available_columns=None) -> list:
    rule = rule or {}
    available = set(available_columns or [])
    entities = rule.get("entities") or []
    columns = []

    for entity in entities:
        mapped = mapped_dict.get(entity)
        if mapped:
            columns.append(mapped)

    if not columns:
        rule_text = " ".join(
            str(rule.get(k, "")) for k in ("name", "description", "business_rule")
        ).lower()
        for entity, mapped in mapped_dict.items():
            if str(entity).lower() in rule_text or str(mapped).lower() in rule_text:
                columns.append(mapped)

    if not columns:
        columns = list(mapped_dict.values())

    deduped = []
    for column in columns:
        if column and column not in deduped and (not available or column in available):
            deduped.append(column)
    return deduped


def _build_failed_records_context(
    failed_df,
    rule: dict,
    mapped_dict: dict,
    id_column: str = None,
    failed_ids=None,
    sample_limit: int = 10,
):
    if failed_df is None:
        return {"available": False, "reason": "No failed records dataframe is available"}

    failed_ids = failed_ids or []
    df_work = failed_df
    if id_column and id_column in df_work.columns and failed_ids:
        df_work = df_work.filter(col(id_column).isin(failed_ids))

    target_columns = _get_rule_columns(rule, mapped_dict, df_work.columns)
    if not target_columns:
        target_columns = [c for c in df_work.columns if c != id_column][:8]

    selected_columns = []
    if id_column and id_column in df_work.columns:
        selected_columns.append(id_column)
    for column in target_columns:
        if column in df_work.columns and column not in selected_columns:
            selected_columns.append(column)

    try:
        scoped_count = df_work.count()
    except Exception:
        scoped_count = None

    dtype_map = dict(df_work.dtypes)
    numeric_types = ("int", "bigint", "double", "float", "decimal", "long", "short")
    column_profile = {}
    failure_patterns = []

    for column in target_columns:
        if column not in df_work.columns:
            continue

        dtype = dtype_map.get(column, "unknown")
        profile = {"dtype": dtype}

        null_count = df_work.filter(col(column).isNull()).count()
        profile["null_count"] = null_count
        if null_count:
            failure_patterns.append({
                "pattern": f"{column} is null",
                "count": null_count,
            })

        blank_count = df_work.filter(
            col(column).isNotNull() & (col(column).cast("string") == "")
        ).count()
        profile["blank_count"] = blank_count
        if blank_count:
            failure_patterns.append({
                "pattern": f"{column} is blank",
                "count": blank_count,
            })

        samples = [
            _json_safe_value(row[column])
            for row in df_work.select(column).where(col(column).isNotNull()).distinct().limit(8).collect()
        ]
        profile["sample_values"] = samples

        if any(dtype.startswith(t) for t in numeric_types):
            stats = df_work.selectExpr(
                f"min(`{column}`) as min_value",
                f"max(`{column}`) as max_value",
            ).collect()[0]
            profile["min"] = _json_safe_value(stats["min_value"])
            profile["max"] = _json_safe_value(stats["max_value"])

            negative_count = df_work.filter(col(column).cast("double") < 0).count()
            profile["negative_count"] = negative_count
            if negative_count:
                failure_patterns.append({
                    "pattern": f"{column} is negative",
                    "count": negative_count,
                })

        column_profile[column] = profile

    sample_records = []
    if selected_columns:
        sample_df = df_work.select(*selected_columns)
        dedupe_cols = [c for c in target_columns if c in selected_columns]
        if dedupe_cols:
            sample_df = sample_df.dropDuplicates(dedupe_cols)
        for row in sample_df.limit(sample_limit).collect():
            sample_records.append({
                key: _json_safe_value(value)
                for key, value in row.asDict().items()
            })

    return {
        "available": True,
        "failed_count_in_scope": scoped_count,
        "id_column": id_column,
        "failed_id_sample": failed_ids[: min(len(failed_ids), 25)],
        "target_columns": target_columns,
        "column_profile": column_profile,
        "failure_patterns": failure_patterns[:20],
        "sample_failed_records": sample_records,
    }


def _resolve_involved_tables_for_rule(session: dict, rule: dict, payload: dict) -> list:
    if payload.get("involved_tables"):
        return payload["involved_tables"]

    tables_meta = session.get("tables_meta", {})
    if not tables_meta:
        return []

    rule_name = (rule or {}).get("name", "")
    involved_tables = session.get("rule_table_map", {}).get(rule_name)
    if involved_tables:
        return involved_tables

    try:
        resolver = ColumnResolver([], tables_meta=tables_meta)
        return resolver.identify_tables_for_rule(
            _rule_from_payload(rule or {}),
            list(tables_meta.keys()),
        )
    except Exception:
        return list(tables_meta.keys())


# ─────────────────────────────────────────────────────────────────────────────
# /upload
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_files(
    dataset: UploadFile = File(...),
    rules:   UploadFile = File(...),
    schema:  Optional[UploadFile] = File(None),
):
    try:
        spark = get_spark()

        rules_df      = pd.read_excel(rules.file, engine="openpyxl")
        dataset_bytes = await dataset.read()
        excel_file    = pd.ExcelFile(io.BytesIO(dataset_bytes), engine="openpyxl")
        sheet_names   = excel_file.sheet_names

        target_schema = []
        if schema is not None:
            try:
                schema_bytes  = await schema.read()
                schema_json   = json.loads(schema_bytes.decode("utf-8"))
                target_schema = schema_json.get("target_columns", [])
                print(f"✅ Loaded target schema with {len(target_schema)} columns")
            except Exception as e:
                print(f"⚠️ Could not parse schema file: {e}")

        session_id = str(uuid.uuid4())

        # ── SINGLE TABLE ──────────────────────────────────────────────────────
        if len(sheet_names) == 1:
            raw_pdf          = pd.read_excel(excel_file, sheet_name=sheet_names[0])
            pdf, col_mapping = _sanitize_columns(raw_pdf)
            df               = spark.createDataFrame(pdf)

            resolver    = ColumnResolver(list(df.columns), target_schema=None)
            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            DATA_STORE[session_id] = {
                "is_multi_table":    False,
                "df":                df,
                "rules_df":          rules_df,
                "columns":           list(df.columns),
                "schema":            "\n".join(df.columns),
                "col_mapping":       col_mapping,
                "target_schema":     target_schema,
                "schema_doc":        _build_schema_rag_doc(target_schema, len(sheet_names)),
                "schema_to_dataset": {},   # populated by /get_mappings
                "mapped_dict":       {},
                "executed_rules":    set(),
                "rule_metrics":      {},
                "result":            {},
                "timestamp":         {}
            }

            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": False,
                "columns":        list(df.columns),
                "rules":          rules_df.to_dict(orient="records"),
                "has_schema":     bool(target_schema),
                "schema_columns": [c["name"] for c in target_schema],
            }

        # ── MULTI TABLE ───────────────────────────────────────────────────────
        else:
            dfs              = {}
            tables_meta      = {}
            all_col_mappings = {}

            for sheet in sheet_names:
                raw_pdf                 = pd.read_excel(excel_file, sheet_name=sheet)
                pdf, col_mapping        = _sanitize_columns(raw_pdf)
                spark_df                = spark.createDataFrame(pdf)
                dfs[sheet]              = spark_df
                cols                    = list(spark_df.columns)
                tables_meta[sheet]      = {"columns": cols}
                all_col_mappings[sheet] = col_mapping

            all_columns_flat = []
            for sheet, meta in tables_meta.items():
                all_columns_flat.extend(meta["columns"])

            resolver    = ColumnResolver(all_columns_flat, target_schema=None)
            column_list = []
            for _, row in rules_df.iterrows():
                rule   = _row_to_rule(row)
                output = resolver.extract_entity_and_conversion(rule)
                column_list.append([j["entity"] for j in output])
            rules_df["entities"] = column_list

            schema_lines = [
                f"[{sheet}]: " + ", ".join(meta["columns"])
                for sheet, meta in tables_meta.items()
            ]

            DATA_STORE[session_id] = {
                "is_multi_table":    True,
                "dfs":               dfs,
                "rules_df":          rules_df,
                "tables_meta":       tables_meta,
                "schema":            "\n".join(schema_lines),
                "col_mappings":      all_col_mappings,
                "target_schema":     target_schema,
                "schema_doc":        _build_schema_rag_doc(target_schema, len(sheet_names)),
                "schema_to_dataset": {},   # populated by /get_mappings
                "mapped_dict":       {},
                "rule_table_map":    {},
                "executed_rules":    set(),
                "rule_metrics":      {},
                "result":            {},
                "timestamp":         {}
            }

            try:
                rag = get_or_create_rag(session_id)
                rag.build_index(DATA_STORE[session_id], session_id)
            except Exception as e:
                print(f"⚠️ RAG index build failed: {e}")

            return {
                "session_id":     session_id,
                "is_multi_table": True,
                "tables":         tables_meta,
                "columns":        all_columns_flat,
                "rules":          rules_df.to_dict(orient="records"),
                "has_schema":     bool(target_schema),
                "schema_columns": [c["name"] for c in target_schema],
            }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /get_mappings
# mapped_dict      = entity → schema_column
# schema_to_dataset = schema_column → dataset_column
# The dataset is renamed schema_col names before any LLM code generation call.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/get_mappings")
async def get_mappings(payload: dict):
    session_id = payload.get("session_id")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df      = session["rules_df"]
    target_schema = session.get("target_schema", [])

    # ── SINGLE TABLE ─────────────────────────────────────────────────────────
    if not session["is_multi_table"]:
        column_resolver = ColumnResolver(session["columns"], target_schema=target_schema)
        mapped_dict, ranked_scores, schema_to_dataset = column_resolver.resolve(rules_df, weights)

        session["mapped_dict"]       = mapped_dict        # entity → schema_col
        session["schema_to_dataset"] = schema_to_dataset  # schema_col → dataset_col
        session["ranked_scores"]     = ranked_scores

        try:
            rag = get_or_create_rag(session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        print("mapped_dict (entity→schema):", mapped_dict)
        print("schema_to_dataset:", schema_to_dataset)
        return {
            "mapped_dict":        mapped_dict,
            "schema_to_dataset":  schema_to_dataset,
            "ranked_scores":      ranked_scores,
        }

    # ── MULTI TABLE ───────────────────────────────────────────────────────────
    tables_meta      = session["tables_meta"]
    all_columns_flat = [c for meta in tables_meta.values() for c in meta["columns"]]

    mapped_dict       = {}
    schema_to_dataset = {}
    ranked_scores     = {}
    rule_table_map    = {}

    if target_schema:
        print("\n🔀 Multi-table + schema: running scoped two-hop mapping")
        column_resolver = ColumnResolver(all_columns_flat, target_schema=target_schema, tables_meta=tables_meta)
        mapped_dict, ranked_scores, schema_to_dataset = column_resolver.resolve(rules_df, weights)

        for _, row in rules_df.iterrows():
            rule      = _row_to_rule(row)
            rule_name = rule["name"]
            try:
                involved = column_resolver.identify_tables_for_rule(rule, list(tables_meta.keys()))
                rule_table_map[rule_name] = involved
            except Exception as e:
                print(f"❌ Table identification failed for '{rule_name}': {e}")
                rule_table_map[rule_name] = list(tables_meta.keys())

    else:
        resolver = ColumnResolver([])
        for _, row in rules_df.iterrows():
            rule      = _row_to_rule(row)
            rule_name = rule["name"]
            print(f"\n🔍 Processing rule: {rule_name}")
            try:
                rule_mapped, rule_ranked, involved_tables = resolver.resolve_for_rule(
                    rule, tables_meta, weights
                )
                mapped_dict.update(rule_mapped)
                ranked_scores.update(rule_ranked)
                rule_table_map[rule_name] = involved_tables
            except Exception as e:
                print(f"❌ Failed mapping for rule '{rule_name}': {e}")
                rule_table_map[rule_name] = list(tables_meta.keys())
        # No separate schema: identity mapping
        schema_to_dataset = {v: v for v in mapped_dict.values()}

    print("mapped_dict (entity→schema):", mapped_dict)
    print("schema_to_dataset:", schema_to_dataset)

    session["mapped_dict"]       = mapped_dict
    session["schema_to_dataset"] = schema_to_dataset
    session["ranked_scores"]     = ranked_scores
    session["rule_table_map"]    = rule_table_map

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "mapped_dict":        mapped_dict,
        "schema_to_dataset":  schema_to_dataset,
        "ranked_scores":      ranked_scores,
        "rule_table_map":     rule_table_map,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_schema
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/suggest_schema")
async def suggest_schema(payload: dict):
    session_id = payload.get("session_id")
    session    = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    if not session["is_multi_table"]:
        suggested = [
            {"name": col, "type": "string", "category": "default"}
            for col in session.get("columns", [])
        ]
    else:
        suggested = []
        for table_name, meta in session.get("tables_meta", {}).items():
            for col in meta.get("columns", []):
                suggested.append({"name": col, "type": "string", "category": table_name})

    return {"suggested_schema": suggested}


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPER: rename dataset columns → schema column names
# ─────────────────────────────────────────────────────────────────────────────
def _apply_schema_rename(df, schema_to_dataset: dict):
    """
    schema_to_dataset : { schema_col: dataset_col }
    Inverts to { dataset_col: schema_col } and renames via withColumnRenamed.
    No-op when mapping is identity (no target schema).
    """
    dataset_to_schema = {v: k for k, v in schema_to_dataset.items() if v != k}
    if not dataset_to_schema:
        return df

    renamed = df
    for dataset_col, schema_col in dataset_to_schema.items():
        if dataset_col in renamed.columns:
            renamed = renamed.withColumnRenamed(dataset_col, schema_col)
    return renamed


# ─────────────────────────────────────────────────────────────────────────────
# /generate_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_code")
async def generate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id. Please upload again."}

    rule_name  = rule.get("name", "")
    code_cache = session.get("code_cache", {})

    if rule_name in code_cache:
        print(f"✅ Cache hit for rule '{rule_name}' — skipping LLM")
        return code_cache[rule_name]

    # mapped_dict       = entity → schema_column
    # schema_to_dataset = schema_column → dataset_column
    mapped_dict       = session.get("mapped_dict", {})
    schema_to_dataset = session.get("schema_to_dataset", {})

    if not session["is_multi_table"]:
        # Rename dataset columns → schema names so LLM code uses schema column names
        
        renamed_df = _apply_schema_rename(session["df"], schema_to_dataset)
        response, dataset = client.generate_pyspark_code(
            df=renamed_df,
            rule=rule,
            mapped_dict=mapped_dict,
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        session["df"]                 = dataset
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return response

    dfs             = session["dfs"]
    tables_meta     = session["tables_meta"]
    rule_table_map  = session.get("rule_table_map", {})
    involved_tables = rule_table_map.get(rule_name)

    if not involved_tables:
        resolver = ColumnResolver([], tables_meta=tables_meta)
        involved_tables = resolver.identify_tables_for_rule(
            _rule_from_payload(rule), list(tables_meta.keys())
        )

    if len(involved_tables) == 1:
        tbl        = involved_tables[0]
        renamed_df = _apply_schema_rename(dfs[tbl], schema_to_dataset)
        response, dataset = client.generate_pyspark_code(
            df=renamed_df, rule=rule, mapped_dict=mapped_dict,
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        session["dfs"][tbl]           = dataset
    else:
        renamed_dfs = {
            tbl: _apply_schema_rename(dfs[tbl], schema_to_dataset)
            for tbl in involved_tables if tbl in dfs
        }
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule, mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta,
            dfs={**dfs, **renamed_dfs},
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df

    session.setdefault("code_cache", {})[rule_name] = response

    try:
        rag = get_or_create_rag(payload.get("session_id"))
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return response


# ─────────────────────────────────────────────────────────────────────────────
# /regenerate_code
# User edits SCHEMA column names (mapped_dict values), not dataset columns.
# schema_to_dataset is unchanged — only mapped_dict overrides are applied.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/regenerate_code")
async def regenerate_code(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    columns    = payload.get("columns")   # user-edited SCHEMA column names
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    mapped_dict = dict(session.get("mapped_dict", {}))
    entities    = rule.get("entities", [])

    for e, schema_col in zip(entities, columns):
        mapped_dict[e] = schema_col

    session["mapped_dict"] = mapped_dict

    schema_to_dataset = dict(session.get("schema_to_dataset", {}))

    # ── NEW: resolve any schema cols not yet in schema_to_dataset ─────────────
    # This happens when user picks a schema col that was never mapped in hop2.
    # We run a targeted hop2 pass for only the unmapped schema cols and
    # append the results into schema_to_dataset before the pipeline runs.
    unmapped_schema_cols = [
        schema_col for schema_col in columns
        if schema_col and schema_col not in schema_to_dataset
    ]

    if unmapped_schema_cols:
        print(f"🔗 New schema cols need hop2 mapping: {unmapped_schema_cols}")
        try:
            if session["is_multi_table"]:
                tables_meta      = session["tables_meta"]
                all_columns_flat = [
                    c for meta in tables_meta.values()
                    for c in meta["columns"]
                ]
                resolver = ColumnResolver(all_columns_flat, target_schema=session.get("target_schema", []))
            else:
                resolver = ColumnResolver(session["columns"], target_schema=session.get("target_schema", []))

            target_schema = session.get("target_schema", [])

            for schema_col in unmapped_schema_cols:
                # Build a synthetic single-rule df to resolve this one schema col
                meta = next(
                    (c for c in target_schema if c.get("name") == schema_col), {}
                )
                synthetic_rule = {
                    "name":          schema_col,
                    "description":   (
                        f"Map target schema column '{schema_col}' "
                        f"(type: {meta.get('type','?')}, "
                        f"category: {meta.get('category','?')}) to dataset"
                    ),
                    "business_rule": (
                        f"Find the dataset column that corresponds to '{schema_col}'"
                    ),
                    "complexity":    "simple",
                    "category":      meta.get("category", "general"),
                }

                import pandas as pd
                synthetic_df = pd.DataFrame([{
                    "name":          synthetic_rule["name"],
                    "description":   synthetic_rule["description"],
                    "business_rule": synthetic_rule["business_rule"],
                    "complexity":    synthetic_rule["complexity"],
                    "category":      synthetic_rule["category"],
                }])

                # For multi-table: scope the resolver columns to the
                # table this schema col belongs to (if table_name is set)
                if session["is_multi_table"] and meta.get("table_name"):
                    tbl_cols = session["tables_meta"].get(
                        meta["table_name"], {}
                    ).get("columns", all_columns_flat)
                    resolver.dataset_columns   = tbl_cols
                    resolver.column_embeddings = resolver.model.encode(tbl_cols)

                hop2_raw = resolver.extract_entity_and_conversion(synthetic_rule)
                mapped, _ = resolver._score_entities(hop2_raw, weights)

                dataset_col = mapped.get(schema_col)
                if dataset_col:
                    schema_to_dataset[schema_col] = dataset_col
                    print(f"  ✅ New hop2: '{schema_col}' → '{dataset_col}'")
                else:
                    # Fallback: identity mapping (schema col name == dataset col)
                    schema_to_dataset[schema_col] = schema_col
                    print(f"  ⚠️ No hop2 match for '{schema_col}', using identity")

        except Exception as e:
            print(f"❌ Hop2 resolution failed for unmapped schema cols: {e}")
            # Fallback: identity map all unmapped cols so pipeline doesn't break
            for schema_col in unmapped_schema_cols:
                if schema_col not in schema_to_dataset:
                    schema_to_dataset[schema_col] = schema_col

        # Persist the updated schema_to_dataset back to session
        session["schema_to_dataset"] = schema_to_dataset
        print(f"📦 Updated schema_to_dataset: {schema_to_dataset}")
    # ── END new hop2 resolution ───────────────────────────────────────────────

    if not session["is_multi_table"]:
        renamed_df = _apply_schema_rename(session["df"], schema_to_dataset)
        response, dataset = client.generate_pyspark_code(
            df=renamed_df, rule=rule, mapped_dict=mapped_dict
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        session["df"]                 = dataset
        session.setdefault("code_cache", {})[rule.get("name", "")] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return response

    dfs          = session["dfs"]
    # original_dfs = session["original_dfs"]
    tables_meta  = session["tables_meta"]
    rule_name    = rule.get("name", "")

    def _find_tables_for_schema_cols(schema_cols, schema_to_dataset, tables_meta):
        involved = set()
        for schema_col in schema_cols:
            dataset_col = schema_to_dataset.get(schema_col, schema_col)
            for tbl, meta in tables_meta.items():
                if dataset_col in meta.get("columns", []):
                    involved.add(tbl)
                    break
            if not involved or schema_col == dataset_col:
                for tbl, meta in tables_meta.items():
                    if schema_col in meta.get("columns", []):
                        involved.add(tbl)
                        break
        return list(involved)

    rule_schema_cols = [mapped_dict[e] for e in entities if e in mapped_dict]

    involved_tables = _find_tables_for_schema_cols(
        rule_schema_cols, schema_to_dataset, tables_meta
    )

    if not involved_tables:
        involved_tables = session.get("rule_table_map", {}).get(
            rule_name, list(tables_meta.keys())
        )

    print(f"🔁 regenerate_code: rule='{rule_name}', involved_tables={involved_tables}")

    if len(involved_tables) == 1:
        tbl        = involved_tables[0]
        renamed_df = _apply_schema_rename(dfs[tbl], schema_to_dataset)
        response, dataset = client.generate_pyspark_code(
            df=renamed_df, rule=rule, mapped_dict=mapped_dict
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        session["dfs"][tbl]           = dataset
        session["table"]              = tbl
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return response
    else:
        renamed_dfs = {
            tbl: _apply_schema_rename(dfs[tbl], schema_to_dataset)
            for tbl in involved_tables if tbl in dfs
        }
        response, updated_dfs = client.generate_pyspark_code_multi(
            rule=rule, mapped_dict=mapped_dict,
            involved_tables=involved_tables,
            tables_meta=tables_meta,
            dfs={**dfs, **renamed_dfs},
        )
        response["mapped_dict"]       = mapped_dict
        response["schema_to_dataset"] = schema_to_dataset
        session["id_column"]          = response.get("id_column")
        for tbl, enriched_df in updated_dfs.items():
            session["dfs"][tbl] = enriched_df
        session.setdefault("code_cache", {})[rule_name] = response

        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        return response


# ─────────────────────────────────────────────────────────────────────────────
# /suggest_columns
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/suggest_columns")
async def suggest_columns(payload: dict):
    session_id = payload.get("session_id")
    rule       = payload.get("rule")
    weights    = payload.get("weights")

    session = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    entities             = rule.get("entities", [])
    rule_obj             = _rule_from_payload(rule)
    rule_obj["entities"] = entities
    target_schema        = session.get("target_schema", [])

    if not session["is_multi_table"]:
        column_resolver   = ColumnResolver(session["columns"], target_schema=target_schema)
        mapped_dict, _, _ = column_resolver.resolve(pd.DataFrame([rule_obj]), weights)
        suggestions       = [mapped_dict.get(e, "") for e in entities]
        return {"suggested_columns": suggestions}

    tables_meta      = session["tables_meta"]
    all_columns_flat = [c for meta in tables_meta.values() for c in meta["columns"]]

    if target_schema:
        column_resolver   = ColumnResolver(
            all_columns_flat, target_schema=target_schema, tables_meta=tables_meta
        )
        mapped_dict, _, _ = column_resolver.resolve(pd.DataFrame([rule_obj]), weights)
        suggestions       = [mapped_dict.get(e, "") for e in entities]
    else:
        resolver          = ColumnResolver(all_columns_flat, target_schema=None)
        rule_mapped, _, _ = resolver.resolve_for_rule(rule_obj, tables_meta, weights)
        suggestions       = [rule_mapped.get(e, "") for e in entities]

    return {"suggested_columns": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_code
# ─────────────────────────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    session_id:   str
    pyspark_code: str
    rule_name:    str


@app.post("/execute_code")
async def execute_code(req: ExecuteRequest):
    try:
        session = DATA_STORE.get(req.session_id)
        if not session:
            return {"status": "error", "error": "Invalid session"}

        clean_code = _strip_id_column_assignment(req.pyspark_code)
        id_column  = session.get("id_column")
        session["executed_rules"].add(req.rule_name)

        if not session["is_multi_table"]:
            local_vars = {"df": session["df"], "id_column": id_column}
            exec(clean_code, local_vars)
            result    = local_vars.get("result", {})
            session["last_passed_df"] = local_vars.get("passed_df")
            session["last_failed_df"] = local_vars.get("failed_df")
            session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
            metrics       = session["rule_metrics"]
            avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
            session["result"][req.rule_name]    = result
            session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')
            try:
                rag = get_or_create_rag(req.session_id)
                rag.update_index(session)
            except Exception as e:
                print(f"⚠️ RAG update failed: {e}")
            return {
                "status":         "success",
                "result":         result,
                "rules_executed": len(session["executed_rules"]),
                "avg_pass_rate":  round(avg_pass_rate, 4),
            }

        dfs        = session["dfs"]
        table      = session.get("table", " ")
        local_vars = {
            "id_column": id_column,
            "df":        dfs[table] if table != " " else next(iter(dfs.values())),
            "dfs":       dfs,
        }
        for sheet_name, spark_df in dfs.items():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sheet_name)
            local_vars[f"df_{safe_name}"] = spark_df

        exec(clean_code, local_vars)

        result    = local_vars.get("result", {})
        passed_df = local_vars.get("passed_df")
        failed_df = local_vars.get("failed_df")
        if passed_df is not None:
            session["last_passed_df"] = passed_df
        if failed_df is not None:
            session["last_failed_df"] = failed_df

        session["rule_metrics"][req.rule_name] = result.get("pass_rate", 0)
        metrics       = session["rule_metrics"]
        avg_pass_rate = sum(metrics.values()) / len(metrics) if metrics else 0.0
        session["result"][req.rule_name]    = result
        session["timestamp"][req.rule_name] = datetime.now().strftime('%d %b %Y %H:%M:%S')

        try:
            rag = get_or_create_rag(req.session_id)
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")

        return {
            "status":         "success",
            "result":         result,
            "rules_executed": len(session["executed_rules"]),
            "avg_pass_rate":  round(avg_pass_rate, 4),
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /add_rule
# ─────────────────────────────────────────────────────────────────────────────
class RuleInput(BaseModel):
    session_id:    str
    name:          str
    description:   str
    business_rule: str
    complexity:    str
    category:      str


@app.post("/add_rule")
async def add_rule(payload: RuleInput):
    session = DATA_STORE.get(payload.session_id)
    if not session:
        return {"error": "Invalid session"}

    rules_df = session["rules_df"]
    new_rule = {
        "name":          payload.name,
        "description":   payload.description,
        "business_rule": payload.business_rule,
        "complexity":    payload.complexity,
        "category":      payload.category,
    }

    pool = (
        [c for meta in session["tables_meta"].values() for c in meta["columns"]]
        if session["is_multi_table"] else session["columns"]
    )

    column_resolver      = ColumnResolver(pool, target_schema=None)
    entities_output      = column_resolver.extract_entity_and_conversion(new_rule)
    new_rule["entities"] = [e["entity"] for e in entities_output]

    for col_name in rules_df.columns:
        if col_name not in new_rule:
            new_rule[col_name] = None

    new_row = pd.DataFrame([new_rule])
    for col_name in new_row.columns:
        if col_name not in rules_df.columns:
            rules_df[col_name] = None

    session["rules_df"] = pd.concat(
        [rules_df, new_row[rules_df.columns]], ignore_index=True
    )

    try:
        rag = get_or_create_rag(payload.session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {
        "message": "Rule added successfully",
        "rule":    new_rule,
        "rules":   session["rules_df"].to_dict(orient="records"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /recommend_rules
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/recommend_rules")
async def recommend_rules(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}
    ai_rules = client.generate_ai_rules(
        session["schema"], session["rules_df"]["business_rule"].tolist()
    )
    return {"recommended_rules": ai_rules}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_remediation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_remediation")
async def generate_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    rule = payload.get("rule") or {}
    failed_ids = payload.get("failed_ids", [])
    failed_count = payload.get("failed_count", 0)
    mapped_dict = session.get("mapped_dict", {})
    id_column = session.get("id_column")
    failed_records_context = _build_failed_records_context(
        failed_df=session.get("last_failed_df"),
        rule=rule,
        mapped_dict=mapped_dict,
        id_column=id_column,
        failed_ids=failed_ids,
    )

    suggestions = client.generate_remediation(
        rule,
        mapped_dict,
        failed_ids,
        failed_count,
        failed_records_context=failed_records_context,
    )
    return {
        "suggestions": suggestions,
        "failed_records_context": failed_records_context,
    }


# ─────────────────────────────────────────────────────────────────────────────
# /generate_remediation_code
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_remediation_code")
async def generate_remediation_code(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    failed_ids  = payload.get("failed_ids", [])
    id_column   = session.get("id_column")
    logic       = payload.get("logic")
    rule        = payload.get("rule") or {}
    remediation = payload.get("remediation") or {}
    if logic and not remediation:
        remediation = {
            "title": "Custom remediation",
            "logic": logic,
            "action_type": "custom",
            "target_columns": [],
        }
    logic = remediation.get("logic") or logic
    mapped_dict = session.get("mapped_dict", {})
    failed_records_context = _build_failed_records_context(
        failed_df=session.get("last_failed_df"),
        rule=rule,
        mapped_dict=mapped_dict,
        id_column=id_column,
        failed_ids=failed_ids,
    )

    if not failed_ids:
        return {"error": "No failed IDs provided. Remediation code must target failed records only."}
    if not id_column:
        return {"error": "No ID column found in session. Execute the rule before generating remediation code."}

    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}
        try:
            return client.generate_remediation_code(
                df,
                logic,
                mapped_dict,
                failed_ids,
                id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}

    dfs             = session["dfs"]
    tables_meta     = session["tables_meta"]
    involved_tables = _resolve_involved_tables_for_rule(session, rule, payload)

    if len(involved_tables) == 1:
        tbl = involved_tables[0]
        df  = dfs.get(tbl)
        if df is None:
            return {"error": f"Table '{tbl}' not found in session"}
        try:
            return client.generate_remediation_code(
                df,
                logic,
                mapped_dict,
                failed_ids,
                id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}
    else:
        try:
            return client.generate_remediation_code_multi(
                dfs=dfs, involved_tables=involved_tables,
                tables_meta=tables_meta, remediation_logic=logic,
                mapped_dict=mapped_dict, failed_ids=failed_ids, id_column=id_column,
                remediation=remediation,
                failed_records_context=failed_records_context,
            )
        except Exception as e:
            return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /execute_remediation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/execute_remediation")
async def execute_remediation(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    if not session:
        return {"error": "Invalid session"}

    code       = payload.get("pyspark_code")
    failed_ids = payload.get("failed_ids", [])
    id_column  = session.get("id_column")

    if not session.get("is_multi_table"):
        df = session.get("df")
        if df is None:
            return {"error": "No dataset found in session"}
        try:
            from pyspark.sql.functions import col as spark_col
            local_vars = {"df": df}
            exec(code, local_vars)
            remediated_df = local_vars.get("df")
            if remediated_df is None:
                return {"error": "Remediation code did not return df"}
            if id_column and id_column in df.columns and failed_ids:
                rows_affected = remediated_df.filter(spark_col(id_column).isin(failed_ids)).count()
                preview_df    = remediated_df.filter(spark_col(id_column).isin(failed_ids)).limit(10)
            else:
                rows_affected = remediated_df.count() #abs(remediated_df.count() - df.count())
                preview_df    = remediated_df.limit(10)
            preview = _sanitize_for_json(preview_df.toPandas().to_dict(orient="records"))
            session["remediated_df"] = remediated_df
            session.setdefault("remediation_log", []).append({
                "logic": payload.get("logic", ""), "rows_affected": rows_affected, "failed_ids": failed_ids,
            })
            try:
                rag = get_or_create_rag(payload.get("session_id"))
                rag.update_index(session)
            except Exception as e:
                print(f"⚠️ RAG update failed: {e}")
            return {"rows_affected": rows_affected, "preview": preview, "audit": session["remediation_log"][-1]}
        except Exception as e:
            return {"error": str(e)}

    dfs   = session["dfs"]
    table = session.get("table", " ")
    try:
        from pyspark.sql.functions import col as spark_col
        local_vars = {
            "id_column": id_column,
            "df":        dfs[table] if table != " " else next(iter(dfs.values())),
            "dfs":       dfs,
        }
        for sheet_name, spark_df in dfs.items():
            local_vars[f"df_{re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)}"] = spark_df

        exec(code, local_vars)
        remediated_df = local_vars.get("df")
        if remediated_df is None:
            return {"error": "Remediation code did not return df"}

        '''if id_column and failed_ids and id_column in remediated_df.columns:
            rows_affected = df.filter(spark_col(id_column).isin(failed_ids)).count()
            preview_df    = df.filter(spark_col(id_column).isin(failed_ids)).limit(10)
        else:'''
        rows_affected = remediated_df.count()
        preview_df    = remediated_df.limit(10)

        preview = _sanitize_for_json(preview_df.toPandas().to_dict(orient="records"))

        for sheet_name in dfs.keys():
            updated = local_vars.get(f"df_{re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)}")
            if updated is not None:
                session["dfs"][sheet_name] = updated

        session["remediated_df"] = remediated_df
        session.setdefault("remediation_log", []).append({
            "logic":        payload.get("logic", ""),
            "rows_affected": rows_affected,
            "failed_ids":   failed_ids,
            "rule_name":    payload.get("rule_name", ""),
            "timestamp":    datetime.now().strftime('%d %b %Y %H:%M:%S'),
        })
        try:
            rag = get_or_create_rag(payload.get("session_id"))
            rag.update_index(session)
        except Exception as e:
            print(f"⚠️ RAG update failed: {e}")
        return {"rows_affected": rows_affected, "preview": preview, "audit": session["remediation_log"][-1]}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /export_failed
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/export_failed")
async def export_failed(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        failed_df  = session.get("last_failed_df")
        failed_ids = payload.get("failed_ids", [])
        id_column  = session.get("id_column")
        if failed_df is None:
            return {"error": "No failed records found."}
        if not failed_ids:
            return {"error": "No failed IDs provided."}
        if not id_column or id_column not in failed_df.columns:
            return {"error": f"ID column '{id_column}' not found in dataset."}
        buffer = io.StringIO()
        failed_df.toPandas().to_csv(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /export_failed_remediations
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/export_failed_remediations")
async def export_failed_remediations(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    try:
        buffer = io.StringIO()
        session.get("remediated_df").toPandas().to_csv(buffer, index=False)
        buffer.seek(0)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_records.csv"}
        )
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# /generate_all_codes
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate_all_codes")
async def generate_all_codes(payload: dict):
    session_id = payload.get("session_id")
    session    = DATA_STORE.get(session_id)
    if not session:
        return {"error": "Invalid session_id"}

    rules             = session["rules_df"].to_dict(orient="records")
    mapped_dict       = session.get("mapped_dict", {})
    schema_to_dataset = session.get("schema_to_dataset", {})
    session.setdefault("code_cache", {})
    errors, generated = [], []

    for rule in rules:
        rule_name = rule.get("name", "")
        try:
            if not session["is_multi_table"]:
                renamed_df = _apply_schema_rename(session["df"], schema_to_dataset)
                response, dataset = client.generate_pyspark_code(
                    df=renamed_df, rule=rule, mapped_dict=mapped_dict,
                )
                response["mapped_dict"]       = mapped_dict
                response["schema_to_dataset"] = schema_to_dataset
                session["id_column"]          = response.get("id_column")
                session["df"]                 = dataset
            else:
                dfs             = session["dfs"]
                tables_meta     = session["tables_meta"]
                involved_tables = session.get("rule_table_map", {}).get(rule_name)
                if not involved_tables:
                    resolver = ColumnResolver([], tables_meta=tables_meta)
                    involved_tables = resolver.identify_tables_for_rule(
                        _rule_from_payload(rule), list(tables_meta.keys())
                    )
                if len(involved_tables) == 1:
                    tbl        = involved_tables[0]
                    renamed_df = _apply_schema_rename(dfs[tbl], schema_to_dataset)
                    response, dataset = client.generate_pyspark_code(
                        df=renamed_df, rule=rule, mapped_dict=mapped_dict,
                    )
                    response["mapped_dict"]       = mapped_dict
                    response["schema_to_dataset"] = schema_to_dataset
                    session["id_column"]          = response.get("id_column")
                    session["dfs"][tbl]           = dataset
                else:
                    renamed_dfs = {
                        tbl: _apply_schema_rename(dfs[tbl], schema_to_dataset)
                        for tbl in involved_tables if tbl in dfs
                    }
                    response, updated_dfs = client.generate_pyspark_code_multi(
                        rule=rule, mapped_dict=mapped_dict,
                        involved_tables=involved_tables,
                        tables_meta=tables_meta,
                        dfs={**dfs, **renamed_dfs},
                    )
                    response["mapped_dict"]       = mapped_dict
                    response["schema_to_dataset"] = schema_to_dataset
                    session["id_column"]          = response.get("id_column")
                    for tbl, enriched_df in updated_dfs.items():
                        session["dfs"][tbl] = enriched_df

            session["code_cache"][rule_name] = response
            generated.append(rule_name)
        except Exception as e:
            errors.append({"rule": rule_name, "error": str(e)})
            print(f"❌ Failed to generate code for rule '{rule_name}': {e}")

    try:
        rag = get_or_create_rag(session_id)
        rag.update_index(session)
    except Exception as e:
        print(f"⚠️ RAG update failed: {e}")

    return {"generated": generated, "failed": errors, "total": len(rules), "cached": len(generated)}


# ─────────────────────────────────────────────────────────────────────────────
# /enrich_rule
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/enrich_rule")
async def enrich_rule_api(payload: dict):
    session = DATA_STORE.get(payload.get("session_id"))
    return client.enrich_rule(payload.get("newRule"), session["schema"])


# ─────────────────────────────────────────────────────────────────────────────
# /rag_query
# ─────────────────────────────────────────────────────────────────────────────
class RAGQueryRequest(BaseModel):
    session_id:   str
    question:     str
    chat_history: list = []


@app.post("/rag_query")
async def rag_query(req: RAGQueryRequest):
    session = DATA_STORE.get(req.session_id)
    if not session:
        return {"error": "Invalid session. Please upload your dataset first."}

    rag = get_or_create_rag(req.session_id)
    if not rag.is_ready():
        try:
            rag.build_index(session, req.session_id)
        except Exception as e:
            return {"error": f"RAG not ready: {str(e)}"}

    result = rag.query(req.question, chat_history=req.chat_history, session=session)
    return {
        "answer":    result["answer"],
        "intent":    result["intent"],
        "doc_types": result.get("doc_types"),
        "sources":   result["sources"],
    }
