import os
import re
from typing import Any, Dict, List

DQ_CHECKS_FILE = os.path.join(os.path.dirname(__file__), "dq_checks.py")


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", (value or "").strip().lower()).strip("_") or "dq_rule"


def build_function_name(rule_name: str) -> str:
    return f"dq_{slugify(rule_name)}"


# 🔥 NEW: LLM-based function generator
def generate_function_with_llm(
    client,
    rule: Dict[str, Any],
    schema_fields: List[Dict[str, Any]],
    dataset_columns: List[str],
) -> str:

    prompt = f"""
You are an expert PySpark developer.

Generate a COMPLETE PySpark function for data quality validation.

STRICT REQUIREMENTS:
- Function name must be: dq_{slugify(rule.get("name"))}
- Input signature:
    def FUNCTION_NAME(df, fields, parameters, id_column):
- Must return:
    passed_df, failed_df, result

result format:
{{
    "rule": "<rule_name>",
    "passed_count": int,
    "failed_count": int,
    "pass_rate": float,
    "failed_ids": list
}}

RULE:
Name: {rule.get("name")}
Description: {rule.get("description")}
Business Rule: {rule.get("business_rule")}

SCHEMA:
{schema_fields}

DATASET COLUMNS:
{dataset_columns}

IMPORTANT:
- Use ONLY PySpark
- Handle NULLs properly
- Handle edge cases
- Use efficient Spark logic
- DO NOT include explanations
- OUTPUT ONLY PYTHON CODE
"""

    response = client.generate_code(prompt)
    return response.strip()


def ensure_function_written(function_name: str, function_code: str) -> None:
    header = "# Auto-generated DQ check functions.\n\n"

    if not os.path.exists(DQ_CHECKS_FILE):
        with open(DQ_CHECKS_FILE, "w", encoding="utf-8") as f:
            f.write(header)

    with open(DQ_CHECKS_FILE, "r", encoding="utf-8") as f:
        existing = f.read()

    begin = f"# BEGIN GENERATED: {function_name}"
    end = f"# END GENERATED: {function_name}"

    block = f"{begin}\n{function_code}\n{end}\n"

    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
        re.DOTALL,
    )

    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        updated = existing.rstrip() + "\n\n" + block

    with open(DQ_CHECKS_FILE, "w", encoding="utf-8") as f:
        f.write(updated)


def build_execution_code(
    function_code: str,
    function_name: str,
    fields: List[str],
    parameters: Dict[str, Any],
) -> str:

    return f"""
{function_code}

passed_df, failed_df, result = {function_name}(
    df=df,
    fields={fields},
    parameters={parameters},
    id_column=id_column
)
"""