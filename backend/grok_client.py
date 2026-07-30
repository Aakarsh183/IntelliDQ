'''import requests
import json
import os
import re
from dotenv import load_dotenv
load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")

class GrokClient:

    def __init__(self):
        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL

    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        # Remove markdown
        content = content.replace("```json", "").replace("```", "").strip()

        # Extract JSON object
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e

    def generate_pyspark_code(self, schema, rule, mapped_dict):
        prompt = f"""
        You are a data quality rule translator.

        Your task is to convert business rules into FULL PySpark validation code.


        Dataset schema:
        {schema}

        Return ONLY JSON.

        The PySpark code must:
        1. Use DataFrame name `df`
        2. Import functions from pyspark.sql.functions
        3. Generate two DataFrames:
        - passed_df
        - failed_df
        4. Use column function col()

        Mapped dictionary which maps columns in the rules file to columns in the source dataset:
        {mapped_dict}

        Important rules:
        1. Use ONLY the values of the dictionary for each entity as columns listed above.
        2. Do not invent new column names.
        3. Use the exact column names when generating PySpark code.


        Example:

        Business Rule:
        Account Number must not be null or empty

        Output:
        {{
        "rule_name": "Account Number Not Empty",
        "pyspark_code": "from pyspark.sql.functions import col\n\npassed_df = df.filter(\n    col('acct_number').isNotNull() & (col('acct_number') != '')\n)\n\nfailed_df = df.filter(\n    ~(col('acct_number').isNotNull() & (col('acct_number') != ''))\n)"
        }}

        Rule:
        Name: {rule['name']}
        Description: {rule['description']}
        Business Rule: {rule['business_rule']}
        Complexity: {rule['complexity']}
        Category: {rule['category']}
        """

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate python validation code."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post(self.url, headers=headers, json=payload)

        if response.status_code != 200:
            raise Exception(f"Grok API Error: {response.text}")

        result = response.json()
       
        content = result["choices"][0]["message"]["content"]

        # Clean possible formatting issues
        content = content.strip()

        try:
            parsed_json = json.loads(content)
        except:
            # Remove markdown if model adds it
            content = content.replace("```json", "").replace("```", "")
            parsed_json = json.loads(content)
        

        return parsed_json'''
'''
import requests
import json
import os
import time
import re
from dotenv import load_dotenv

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")


class GrokClient:

    def __init__(self):
        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL

   
    def _call_api_with_retry(self, payload, headers, max_retries=5):
        for attempt in range(max_retries):
            response = requests.post(self.url, headers=headers, json=payload)

            if response.status_code == 200:
                return response.json()

            error_text = response.text

            # Handle rate limit
            if "rate_limit_exceeded" in error_text:
                match = re.search(r"try again in ([\d\.]+)s", error_text)
                wait_time = float(match.group(1)) if match else 5

                print(f"⏳ Rate limit hit. Waiting {wait_time:.2f}s...")
                time.sleep(wait_time + 1)
            else:
                raise Exception(f"Grok API Error: {error_text}")

        raise Exception("Max retries exceeded")

    
    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        # Remove markdown
        content = content.replace("```json", "").replace("```", "").strip()

        # Extract JSON object
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e

   
    def generate_pyspark_code(self, schema, rule, mapped_dict):

        # Reduce schema size (important for token optimization)
        if isinstance(schema, list):
            schema_str = ", ".join(schema[:50])  # limit to 50 columns
        else:
            schema_str = str(schema)

        prompt = f"""
You are a data quality rule translator.

Your task is to convert business rules into FULL PySpark validation code.

STRICT INSTRUCTIONS:
- Return ONLY valid JSON
- Do NOT include explanation, text, or markdown
- Output must start with {{ and end with }}
- Ensure JSON is parseable using json.loads()
- Escape all newline characters properly using \\n

Dataset columns:
{schema_str}

Mapped dictionary:
{mapped_dict}

Rules:
1. Use DataFrame name `df`
2. Import from pyspark.sql.functions
3. Generate:
   - passed_df
   - failed_df
4. Use col() for all columns
5. Strictly use {mapped_dict} values for the particular column in the rule as a column to be used in pyspark code.

Example:

Business Rule:
Account Number must not be null or empty

Output:
{{
  "rule_name": "Account Number Not Empty",
  "pyspark_code": "from pyspark.sql.functions import col\\n\\npassed_df = df.filter(col('acct_number').isNotNull() & (col('acct_number') != ''))\\n\\nfailed_df = df.filter(~(col('acct_number').isNotNull() & (col('acct_number') != '')))"
}}

Rule:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}
"""

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        
        result = self._call_api_with_retry(payload, headers)

        
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]

        if not content:
            raise Exception("Empty response from model")

        # 🛡️ Safe JSON parsing
        parsed_json = self._safe_json_load(content)

        return parsed_json

'''

