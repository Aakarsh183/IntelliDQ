import json
import os
import re
import httpx
from typing import Any, Dict, List
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()


AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


# ─────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────

class SchemaRuleAnalyzer:

    def __init__(self):
        self.client = None

        if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT:
            self.client = AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_version=AZURE_OPENAI_API_VERSION,
                http_client=httpx.Client(verify=False),
            )
            self.deployment = AZURE_OPENAI_DEPLOYMENT

    # ─────────────────────────────────────────────
    # SCHEMA PARSER
    # ─────────────────────────────────────────────

    def parse_schema(self, schema_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract fields from schema
        """

        fields = []

        for col in schema_payload.get("target_columns", []):
            field = {
                "name": col.get("name"),
                "type": col.get("type", "string"),
                "category": col.get("category", "general"),
                "check_types": self._infer_check_types(col)
            }
            fields.append(field)

        return fields

    # ─────────────────────────────────────────────
    # CHECK TYPE FROM SCHEMA
    # ─────────────────────────────────────────────

    def _infer_check_types(self, field: Dict[str, Any]) -> List[str]:
        """
        Infer possible check types from schema
        """

        check_types = []

        field_name = field.get("name", "").lower()
        field_type = field.get("type", "").lower()

        # always possible
        check_types.append("not_null")

        # numeric → range
        if field_type in ["int", "integer", "double", "float", "decimal", "number"]:
            check_types.append("range")

        # string → length / regex
        if field_type == "string":
            check_types.append("length")
            check_types.append("regex")

        # date → comparison
        if field_type in ["date", "timestamp"]:
            check_types.append("comparison")

        # id fields → uniqueness
        if "id" in field_name:
            check_types.append("uniqueness")

        return list(set(check_types))

    # ─────────────────────────────────────────────
    # LLM: CHECK TYPE EXTRACTION
    # ─────────────────────────────────────────────

    def extract_check_type_with_llm(self, rule: Dict[str, Any], schema_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        LLM extracts ONLY:
        - check_type
        - parameters
        """

        if not self.client:
            return {"check_type": "not_null", "parameters": {}}

        prompt = f"""
You are a data quality expert.

Classify the business rule into ONE of these check types:

- not_null
- uniqueness
- length
- range
- allowed_values
- regex
- comparison

Also extract parameters if applicable.

--------------------------------------------------

RULE:
{json.dumps(rule, indent=2)}

SCHEMA:
{json.dumps(schema_fields[:50], indent=2)}

--------------------------------------------------

RETURN STRICT JSON:

{{
  "check_type": "...",
  "parameters": {{}}
}}

Examples:

Rule: "Age must be between 0 and 120"
→ {{ "check_type": "range", "parameters": {{ "min_value": 0, "max_value": 120 }} }}

Rule: "Email must be valid"
→ {{ "check_type": "regex", "parameters": {{ "pattern": "email" }} }}

Rule: "Account ID must be unique"
→ {{ "check_type": "uniqueness", "parameters": {{}} }}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You return only JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )

            content = response.choices[0].message.content
            return self._safe_json(content)

        except Exception as e:
            print("LLM error:", e)
            return {"check_type": "not_null", "parameters": {}}

    # ─────────────────────────────────────────────
    # SAFE JSON
    # ─────────────────────────────────────────────

    def _safe_json(self, content: str) -> Dict[str, Any]:
        if not content:
            return {"check_type": "not_null", "parameters": {}}

        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except:
            return {"check_type": "not_null", "parameters": {}}