'''
import os
import sys
 
os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

import requests
import json
import os
import time
import re
from dotenv import load_dotenv
from pyspark.sql.functions import col , monotonically_increasing_id
from pyspark.sql.functions import countDistinct

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")


class GrokClient:

    def __init__(self):
        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL

   
    def _call_api_with_retry(self, payload, headers, max_retries=5):
        for attempt in range(max_retries):
            response = requests.post(self.url, headers=headers, json=payload)

            if response.status_code == 200:
                return response.json()

            error_text = response.text

            # Handle rate limit
            if "rate_limit_exceeded" in error_text:
                match = re.search(r"try again in ([\d\.]+)s", error_text)
                wait_time = float(match.group(1)) if match else 5

                print(f"⏳ Rate limit hit. Waiting {wait_time:.2f}s...")
                time.sleep(wait_time + 1)
            else:
                raise Exception(f"Grok API Error: {error_text}")

        raise Exception("Max retries exceeded")

    
    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        # Remove markdown
        content = content.replace("```json", "").replace("```", "").strip()

        # Extract JSON object
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e
        
    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        # Extract JSON array
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise
    
    def get_or_create_primary_key(self,df):

     for column in df.columns:
            stats = df.selectExpr(
                f"count(*) as total",
                f"count(distinct `{column}`) as distinct_count"
            ).collect()[0]

            if stats["total"] == stats["distinct_count"]:
                print(f"✅ Using existing primary key: {column}")
                return df, column

     print("⚠️ No primary key found. Creating new ID column...")
     df = df.withColumn("generated_id", monotonically_increasing_id())

     return df, "generated_id"
   
    def generate_pyspark_code(self, df, rule, mapped_dict):

        # Reduce schema size (important for token optimization)
        dataset,id_column = self.get_or_create_primary_key(df)

        prompt = f"""
You are an expert PySpark data quality engineer.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n
- JSON must be parseable using json.loads()

--------------------------------------------------

📥 INPUT:

Mapped Dictionary:
{mapped_dict}

(This maps rule column names → dataset column names.
You MUST ONLY use the VALUES from this dictionary as PySpark column names.)

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df

2. ID column is PROVIDED externally as:
   {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column
- DO NOT assign id_column inside the code
- ONLY use id_column for failed_ids extraction

--------------------------------------------------

3. Column Selection Rules:

- Identify ONLY the columns required for this rule
- Use mapped_dict to find corresponding dataset columns
- DO NOT use all mapped_dict values
- DO NOT include unused columns

Example:
Rule: "Account number must not be empty"
Mapped: {{"Account number": "acct_number"}}

Correct:
required_columns = ["acct_number"]

Incorrect:
required_columns = ["acct_number", "other_column"]

--------------------------------------------------

4. Column Validation Rules:

- Validate ONLY required_columns
- Validate id_column separately

--------------------------------------------------

5. Data Safety Rules:

- Validate df is not None
- Validate df has columns
- Check if df is empty using df.rdd.isEmpty()

- Handle null values using isNotNull()
- Cast numeric columns using cast("double") when needed
- Avoid direct comparisons with null

--------------------------------------------------

6. Condition Rules:

- Build condition using ONLY required_columns
- DO NOT introduce new columns
- DO NOT use unused mapped columns

--------------------------------------------------

7. Generate:

- passed_df
- failed_df

--------------------------------------------------

8. Compute:

- passed_count
- failed_count
- total_count
- pass_rate (safe division)

--------------------------------------------------

9. Failed IDs:

- Extract using id_column
- Limit to 100 records
- Exclude null IDs

--------------------------------------------------

10. Wrap EVERYTHING in try-except

--------------------------------------------------

11. Store output in variable:
result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.rdd.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <ONLY COLUMNS USED IN CONDITION>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <SAFE CONDITION BASED ON RULE>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

--------------------------------------------------

🚨 FINAL VALIDATION BEFORE OUTPUT:

- Ensure id_column is NOT assigned anywhere
- Ensure required_columns contains ONLY columns used in condition
- Ensure no extra mapped_dict values are used
- Ensure code is executable and safe

If any rule is violated → regenerate output

"""

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        
        result = self._call_api_with_retry(payload, headers)

        
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]

        if not content:
            raise Exception("Empty response from model")

        # 🛡️ Safe JSON parsing
        parsed_json = self._safe_json_load(content)

        return parsed_json
    
    def generate_ai_rules(self, schema, existing_rules):

    
        prompt = f"""
        You are an expert Data Quality Engineer.

        Your task is to generate high-quality data validation rules based on:
        1. Dataset schema
        2. Existing business rules

        STRICT INSTRUCTIONS:
        - Return ONLY valid JSON
        - Do NOT include explanation or markdown
        - Output must be a list of JSON 
        - Each rule must follow this structure:
        {{
            "name": "...",
            "description": "...",
            "business_rule": "...",
            "complexity": "simple|medium|complex",
            "category": "completeness|validity|consistency|accuracy"
        }}

        DATASET COLUMNS:
        {schema}

        EXISTING RULES:
        {existing_rules}

        RULE GENERATION GUIDELINES:
        - Do NOT duplicate existing rules
        - Generate 5-10 new meaningful rules
        - Include:
        - Null checks
        - Range validations
        - Date validations
        - Cross-column rules
        - Financial validations (if applicable)
        - Use realistic business language
        - Ensure rules are implementable in PySpark later

        EXAMPLE OUTPUT:
        [
        {{
            "name": "Net Return Range Check",
            "description": "Net return should be within acceptable limits",
            "business_rule": "Net return must be between -1 and 1",
            "complexity": "simple",
            "category": "validity"
        }},

        {{
           
            "name": "Gross Return Greater Than Net Return",
            "description": "Gross return should be greater than or equal to net return",
            "business_rule": "Gross return must be greater than or equal to net return",
            "complexity": "medium",
            "category": "consistency"
  
        }}
        ]
        """

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate data quality rules in JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        result = self._call_api_with_retry(payload, headers)
        
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")
        
        content = result["choices"][0]["message"]["content"]
        
        parsed = self._safe_json_load_array(content)

        return parsed
'''
'''
import os
import sys

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

import requests
import json
import time
import re
from dotenv import load_dotenv
from pyspark.sql.functions import col, monotonically_increasing_id

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")

#AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")  # e.g. gpt-4o
#AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-02-15-preview")
class GrokClient:

    def __init__(self):
        self.api_key = GROK_API_KEY
        self.url     = GROK_BASE_URL
        #self.api_version = AZURE_API_VERSION
        #self.deployment = AZURE_DEPLOYMENT_NAME

    # ── Utilities (unchanged) ─────────────────────────────────────────────────

    def _call_api_with_retry(self, payload, headers, max_retries=5):
        for attempt in range(max_retries):
           # response = requests.post(self.url, headers=headers, json=payload)
            response = requests.post(self.url, headers=headers, json=payload)
            if response.status_code == 200:
                return response.json()
            error_text = response.text
            if "rate_limit_exceeded" in error_text:
                match = re.search(r"try again in ([\d\.]+)s", error_text)
                wait_time = float(match.group(1)) if match else 5
                print(f"⏳ Rate limit hit. Waiting {wait_time:.2f}s...")
                time.sleep(wait_time + 1)
            else:
                raise Exception(f"Grok API Error: {error_text}")
        raise Exception("Max retries exceeded")

    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def get_or_create_primary_key(self, df):
        for column in df.columns:
            stats = df.selectExpr(
                f"count(*) as total",
                f"count(distinct `{column}`) as distinct_count"
            ).collect()[0]
            if stats["total"] == stats["distinct_count"]:
                print(f"✅ Using existing primary key: {column}")
                return df, column
        print("⚠️ No primary key found. Creating generated_id column...")
        df = df.withColumn("generated_id", monotonically_increasing_id())
        return df, "generated_id"
    

    def remove_table_prefix(code, all_columns_flat):
        """
        Converts table.column → column
        """

        for full_col in all_columns_flat:
            if "." in full_col:
                table, col = full_col.split(".", 1)

                # Replace table.column → column
                code = re.sub(
                    rf'col\(["\']{table}\.{col}["\']\)',
                    f'col("{col}")',
                    code
                )

        return code

    # ── Single-table code generation (ORIGINAL — untouched) ──────────────────

    def generate_pyspark_code(self, df, rule, mapped_dict):
        dataset, id_column = self.get_or_create_primary_key(df)

        prompt = f"""
You are an expert PySpark data quality engineer.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n
- JSON must be parseable using json.loads()

--------------------------------------------------

📥 INPUT:

Mapped Dictionary:
{mapped_dict}

(This maps rule column names → dataset column names.
You MUST ONLY use the VALUES from this dictionary as PySpark column names.)

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df

2. ID column is PROVIDED externally as:
   {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column
- DO NOT assign id_column inside the code
- ONLY use id_column for failed_ids extraction

--------------------------------------------------

3. Column Selection Rules:

- Identify ONLY the columns required for this rule
- Use mapped_dict to find corresponding dataset columns
- DO NOT use all mapped_dict values
- DO NOT include unused columns

--------------------------------------------------

4. Data Safety Rules:

- Validate df is not None
- Validate df has columns
- Check if df is empty using df.rdd.isEmpty()
- Handle null values using isNotNull()
- Cast numeric columns using cast("double") when needed
- Avoid direct comparisons with null

--------------------------------------------------

5. Generate:

- passed_df
- failed_df

--------------------------------------------------

6. Compute:

- passed_count
- failed_count
- total_count
- pass_rate (safe division)

--------------------------------------------------

7. Failed IDs:

- Extract using id_column
- Limit to 100 records
- Exclude null IDs

--------------------------------------------------

8. Wrap EVERYTHING in try-except

--------------------------------------------------

9. Store output in variable:
result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.rdd.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <ONLY COLUMNS USED IN CONDITION>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <SAFE CONDITION BASED ON RULE>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

--------------------------------------------------

🚨 FINAL VALIDATION BEFORE OUTPUT:

- Ensure id_column is NOT assigned anywhere
- Ensure required_columns contains ONLY columns used in condition
- Ensure no extra mapped_dict values are used
- Ensure code is executable and safe

If any rule is violated → regenerate output
"""

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

        result = self._call_api_with_retry(payload, headers)

        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")

        return self._safe_json_load(content)

    # ── Multi-table code generation (NEW — only called for multi-table) ───────

    def generate_pyspark_code_multi(self, df, rule, mapped_dict, touched_tables):
        """
        Called only when is_multi_table=True.
        df is the pre-joined DataFrame built in main_app.py.
        touched_tables is the list of sheet names involved in this rule.
        """
        dataset, id_column = self.get_or_create_primary_key(df)
        schema_str = ", ".join(dataset.columns[:60])
        all_columns_flat = df.columns

        if len(touched_tables) > 1:
            table_context = (
                f"This rule spans multiple tables that have been PRE-JOINED into `df`: "
                f"{', '.join(touched_tables)}. "
                f"Some columns in `df` may be in 'TableName.ColumnName' format."
            )
        else:
            table_context = (
                f"This rule applies to the '{touched_tables[0]}' table only. "
                f"`df` contains only this table's columns. "
                f"Note: some column names may naturally contain dots "
                f"(e.g. 'Rep.QTD Target USD') — these are plain column names, "
                f"NOT table-qualified references."
            )

        prompt = f"""
You are an expert PySpark data quality engineer working with a dataset
that may contain multiple tables.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n

--------------------------------------------------

📋 DATASET CONTEXT:

{table_context}

Known table names (sheets): {touched_tables}

Available columns in `df`:
{schema_str}

--------------------------------------------------

📥 INPUT:

Mapped Dictionary (maps rule entity names → actual column names in df):
{mapped_dict}

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df
   (Pre-joined — do NOT load or join tables yourself)

2. ID column is PROVIDED externally as:
   {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column
- DO NOT assign id_column inside the code
- ONLY use id_column for failed_ids extraction

--------------------------------------------------

3. Column Reference Rules — READ CAREFULLY:

Known table names are: {touched_tables}

A dot in a column name means it is table-qualified ONLY if the text before
the dot exactly matches one of the known table names above.

Examples:
- "Orders.amount"       → table-qualified  (Orders is a known table)
- "Rep.QTD Target USD"  → plain column name (Rep is NOT a known table)

In BOTH cases, use backtick quoting inside col():
  col('`Orders.amount`')        ✅
  col('`Rep.QTD Target USD`')   ✅

For required_columns list and df.columns membership checks,
use the RAW column name WITHOUT backticks:
  required_columns = ["Rep.QTD Target USD"]    ✅
  required_columns = ["`Rep.QTD Target USD`"]  ❌  DO NOT do this

DO NOT include unused columns.

--------------------------------------------------

4. Data Safety Rules:

- Validate df is not None
- Validate df has columns
- Check if df is empty using df.rdd.isEmpty()
- Handle null values using isNotNull()
- Cast numeric columns using cast("double") when needed

--------------------------------------------------

5. Generate:

- passed_df
- failed_df

--------------------------------------------------

6. Compute:

- passed_count
- failed_count
- total_count
- pass_rate (safe division)

--------------------------------------------------

7. Failed IDs:

- Extract using id_column
- Limit to 100 records
- Exclude null IDs

--------------------------------------------------

8. Wrap EVERYTHING in try-except

--------------------------------------------------

9. Store output in variable: result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.rdd.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <RAW COLUMN NAMES WITHOUT BACKTICKS>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <USE col(backtick-quoted name) FOR ALL DOT-CONTAINING COLUMNS>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count  = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

--------------------------------------------------

🚨 FINAL VALIDATION BEFORE OUTPUT:

- id_column must NOT be assigned anywhere in the code
- required_columns must use raw names with no backticks
- col() calls for any dot-containing column must use backtick quoting
- Code must be fully executable

If any rule is violated → regenerate output
"""

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

        result = self._call_api_with_retry(payload, headers)
        
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")
        
        parsed = self._safe_json_load(content)
        code = parsed["pyspark_code"]
        parsed["pyspark_code"] = self.remove_table_prefix(code, all_columns_flat)
        return parsed

    # ── AI rule recommendation (unchanged) ────────────────────────────────────

    def generate_ai_rules(self, schema, existing_rules):
        prompt = f"""
        You are an expert Data Quality Engineer.

        Your task is to generate high-quality data validation rules based on:
        1. Dataset schema
        2. Existing business rules

        STRICT INSTRUCTIONS:
        - Return ONLY valid JSON
        - Do NOT include explanation or markdown
        - Output must be a list of JSON 
        - Each rule must follow this structure:
        {{
            "name": "...",
            "description": "...",
            "business_rule": "...",
            "complexity": "simple|medium|complex",
            "category": "completeness|validity|consistency|accuracy"
        }}

        DATASET COLUMNS:
        {schema}

        EXISTING RULES:
        {existing_rules}

        RULE GENERATION GUIDELINES:
        - Do NOT duplicate existing rules
        - Generate 5-10 new meaningful rules
        - Include:
        - Null checks
        - Range validations
        - Date validations
        - Cross-column rules
        - Financial validations (if applicable)
        - For multi-table schemas, include cross-table consistency rules
        - Use realistic business language
        - Ensure rules are implementable in PySpark later

        EXAMPLE OUTPUT:
        [
        {{
            "name": "Net Return Range Check",
            "description": "Net return should be within acceptable limits",
            "business_rule": "Net return must be between -1 and 1",
            "complexity": "simple",
            "category": "validity"
        }}
        ]
        """

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You generate data quality rules in JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

        result = self._call_api_with_retry(payload, headers)

        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)
'''  
'''
import os
import sys

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

import json
import time
import re
import httpx
from openai import AzureOpenAI
from dotenv import load_dotenv
from pyspark.sql.functions import col, monotonically_increasing_id

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class GrokClient:

    def __init__(self):
        self.client = AzureOpenAI(
            api_key         = AZURE_OPENAI_API_KEY,
            azure_endpoint  = AZURE_OPENAI_ENDPOINT,
            api_version     = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _call_api_with_retry(self, payload, headers, max_retries=5):
        """
        headers param kept for signature compatibility — not used for Azure.
        payload uses the same messages/temperature shape as before.
        """
        messages    = payload.get("messages", [])
        temperature = payload.get("temperature", 0)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model       = self.deployment,
                    messages    = messages,
                    temperature = temperature,
                )

                # Normalize to the same shape the rest of the code expects:
                # { "choices": [{ "message": { "content": "..." } }] }
                content = response.choices[0].message.content

                return {
                    "choices": [
                        {"message": {"content": content}}
                    ]
                }

            except Exception as e:
                error_str = str(e)

                # Handle rate limit / throttling
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = (attempt + 1) * 5
                    print(f"⏳ Azure rate limit hit. Waiting {wait_time}s (attempt {attempt + 1})...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Azure OpenAI API Error: {error_str}")

        raise Exception("Max retries exceeded")

    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def get_or_create_primary_key(self, df):
        for column in df.columns:
            stats = df.selectExpr(
                f"count(*) as total",
                f"count(distinct `{column}`) as distinct_count"
            ).collect()[0]
            if stats["total"] == stats["distinct_count"]:
                print(f"✅ Using existing primary key: {column}")
                return df, column
        print("⚠️ No primary key found. Creating generated_id column...")
        df = df.withColumn("generated_id", monotonically_increasing_id())
        return df, "generated_id"
    
    def generate_pyspark_code(self, df, rule, mapped_dict):
        dataset, id_column = self.get_or_create_primary_key(df)

        prompt = f"""
You are an expert PySpark data quality engineer.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n
- JSON must be parseable using json.loads()

--------------------------------------------------

📥 INPUT:

Mapped Dictionary:
{mapped_dict}

(This maps rule column names → dataset column names.
You MUST ONLY use the VALUES from this dictionary as PySpark column names.)

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df

2. ID column is PROVIDED externally as:
   {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column
- DO NOT assign id_column inside the code
- ONLY use id_column for failed_ids extraction

--------------------------------------------------

3. Column Selection Rules:

- Identify ONLY the columns required for this rule
- Use mapped_dict to find corresponding dataset columns
- DO NOT use all mapped_dict values
- DO NOT include unused columns

--------------------------------------------------

4. Data Safety Rules:

- Validate df is not None
- Validate df has columns
- Check if df is empty using df.rdd.isEmpty()
- Handle null values using isNotNull()
- Cast numeric columns using cast("double") when needed
- Avoid direct comparisons with null

--------------------------------------------------

5. Generate:

- passed_df
- failed_df

--------------------------------------------------

6. Compute:

- passed_count
- failed_count
- total_count
- pass_rate (safe division)

--------------------------------------------------

7. Failed IDs:

- Extract using id_column
- Limit to 100 records
- Exclude null IDs

--------------------------------------------------

8. Wrap EVERYTHING in try-except

--------------------------------------------------

9. Store output in variable:
result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.rdd.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <ONLY COLUMNS USED IN CONDITION>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <SAFE CONDITION BASED ON RULE>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

--------------------------------------------------

🚨 FINAL VALIDATION BEFORE OUTPUT:

- Ensure id_column is NOT assigned anywhere
- Ensure required_columns contains ONLY columns used in condition
- Ensure no extra mapped_dict values are used
- Ensure code is executable and safe

If any rule is violated → regenerate output
"""

        payload = {
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {}

        result = self._call_api_with_retry(payload, headers)
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")

        parsed = self._safe_json_load(content)
        return parsed

    # ── Multi-table code generation ───────────────────────────────────────────

    def generate_pyspark_code_multi(self, df, rule, mapped_dict, touched_tables):
        dataset, id_column = self.get_or_create_primary_key(df)
        schema_str = ", ".join(dataset.columns[:60])
        all_columns_flat = df.columns
        if len(touched_tables) > 1:
            table_context = (
                f"This rule spans multiple tables that have been PRE-JOINED into `df`: "
                f"{', '.join(touched_tables)}."
            )
        else:
            table_context = (
                f"This rule applies to the '{touched_tables[0]}' table. "
                f"`df` contains only this table's columns."
            )

        prompt = f"""
You are an expert PySpark data quality engineer working with a dataset
that may contain multiple tables.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n

--------------------------------------------------

📋 DATASET CONTEXT:

{table_context}

Known table names (sheets): {touched_tables}

Available columns in `df`:
{schema_str}

--------------------------------------------------

📥 INPUT:

Mapped Dictionary (maps rule entity names → actual column names in df):
{mapped_dict}

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df
   (Pre-joined — do NOT load or join tables yourself)

2. ID column is PROVIDED externally as:
   {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column
- DO NOT assign id_column inside the code
- ONLY use id_column for failed_ids extraction

--------------------------------------------------

3. Column Reference Rules — READ CAREFULLY:

Known table names are: {touched_tables}

A dot in a column name means it is table-qualified ONLY if the text before
the dot exactly matches one of the known table names above.

Examples:
- "Orders.amount"       → table-qualified  (Orders is a known table)
- "Rep.QTD Target USD"  → plain column name (Rep is NOT a known table)

In BOTH cases, use backtick quoting inside col():
  col('`Orders.amount`')        ✅
  col('`Rep.QTD Target USD`')   ✅

For required_columns list and df.columns membership checks,
use the RAW column name WITHOUT backticks:
  required_columns = ["Rep.QTD Target USD"]    ✅
  required_columns = ["`Rep.QTD Target USD`"]  ❌  DO NOT do this

DO NOT include unused columns.

--------------------------------------------------

4. Data Safety Rules:

- Validate df is not None
- Validate df has columns
- Check if df is empty using df.rdd.isEmpty()
- Handle null values using isNotNull()
- Cast numeric columns using cast("double") when needed

--------------------------------------------------

5. Generate:

- passed_df
- failed_df

--------------------------------------------------

6. Compute:

- passed_count
- failed_count
- total_count
- pass_rate (safe division)

--------------------------------------------------

7. Failed IDs:

- Extract using id_column
- Limit to 100 records
- Exclude null IDs

--------------------------------------------------

8. Wrap EVERYTHING in try-except

--------------------------------------------------

9. Store output in variable: result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.rdd.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <RAW COLUMN NAMES WITHOUT BACKTICKS>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <USE col(backtick-quoted name) FOR ALL DOT-CONTAINING COLUMNS>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count  = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

--------------------------------------------------

🚨 FINAL VALIDATION BEFORE OUTPUT:

- id_column must NOT be assigned anywhere in the code
- required_columns must use raw names with no backticks
- col() calls for any dot-containing column must use backtick quoting
- Code must be fully executable

If any rule is violated → regenerate output
"""

        payload = {
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {}

        result = self._call_api_with_retry(payload, headers)
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")

        parsed = self._safe_json_load(content)
        code = parsed["pyspark_code"]
        parsed["pyspark_code"] = self.remove_table_prefix(code, all_columns_flat)
        return parsed

    # ── AI rule recommendation ────────────────────────────────────────────────

    def generate_ai_rules(self, schema, existing_rules):
        prompt = f"""
        You are an expert Data Quality Engineer.

        Your task is to generate high-quality data validation rules based on:
        1. Dataset schema
        2. Existing business rules

        STRICT INSTRUCTIONS:
        - Return ONLY valid JSON
        - Do NOT include explanation or markdown
        - Output must be a list of JSON
        - Each rule must follow this structure:
        {{
            "name": "...",
            "description": "...",
            "business_rule": "...",
            "complexity": "simple|medium|complex",
            "category": "completeness|validity|consistency|accuracy"
        }}

        DATASET COLUMNS:
        {schema}

        EXISTING RULES:
        {existing_rules}

        RULE GENERATION GUIDELINES:
        - Do NOT duplicate existing rules
        - Generate 5-10 new meaningful rules
        - Include:
          - Null checks
          - Range validations
          - Date validations
          - Cross-column rules
          - Financial validations (if applicable)
          - For multi-table schemas, include cross-table consistency rules
        - Use realistic business language
        - Ensure rules are implementable in PySpark later

        EXAMPLE OUTPUT:
        [
        {{
            "name": "Net Return Range Check",
            "description": "Net return should be within acceptable limits",
            "business_rule": "Net return must be between -1 and 1",
            "complexity": "simple",
            "category": "validity"
        }}
        ]
        """

        payload = {
            "messages": [
                {"role": "system", "content": "You generate data quality rules in JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {}

        result = self._call_api_with_retry(payload, headers)
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)
'''

import os
import sys

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

import json
import time
import re
import httpx
from openai import AzureOpenAI
from dotenv import load_dotenv
from pyspark.sql.functions import col, monotonically_increasing_id

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class GrokClient:

    def __init__(self):
        self.client = AzureOpenAI(
            api_key        = AZURE_OPENAI_API_KEY,
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_version    = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _call_api_with_retry(self, payload, headers, max_retries=5):
        messages    = payload.get("messages", [])
        temperature = payload.get("temperature", 0)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model       = self.deployment,
                    messages    = messages,
                    temperature = temperature,
                )
                content = response.choices[0].message.content
                return {
                    "choices": [{"message": {"content": content}}]
                }
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = (attempt + 1) * 5
                    print(f"⏳ Azure rate limit hit. Waiting {wait_time}s (attempt {attempt + 1})...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Azure OpenAI API Error: {error_str}")

        raise Exception("Max retries exceeded")

    def _safe_json_load(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Failed. Raw content:\n", content)
            raise e

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")
        content = content.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def get_or_create_primary_key(self, df):
        for column in df.columns:
            stats = df.selectExpr(
                f"count(*) as total",
                f"count(distinct `{column}`) as distinct_count"
            ).collect()[0]
            if stats["total"] == stats["distinct_count"]:
                print(f"✅ Using existing primary key: {column}")
                return df, column
        print("⚠️ No primary key found. Creating generated_id column...")
        df = df.withColumn("generated_id", monotonically_increasing_id())
        return df, "generated_id"

    # ── Single-table code generation (unchanged) ──────────────────────────────

    def generate_pyspark_code(self, df, rule, mapped_dict, id_column=None):
        if id_column is not None and id_column in df.columns:
            dataset = df
        else:
            dataset, id_column = self.get_or_create_primary_key(df)

        prompt = f"""
You are an expert PySpark data quality engineer.

Your task is to convert business rules into FULLY EXECUTABLE, DEFENSIVE PySpark code.

--------------------------------------------------

🚨 STRICT OUTPUT RULES (MANDATORY):

- Return ONLY valid JSON
- DO NOT include explanation or extra text
- DO NOT include markdown
- Output must start with {{ and end with }}
- Escape all newline characters using \\n

--------------------------------------------------

📥 INPUT:

Mapped Dictionary:
{mapped_dict}

Rule Entities (Columns extracted from rule):
{rule["entities"]}

IMPORTANT: Column names are already sanitized — dots and spaces replaced with underscores.
Use column names EXACTLY as they appear in mapped_dict values of the rule entities.
DO NOT add backtick quoting — column names are plain underscore-separated strings.

Rule Details:
Name: {rule['name']}
Description: {rule['description']}
Business Rule: {rule['business_rule']}
Complexity: {rule['complexity']}
Category: {rule['category']}

--------------------------------------------------

⚙️ REQUIREMENTS (MANDATORY):

1. Use DataFrame name: df

2. ID column is PROVIDED externally as variable: id_column
   Current value: {id_column}

🚨 CRITICAL:
- DO NOT redefine id_column anywhere in the code
- DO NOT write id_column = '...' anywhere
- The variable id_column is already available — just use it

3. Use ONLY mapped_dict values that are relevant to this rule
4. Column names are plain strings — no backticks needed
5. Validate df is not None, has columns, check empty with df.rdd.isEmpty()
6. Handle nulls with isNotNull(), cast numerics with cast("double")
7. Generate passed_df and failed_df
8. Compute passed_count, failed_count, total_count, pass_rate
9. Extract failed_ids using id_column, limit 100, exclude nulls
10. Wrap EVERYTHING in try-except
11. Store output in variable: result

--------------------------------------------------

📤 OUTPUT FORMAT (STRICT):

{{
  "rule_name": "<rule name>",
  "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    if df is None:\\n        raise Exception('Input DataFrame is None')\\n\\n    if len(df.columns) == 0:\\n        raise Exception('DataFrame has no columns')\\n\\n    if df.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = <ONLY COLUMNS USED IN CONDITION>\\n\\n        for c in required_columns:\\n            if c not in df.columns:\\n                raise Exception(f'Column {{c}} not found in dataframe')\\n\\n        if id_column not in df.columns:\\n            raise Exception(f'ID Column {{id_column}} not found in dataframe')\\n\\n        condition = <SAFE CONDITION BASED ON RULE>\\n\\n        passed_df = df.filter(condition)\\n        failed_df = df.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
}}

🚨 FINAL VALIDATION:
- id_column must NOT be assigned anywhere
- Column names: plain strings, no backticks
- Code must be fully executable
"""

        payload = {
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }

        result = self._call_api_with_retry(payload, {})
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")

        parsed = self._safe_json_load(content)
        parsed["id_column"] = id_column
        
        return parsed,dataset

    # ── Multi-table code generation ───────────────────────────────────────────

    def generate_pyspark_code_multi(self, rule, mapped_dict,
                                  involved_tables, tables_meta, dfs):
        """
        Called for multi-table rules that span MORE THAN ONE sheet.
        
        Instead of a pre-joined df, we pass full schema info for each
        involved table. The LLM generates the join logic itself.
        
        dfs            : { sheet_name: spark_df }
        involved_tables: list of sheet names this rule touches
        tables_meta    : { sheet_name: { "columns": [...] } }
        """

        # ── Build id_column per table ─────────────────────────────────────────────
        # Find or create primary key for each involved table individually
        table_id_columns = {}
        updated_dfs      = {}

        for tbl in involved_tables:
            tbl_df = dfs[tbl]
            enriched_df, id_col = self.get_or_create_primary_key(tbl_df)
            updated_dfs[tbl]      = enriched_df
            table_id_columns[tbl] = id_col
            # Write back enriched df so execute_code sees generated_id too
            dfs[tbl] = enriched_df

        # Use the first involved table's id_column as the primary id_column
        # (the LLM will be told which table's id to use for failed_ids)
        primary_table  = involved_tables[0]
        id_column      = table_id_columns[primary_table]

        # ── Build per-table schema info ───────────────────────────────────────────
        table_schemas = {}
        for tbl in involved_tables:
            table_schemas[tbl] = list(updated_dfs[tbl].columns)

        # ── Build join info ───────────────────────────────────────────────────────
        join_info_lines = []
        for i in range(len(involved_tables)):
            for j in range(i + 1, len(involved_tables)):
                t1, t2  = involved_tables[i], involved_tables[j]
                cols1   = set(table_schemas[t1])
                cols2   = set(table_schemas[t2])
                common  = list(cols1 & cols2)
                if common:
                    join_info_lines.append(
                        f"- {t1} and {t2} share common columns (use for join): {common}"
                    )
                else:
                    join_info_lines.append(
                        f"- {t1} and {t2} have NO common columns — cross join or rule may not need both"
                    )

        join_info = "\n".join(join_info_lines) if join_info_lines else "No join info available."

        # ── DataFrame variable names available in exec() scope ───────────────────
        df_var_lines = []
        for tbl in involved_tables:
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", tbl)
            df_var_lines.append(
                f"  df_{safe}  →  table '{tbl}'  →  columns: {table_schemas[tbl]}"
            )
        df_vars_str = "\n".join(df_var_lines)

        prompt = f"""
    You are an expert PySpark data quality engineer working with a MULTI-TABLE dataset.

    Your task is to convert a business rule into FULLY EXECUTABLE, DEFENSIVE PySpark code.

    --------------------------------------------------

    🚨 STRICT OUTPUT RULES (MANDATORY):

    - Return ONLY valid JSON
    - DO NOT include explanation or extra text
    - DO NOT include markdown
    - Output must start with {{ and end with }}
    - Escape all newline characters using \\n

    --------------------------------------------------

    📋 MULTI-TABLE CONTEXT:

    This rule involves {len(involved_tables)} table(s): {involved_tables}

    Available DataFrames already loaded in execution scope:
    {df_vars_str}

    Join information:
    {join_info}

    --------------------------------------------------

    📥 INPUT:

    Mapped Dictionary (entity name → sanitized column name):
    {mapped_dict}

    Rule Entities (Columns extracted from rule):
    {rule["entities"]}

    IMPORTANT:
    - Column names are already sanitized (dots and spaces replaced with underscores)
    - Use column names EXACTLY as they appear in mapped_dict values of the rule entities
    - No backtick quoting needed

    Rule Details:
    Name        : {rule['name']}
    Description : {rule['description']}
    Business Rule: {rule['business_rule']}
    Complexity  : {rule['complexity']}
    Category    : {rule['category']}

    --------------------------------------------------

    ⚙️ CODE GENERATION REQUIREMENTS (MANDATORY):

    1. Load DataFrames using ONLY the variable names shown above
    (df_TableName format — already in scope, do NOT use spark.read or spark.table)

    2. If the rule requires data from multiple tables:
    - Join them on the common columns listed in Join information above
    - Use inner join unless the rule implies otherwise
    - Assign the joined result to df_work

    3. If the rule only needs ONE of the tables:
    - Use that table's DataFrame directly
    - Assign it to df_work

    4. ID column for the PRIMARY table '{primary_table}':
    The variable id_column is PROVIDED externally.
    Current value: {id_column}

    🚨 CRITICAL:
    - DO NOT redefine id_column anywhere in the code
    - DO NOT write id_column = '...' anywhere
    - The variable id_column is already available — just use it
    - DO NOT use spark.read, spark.table, or spark.createDataFrame
    - All DataFrames are already loaded as df_TableName variables

    5. Use ONLY mapped_dict values relevant to this rule
    6. Column names are plain strings — no backtick quoting
    7. Validate df_work is not None, check empty with .rdd.isEmpty()
    8. Handle nulls with isNotNull(), cast numerics with .cast("double")
    9. Generate passed_df and failed_df from df_work
    10. Compute passed_count, failed_count, total_count, pass_rate
    11. Extract failed_ids from df_work using id_column, limit 100, exclude nulls
    12. Wrap EVERYTHING in try-except
    13. Store final output in variable: result

    --------------------------------------------------

    📤 OUTPUT FORMAT (STRICT):

    {{
    "rule_name": "<rule name>",
    "pyspark_code": "try:\\n    from pyspark.sql.functions import col\\n\\n    rule_name = '<rule name>'\\n\\n    # Load tables\\n    df_Table1 = df_Table1  # already in scope\\n\\n    # Join if needed\\n    df_work = df_Table1.join(df_Table2, on=['common_col'], how='inner')\\n    # OR if single table: df_work = df_Table1\\n\\n    if df_work is None:\\n        raise Exception('DataFrame is None')\\n\\n    if df_work.isEmpty():\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': 0,\\n            'failed_count': 0,\\n            'pass_rate': 0,\\n            'failed_ids': [],\\n            'message': 'Empty DataFrame'\\n        }}\\n    else:\\n        required_columns = ['col1', 'col2']\\n\\n        for c in required_columns:\\n            if c not in df_work.columns:\\n                raise Exception(f'Column {{c}} not found')\\n\\n        if id_column not in df_work.columns:\\n            raise Exception(f'ID Column {{id_column}} not found')\\n\\n        condition = <CONDITION BASED ON RULE>\\n\\n        passed_df = df_work.filter(condition)\\n        failed_df = df_work.filter(~condition)\\n\\n        passed_count = passed_df.count()\\n        failed_count = failed_df.count()\\n        total_count  = passed_count + failed_count\\n\\n        pass_rate = (passed_count / total_count) if total_count > 0 else 0\\n\\n        failed_ids = [row[id_column] for row in failed_df.select(id_column).limit(100).collect() if row[id_column] is not None]\\n\\n        result = {{\\n            'rule': rule_name,\\n            'passed_count': passed_count,\\n            'failed_count': failed_count,\\n            'pass_rate': pass_rate,\\n            'failed_ids': failed_ids\\n        }}\\n\\nexcept Exception as e:\\n    result = {{\\n        'rule': '<rule name>',\\n        'error': str(e)\\n    }}"
    }}

    🚨 FINAL VALIDATION BEFORE OUTPUT:
    - id_column must NOT be assigned or redefined anywhere in the code
    - All DataFrames loaded using df_TableName variables only
    - Column names: plain strings, no backticks
    - df_work must be defined before any filter/validation
    - Code must be fully executable as-is
    """

        payload = {
            "messages": [
                {"role": "system", "content": "You generate PySpark validation code in strict JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }

        result = self._call_api_with_retry(payload, {})
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response format")

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise Exception("Empty response from model")

        parsed = self._safe_json_load(content)
        parsed["id_column"] = id_column
        # Return updated_dfs so main_app can write enriched dfs back to session
        return parsed, updated_dfs
    # ── AI rule recommendation ────────────────────────────────────────────────

    def generate_ai_rules(self, schema, existing_rules):
        prompt = f"""
        You are an expert Data Quality Engineer.

        Your task is to generate high-quality data validation rules based on:
        1. Dataset schema
        2. Existing business rules

        STRICT INSTRUCTIONS:
        - Return ONLY valid JSON
        - Do NOT include explanation or markdown
        - Output must be a list of JSON
        - Each rule must follow this structure:
        {{
            "name": "...",
            "description": "...",
            "business_rule": "...",
            "complexity": "simple|medium|complex",
            "category": "completeness|validity|consistency|accuracy"
        }}

        DATASET COLUMNS:
        {schema}

        EXISTING RULES:
        {existing_rules}

        RULE GENERATION GUIDELINES:
        - Do NOT duplicate existing rules
        - Generate 5-10 new meaningful rules
        - Include null checks, range validations, date validations,
          cross-column rules, financial validations
        - For multi-table schemas, include cross-table consistency rules
        - Use realistic business language
        - Ensure rules are implementable in PySpark

        EXAMPLE OUTPUT:
        [
        {{
            "name": "Net Return Range Check",
            "description": "Net return should be within acceptable limits",
            "business_rule": "Net return must be between -1 and 1",
            "complexity": "simple",
            "category": "validity"
        }}
        ]
        """

        payload = {
            "messages": [
                {"role": "system", "content": "You generate data quality rules in JSON format."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }

        result = self._call_api_with_retry(payload, {})
        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)
    
    def generate_remediation(
        self,
        rule,
        mapped_dict,
        failed_ids=None,
        failed_count=0,
        failed_records_context=None,
    ):

        rule = rule or {}
        entities = rule.get("entities", [])
        sample_ids = (failed_ids or [])[:25]
        failed_records_context = failed_records_context or {}
        failed_context_json = json.dumps(failed_records_context, default=str, indent=2)

        prompt = f"""
You are a Data Quality Remediation Expert.

A data quality rule has FAILED on {failed_count} records.

Rule that failed:
Name: {rule.get("name")}
Business Rule: {rule.get("business_rule")}
Category: {rule.get("category")}

Entities (columns) involved: {entities}
Column mapping (entity → actual dataset column): {mapped_dict}
Sample of failed record IDs: {sample_ids}

Failed records evidence:
{failed_context_json}

Generate 3-5 targeted remediation suggestions for ONLY the failing records.
Base every suggestion on the failed-record evidence. If evidence is insufficient,
recommend review/export instead of guessing a destructive correction.
Each suggestion must be safe, targeted, and reversible.

Return ONLY a JSON array. Each item must have:
- title: short action name
- description: what it does and which column it targets (use actual column names from mapped_dict)
- logic: natural language instruction precise enough to generate PySpark code from
         (e.g. "for records where account_number is null, set account_number to 'UNKNOWN'")
- action_type: one of fillna | filter | replace | cast | deduplicate | standardize | review
- target_columns: array of actual dataset column names touched by the action
- confidence: high | medium | low
- why_this_fixes_failure: concise reason tied to the failed-record evidence
- risk_level: low | medium | high
- reversible: true | false
- requires_business_approval: true | false

STRICT:
- Only suggest actions on mapped_dict values and failed-record target_columns.
- Do NOT modify ID columns.
- Do NOT suggest dropping the entire table or unrelated transformations.
- Use action_type "filter" only when removing invalid failed rows is explicitly safe.
- Mark high-risk inferred replacements as requires_business_approval = true.

Example:
[
  {{
    "title": "Fill null account numbers",
    "description": "Replace null values in account_number with 'UNKNOWN' for the {failed_count} failing records",
    "logic": "for records where account_number is null, set account_number to 'UNKNOWN'",
    "action_type": "fillna",
    "target_columns": ["account_number"],
    "confidence": "medium",
    "why_this_fixes_failure": "The failed evidence shows account_number has null values.",
    "risk_level": "medium",
    "reversible": true,
    "requires_business_approval": true
  }}
]
"""
        payload = {
            "messages": [
                {"role": "system", "content": "You generate targeted data remediation suggestions as a JSON array."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        result  = self._call_api_with_retry(payload, {})
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)
    
    def generate_remediation_code(
        self,
        df,
        remediation_logic,
        mapped_dict,
        failed_ids=None,
        id_column=None,
        remediation=None,
        failed_records_context=None,
    ):
        schema_str = ", ".join(df.columns[:60])
        failed_ids = failed_ids or []
        remediation = remediation or {"logic": remediation_logic}
        failed_records_context = failed_records_context or {}
        remediation_json = json.dumps(remediation, default=str, indent=2)
        failed_context_json = json.dumps(failed_records_context, default=str, indent=2)

        prompt = f"""
You are an expert PySpark developer generating TARGETED remediation code.

CONTEXT:
- The DataFrame `df` contains the FULL dataset.
- Only apply changes to records whose `{id_column}` is in: {failed_ids}
- Use the id_column `{id_column}` to target only the failing rows.

Dataset columns: {schema_str}
Column mapping (business name → actual column name): {mapped_dict}
Selected remediation object:
{remediation_json}

Remediation logic:
{remediation_logic}

Failed records evidence:
{failed_context_json}

STRICT RULES:
1. Use `from pyspark.sql.functions import col, when, lit` (and others as needed)
2. DataFrame is named `df`; return the modified version as `df`
3. Only modify records where col('{id_column}').isin({failed_ids})
4. Use `when(...).otherwise(col(...))` pattern — do NOT drop rows unless action_type is filter
5. Use only target_columns from the remediation object, mapped_dict values, and failed-record target_columns
6. Do NOT modify `{id_column}`
7. If action_type is filter, filter only rows matching the failed_id condition and the stated invalid condition
8. Preserve all non-failed records unchanged
9. Output ONLY valid JSON

Output format:
{{
  "pyspark_code": "<executable PySpark code as a single string with \\n>"
}}

Example for "fill null account_number with UNKNOWN for failed records":
{{
  "pyspark_code": "from pyspark.sql.functions import col, when, lit\\n\\ndf = df.withColumn('account_number', when(col('{id_column}').isin({failed_ids[:5]}) & col('account_number').isNull(), lit('UNKNOWN')).otherwise(col('account_number')))"
}}
"""
        payload = {
            "messages": [
                {"role": "system", "content": "You generate targeted PySpark remediation code as strict JSON."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }
        result  = self._call_api_with_retry(payload, {})
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load(content)
    
    def generate_remediation_code_multi(self, dfs, involved_tables, tables_meta,
                                     remediation_logic, mapped_dict,
                                     failed_ids=None, id_column=None,
                                     remediation=None,
                                     failed_records_context=None):
        """
        Called for multi-table datasets where the rule involves MORE THAN ONE sheet.

        Instead of a single df, the LLM is given full schema context for each
        involved table and told the df_TableName variables available in scope.
        The LLM generates the join + remediation logic itself.

        dfs             : { sheet_name: spark_df }  — already enriched with generated_id
        involved_tables : list of sheet names this rule touches
        tables_meta     : { sheet_name: { "columns": [...] } }
        """
        failed_ids = failed_ids or []
        remediation = remediation or {"logic": remediation_logic}
        failed_records_context = failed_records_context or {}
        remediation_json = json.dumps(remediation, default=str, indent=2)
        failed_context_json = json.dumps(failed_records_context, default=str, indent=2)

        # Build per-table schema info
        table_schemas = {}
        for tbl in involved_tables:
            table_schemas[tbl] = list(dfs[tbl].columns)

        # Build join info between involved tables
        join_info_lines = []
        for i in range(len(involved_tables)):
            for j in range(i + 1, len(involved_tables)):
                t1, t2  = involved_tables[i], involved_tables[j]
                cols1   = set(table_schemas[t1])
                cols2   = set(table_schemas[t2])
                common  = list(cols1 & cols2)
                if common:
                    join_info_lines.append(
                        f"- {t1} and {t2} share common columns (use for join): {common}"
                    )
                else:
                    join_info_lines.append(
                        f"- {t1} and {t2} have NO common columns"
                    )
        join_info = "\n".join(join_info_lines) if join_info_lines else "No common columns found."

        # Build df variable name listing for the prompt
        df_var_lines = []
        for tbl in involved_tables:
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", tbl)
            df_var_lines.append(
                f"  df_{safe}  →  table '{tbl}'  →  columns: {table_schemas[tbl]}"
            )
        df_vars_str = "\n".join(df_var_lines)

        prompt = f"""
    You are an expert PySpark developer generating TARGETED remediation code
    for a MULTI-TABLE dataset.

    --------------------------------------------------

    🚨 STRICT OUTPUT RULES (MANDATORY):

    - Return ONLY valid JSON
    - DO NOT include explanation or extra text
    - DO NOT include markdown
    - Output must start with {{ and end with }}
    - Escape all newline characters using \\n

    --------------------------------------------------

    📋 MULTI-TABLE CONTEXT:

    This remediation involves {len(involved_tables)} table(s): {involved_tables}

    Available DataFrames already in execution scope:
    {df_vars_str}

    Join information:
    {join_info}

    --------------------------------------------------

    📥 INPUT:

    ID column (already available as variable `id_column`): {id_column}
    Failed record IDs to target: {failed_ids}

    Column mapping (business name → actual column name): {mapped_dict}
    Selected remediation object:
    {remediation_json}

    Remediation logic to apply: {remediation_logic}

    Failed records evidence:
    {failed_context_json}

    --------------------------------------------------

    ⚙️ CODE GENERATION REQUIREMENTS (MANDATORY):

    1. Load DataFrames using ONLY the df_TableName variables shown above
    (already in scope — do NOT use spark.read, spark.table, spark.createDataFrame)

    2. If the remediation requires data from multiple tables:
    - Join them on the common columns listed in Join information above
    - Assign the joined result to df_work

    3. If the remediation only affects ONE table:
    - Use that table's df_TableName directly
    - Assign it to df_work

    4. Apply remediation ONLY to records where col('{id_column}').isin({failed_ids})
    - Use when(...).otherwise(col(...)) pattern for modifications
    - Do NOT drop rows unless the logic explicitly says to filter/remove

    5. After applying the remediation, write the result back to the original
    df_TableName variable (so the session DataFrame is updated):
    e.g. df_Territory = df_Territory.withColumn(...)

    6. Also assign the final modified DataFrame to `df` for the result block

    7. ID column is PROVIDED externally as variable: id_column
    Current value: {id_column}

    🚨 CRITICAL:
    - DO NOT redefine id_column anywhere
    - DO NOT write id_column = '...'
    - DO NOT use spark.read or spark.table
    - All DataFrames are already loaded as df_TableName variables
    - Strictly use the values of the {mapped_dict} as required columns in the code

    8. Resolve all column names via mapped_dict values before using in code
    9. Column names are plain strings — no backtick quoting
    10. Wrap EVERYTHING in try-except
    11. Assign the final modified df to variable `df` at the end
    12. Use only target_columns from the remediation object, mapped_dict values,
        and failed-record target_columns
    13. Do NOT modify `{id_column}`
    14. Preserve non-failed records unchanged

    --------------------------------------------------

    📤 OUTPUT FORMAT (STRICT):

    {{
    "pyspark_code": "try:\\n    from pyspark.sql.functions import col, when, lit\\n\\n    # Load tables\\n    df_work = df_Table1.join(df_Table2, on=['common_col'], how='inner')\\n    # OR for single table: df_work = df_Table1\\n\\n    # Apply remediation only to failed records\\n    df_work = df_work.withColumn(\\n        'column_name',\\n        when(col('{id_column}').isin({failed_ids[:5] if failed_ids else []}) & col('column_name').isNull(), lit('replacement')).otherwise(col('column_name'))\\n    )\\n\\n    # Write back to original table variable\\n    df_Table1 = df_work  # or the specific table that was modified\\n    df = df_work\\n\\nexcept Exception as e:\\n    raise Exception(f'Remediation failed: {{str(e)}}')"
    }}

    🚨 FINAL VALIDATION BEFORE OUTPUT:
    - id_column must NOT be assigned or redefined anywhere
    - All DataFrames loaded using df_TableName variables only
    - Remediation applied ONLY to records in failed_ids
    - df assigned at the end so execute_remediation can read it
    - Code must be fully executable as-is
    """

        payload = {
            "messages": [
                {"role": "system", "content": "You generate targeted PySpark remediation code for multi-table datasets as strict JSON."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload, {})
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load(content)
    
    def enrich_rule(self, rule, schema):

        prompt = f"""
    You are a Data Quality expert.

    Given a rule and dataset schema, classify:

    1. complexity → simple | medium | complex
    2. category → completeness | validity | consistency | accuracy

    Return ONLY JSON:

    {{
    "complexity": "...",
    "category": "..."
    }}

    Dataset:
    {schema}

    Rule:
    Name: {rule['name']}
    Description: {rule['description']}
    Business Rule: {rule['business_rule']}
    """

        payload = {
            "messages": [
                {"role": "system", "content": "You classify data quality rules."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }


        result = self._call_api_with_retry(payload, {})

        content = result["choices"][0]["message"]["content"]

        return self._safe_json_load(content)

