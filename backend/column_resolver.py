'''
import re
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")


from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

class ColumnResolver:
    def __init__(self,dataset_columns):
        self.dataset_columns = dataset_columns
        self.model =  SentenceTransformer("all-MiniLM-L6-v2")
        self.column_embeddings = self.model.encode(dataset_columns)
        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL
    
    def normalize(self,text):
        text = text.lower()
        text = text.replace("_"," ")
        text = re.sub(r"[^a-z0-9 ]", "", text)
        return text
    

    def extract_entity_and_conversion(self,dataset_columns,rule):
        prompt = f"""
        You extract columns from rules and convert column names from the bussiness rules to real
        column names present in the Dataset.

        Return ONLY list of JSON.
        
        Understand the business rules and extract the column names as entity from
        the business rules as values for the key "entity" of the JSON output and find 
        possible matching column from the Dataset columns {dataset_columns} 
        for the particular column extracted from the business rule 
        and return them as values of the JSON output.
        Also return the confidence scores for all the columns in the dataset as a 
        list in the same order as they are present in the dataset the scores should be  
        between 0 and 1 on the basis of the token matching formula you 
        would apply with the dataset columns as LLM score.
         
        If a rule contains more than 1 column then give list of JSON 
        outputs for the respective columns in the rule.

        The values of the JSON output should be a string.
        
        Example:
        Business rule: Performance Date must be less than or equal to Period End Date.
        Output:
        [{{
          "entity": "Performance Date",
          "column": "perf_date",
          "llm_scores": [ 0.11413847,  0.10774598,  0.13146713, 0.77867434,   0.14131579,  0.07127768
                        -0.00113139,  0.15643278,  0.08496414,  0.07214927, -0.02477538, -0.01672722
                        0.03742597,  0.08728956,  0.12339534,  0.09549795,  0.03623211,  0.0150523,
                        0.05763124,  0.0686496 ]
        }},
        {{
          "entity": "Period End Date",
          "column": "period_end",
          "llm_score": [0.15619636, 0.05553747, 0.14979048, 0.41115177, 0.85360882,  0.10363387
                        0.0865946,  0.04539054, 0.0660622,  0.0574693,  0.27918896, 0.08438981
                        0.12631638, 0.12469309, 0.16212073, 0.1321456,  0.01041027, 0.03692239
                        0.02488876, 0.1388839 ]
        }}]
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
                {"role": "system", "content": "You convert column names from the rules to Dataset column names."},
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

        return parsed_json
    
    final_result = []

    def resolve(self,rules_df):
        mapping = {}
        final_result = []
        for _, row in rules_df.iterrows():

            rule = {
                "name": row["name"],
                "description": row["description"],
                "business_rule": row["business_rule"],
                "complexity": row["complexity"],
                "category": row["category"]
            }
            data_columns = self.dataset_columns
            result = self.extract_entity_and_conversion(data_columns,rule)
            final_result.extend(result)

        for i in final_result:
            entity = i["entity"]   
            entity_norm  = self.normalize(entity)
            entity_embeddings = self.model.encode([entity])[0]
            cosine_scores = cosine_similarity(
                [entity_embeddings] , self.column_embeddings
            )[0]
            
            scores = []

            for j, col in enumerate(self.dataset_columns):
            
                col_norm = self.normalize(col)

                fuzzy_score = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                cosine_score = cosine_scores[j]
                llm_score = float(i['llm_scores'][j])
                final_score = (0.5 * llm_score) + (0.3 * cosine_score) + (0.2 * fuzzy_score)

                scores.append((col, final_score))

            scores.sort(key=lambda x: x[1], reverse=True)
            mapping[entity] = scores[0][0]
        return mapping
'''
'''
import re
import requests
import json
import os
import time
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")


class ColumnResolver:
    def __init__(self, dataset_columns):
        self.dataset_columns = dataset_columns

        # Load model once
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

        # Precompute embeddings
        self.column_embeddings = self.model.encode(dataset_columns)

        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL

    
    def normalize(self, text):
        text = text.lower()
        text = text.replace("_", " ")
        text = re.sub(r"[^a-z0-9 ]", "", text)
        return text

   
    def _call_api_with_retry(self, payload, headers, max_retries=5):
        for attempt in range(max_retries):
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

        # Extract JSON array
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

   
    def extract_entity_and_conversion(self, rule):

        # Reduce token size
        columns_str = ", ".join(self.dataset_columns[:50])
        column_index = {}
        for i,col in enumerate(self.dataset_columns):
            column_index[i] = col

        prompt = f"""
        You extract columns from business rules and map them to dataset columns.

        STRICT INSTRUCTIONS:
        - Return ONLY valid JSON array
        - No explanation, no markdown
        - Output must start with [ and end with ]
        - Ensure JSON is parseable

        Dataset columns:
        {columns_str}
        
        Extract the column names as entity from the business rules with the  interpreting that for the business rules 
        you have to generate pyspark/sql queries.

        Return format:
        [
        {{
            "entity": "column from Business rule",
            "column": "matching column from {columns_str}"
            "llm_scores": [float list same length as dataset columns]
        }}
        ]
        The llm_scores should be between 0 and 1 on the basis of the token matching formula you 
        would apply between the rule and the dataset columns as LLM score.
        If a rule contains more than 1 column then give list of JSON 
        outputs for the respective columns in the rule.
        Also return the llm scores for all the columns in the dataset as a 
        list in the same order as they are present in the dataset.The column that matched maximum 
        with entity should have the maximum llm_score i.e the index of the column in the list of llm_scores 
        should have the maximum score among all other llm_scores in that list.
        
       
        
        Example:
        Business rule: Performance Date must be less than or equal to Period End Date.
        Output:
        [{{
          "entity": "Performance Date",
          "column": "perf_date",
          "llm_scores": [ 0.11413847,  0.10774598,  0.13146713, 0.77867434,   0.14131579,  0.07127768
                        -0.00113139,  0.15643278,  0.08496414,  0.07214927, -0.02477538, -0.01672722
                        0.03742597,  0.08728956,  0.12339534,  0.09549795,  0.03623211,  0.0150523,
                        0.05763124,  0.0686496 ]
        }},
        {{
          "entity": "Period End Date",
          "column": "period_end",
          "llm_scores": [0.15619636, 0.05553747, 0.14979048, 0.41115177, 0.85360882,  0.10363387
                        0.0865946,  0.04539054, 0.0660622,  0.0574693,  0.27918896, 0.08438981
                        0.12631638, 0.12469309, 0.16212073, 0.1321456,  0.01041027, 0.03692239
                        0.02488876, 0.1388839 ]
        }}]
        Column wit its Index:
        {column_index}
        This represents a dictionary with keys as index positions and values as their corresponding
        columns.

        The llm_score for each column should be at the index of the column present in {column_index}
        in the list. 
        For example if column: "acct_number" and its index is 0 from {column_index}
        then the llm_score of "acct_number" should be at index 0 of the llm_scores list.

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
                {"role": "system", "content": "You map business rule entities to dataset columns."},
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

        return self._safe_json_load(content)

    
    def resolve(self, rules_df):

        mapping = {}
        final_result = []

        # Step 1: LLM extraction
        for _, row in rules_df.iterrows():

            rule = {
                "name": row["name"],
                "description": row["description"],
                "business_rule": row["business_rule"],
                "complexity": row["complexity"],
                "category": row["category"]
            }

            try:
                result = self.extract_entity_and_conversion(rule)
                final_result.extend(result)
                time.sleep(1.5)  # prevent rate burst
            except Exception as e:
                print(f"❌ Error processing rule: {rule['name']} → {e}")
        print(final_result)
        # Step 2: Scoring
        for item in final_result:

            entity = item["entity"]
            llm_scores = item["llm_scores"]

            if not entity or not llm_scores:
                continue

            entity_norm = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]

            cosine_scores = cosine_similarity(
                [entity_embedding], self.column_embeddings
            )[0]

            scores = []

            for j, col in enumerate(self.dataset_columns):

                try:
                    col_norm = self.normalize(col)

                    fuzzy_score = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = cosine_scores[j]

                    llm_score = float(llm_scores[j]) if j < len(llm_scores) else 0.0
                    
                    final_score = (
                        0.5 * llm_score +
                        0.3 * cosine_score +
                        0.2 * fuzzy_score
                    )

                    scores.append((col, final_score))
                    
                except Exception as e:
                    print(f"⚠️ Skipping column {col}: {e}")

            #print(scores)
            #print('\n')
            # Select best match
            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity] = scores[0][0]

        return mapping
'''
'''
import re
import requests
import json
import os
import time
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")
#AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")  # e.g. gpt-4o
#AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "2024-02-15-preview")

class ColumnResolver:
    def __init__(self, dataset_columns):
        self.dataset_columns = dataset_columns

        # Load model once
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

        # Precompute embeddings
        self.column_embeddings = self.model.encode(dataset_columns)

        self.api_key = GROK_API_KEY
        self.url = GROK_BASE_URL
        #self.api_version = AZURE_API_VERSION
        #self.deployment = AZURE_DEPLOYMENT_NAME
    
    def normalize(self, text):
        text = text.lower()
        text = text.replace("_", " ")
        text = re.sub(r"[^a-z0-9 ]", "", text)
        return text

   
    def _call_api_with_retry(self, payload, headers, max_retries=5):
        for attempt in range(max_retries):
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

        # Extract JSON array
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

   
    def extract_entity_and_conversion(self, rule):

        # Reduce token size
        columns_str = ", ".join(self.dataset_columns)
        column_index = {}
        for i,col in enumerate(self.dataset_columns):
            column_index[i] = col

        prompt = f"""
       You are a data extraction specialist with extensive experience in analyzing business rules and mapping them to relevant dataset columns. Your expertise lies in generating SQL or PySpark queries from the information provided.

---

Your task is to extract column names as entities from business rules and map them to the dataset columns. Here are the details you need to include in your analysis:

- Dataset columns: {columns_str}
- Column with index: {column_index}
- Business Rule: {rule['business_rule']}
- Complexity: {rule['complexity']}
- Category: {rule['category']}

---

The output should be formatted as a valid JSON array that adheres to the following structure:

[
  {{
    "entity": "column from Business rule",
    "column": "matching column from {columns_str}",
    "llm_scores": [float list same length as dataset columns]
  }}
]

The llm_scores should be between 0 and 1, reflecting the token matching formula you apply between the rule and the dataset columns. If a rule contains multiple columns, generate a separate JSON output for each entity.

---

Key points to remember in your extraction:

- Entities are column names or field names mentioned in the rule.
- They are usually noun phrases representing data fields.
- Ignore conditions, verbs, and logic words.
- Preserve original wording exactly as written.
- Do NOT infer or modify names.
- The llm_score for each column should be positioned in the list according to its index in the {column_index}.
- The llm_score should be decided like how much was the probability that you gave the column as an output for the particular entity.
- Ensure JSON is parseable, starts with [ and ends with ].
- Return only the JSON array with no additional explanation or markdown.

---

Example of input and expected output format:

Business Rule: __________ (e.g., "Performance Date must be less than or equal to Period End Date.")
Output:
[
  {{
    "entity": "Performance Date",
    "column": "perf_date",
    "llm_scores": [0.11413847, 0.10774598, 0.13146713, 0.77867434, 0.14131579, 0.07127768, -0.00113139, 0.15643278, 0.08496414, 0.07214927, -0.02477538, -0.01672722, 0.03742597, 0.08728956, 0.12339534, 0.09549795, 0.03623211, 0.0150523, 0.05763124, 0.0686496]
  }},
  {{
    "entity": "Period End Date",
    "column": "period_end",
    "llm_scores": [0.15619636, 0.05553747, 0.14979048, 0.41115177, 0.85360882,  0.10363387, 0.0865946,  0.04539054, 0.0660622,  0.0574693,  0.27918896, 0.08438981, 0.12631638, 0.12469309, 0.16212073, 0.1321456,  0.01041027, 0.03692239, 0.02488876, 0.1388839 ]
   }}
]
    """

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": "You map business rule entities to dataset columns and give the probabilities of mapped columns."},
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

        return self._safe_json_load(content)

    
    def resolve(self, rules_df, weights):

        mapping = {}
        final_result = []

        # Step 1: LLM extraction
        for _, row in rules_df.iterrows():

            rule = {
                "name": row["name"],
                "description": row["description"],
                "business_rule": row["business_rule"],
                "complexity": row["complexity"],
                "category": row["category"]
            }

            try:
                result = self.extract_entity_and_conversion(rule)
                final_result.extend(result)
                time.sleep(1.5)  # prevent rate burst
            except Exception as e:
                print(f"❌ Error processing rule: {rule['name']} → {e}")
        print(final_result)
        # Step 2: Scoring
        for item in final_result:

            entity = item["entity"]
            llm_scores = item["llm_scores"]

            if not entity or not llm_scores:
                continue

            entity_norm = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]

            cosine_scores = cosine_similarity(
                [entity_embedding], self.column_embeddings
            )[0]

            scores = []

            for j, col in enumerate(self.dataset_columns):

                try:
                    col_norm = self.normalize(col)

                    fuzzy_score = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = cosine_scores[j]

                    llm_score = float(llm_scores[j]) if j < len(llm_scores) else 0.0
                    
                    final_score = (
                        weights["llm"]/100 * llm_score +
                        weights["cosine"]/100 * cosine_score +
                        weights["fuzzy"]/100 * fuzzy_score
                    )

                    scores.append((col, final_score))
                    
                except Exception as e:
                    print(f"⚠️ Skipping column {col}: {e}")

            #print(scores)
            #print('\n')
            # Select best match
            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity] = scores[0][0]

        return mapping
'''
'''
import re
import json
import os
import time
import httpx
from openai import AzureOpenAI
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class ColumnResolver:

    def __init__(self, dataset_columns):
        self.dataset_columns   = list(dataset_columns)
        self.model             = SentenceTransformer("all-MiniLM-L6-v2")
        self.column_embeddings = self.model.encode(self.dataset_columns)
        self.client            = AzureOpenAI(
            api_key        = AZURE_OPENAI_API_KEY,
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_version    = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    def normalize(self, text):
        text = text.lower().replace("_", " ").replace(".", " ")
        return re.sub(r"[^a-z0-9 ]", "", text)

    def _call_api_with_retry(self, payload, headers, max_retries=5):
        """
        headers param kept for signature compatibility — not used for Azure.
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

                content = response.choices[0].message.content

                return {
                    "choices": [
                        {"message": {"content": content}}
                    ]
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
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def extract_entity_and_conversion(self, rule):
        columns_str  = ", ".join(self.dataset_columns[:50])
        column_index = {i: c for i, c in enumerate(self.dataset_columns)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the dataset.

Dataset columns (may be "TableName.ColumnName" for multi-table datasets,
or plain sanitized names with underscores):
{columns_str}

Column index reference:
{column_index}

Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the rule",
    "column"    : "best matching column from the list above",
    "llm_scores": [<float per column, same length as dataset columns, values 0-1>]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- llm_scores length MUST equal {len(self.dataset_columns)}.
- llm_scores[i] = probability that dataset_columns[i] is the right match.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to dataset columns and output strict JSON arrays."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {}

        result = self._call_api_with_retry(payload, headers)

        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load(content)

    def resolve(self, rules_df, weights):
        mapping      = {}
        final_result = []

        for _, row in rules_df.iterrows():
            rule = {
                "name":          row.get("name", ""),
                "description":   row.get("description", ""),
                "business_rule": row.get("business_rule", ""),
                "complexity":    row.get("complexity", ""),
                "category":      row.get("category", ""),
            }
            try:
                result = self.extract_entity_and_conversion(rule)
                final_result.extend(result)
                time.sleep(1.5)
            except Exception as e:
                print(f"❌ Error processing rule '{rule['name']}': {e}")

        for item in final_result:
            entity     = item.get("entity")
            llm_scores = item.get("llm_scores", [])

            if not entity or not llm_scores:
                continue

            entity_norm      = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]
            cosine_scores    = cosine_similarity(
                [entity_embedding], self.column_embeddings
            )[0]

            scores = []
            for j, col in enumerate(self.dataset_columns):
                try:
                    col_norm     = self.normalize(col)
                    fuzzy_score  = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = float(cosine_scores[j])
                    llm_score    = float(llm_scores[j]) if j < len(llm_scores) else 0.0

                    final_score = (
                        weights["llm"]    / 100 * llm_score +
                        weights["cosine"] / 100 * cosine_score +
                        weights["fuzzy"]  / 100 * fuzzy_score
                    )
                    scores.append((col, final_score))
                except Exception as e:
                    print(f"⚠️ Skipping column '{col}': {e}")

            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity] = scores[0][0]

        return mapping
'''
'''
import re
import json
import os
import time
import httpx
from openai import AzureOpenAI
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class ColumnResolver:

    def __init__(self, dataset_columns):
        self.dataset_columns   = list(dataset_columns)
        self.model             = SentenceTransformer("all-MiniLM-L6-v2")
        self.column_embeddings = self.model.encode(self.dataset_columns)
        self.client            = AzureOpenAI(
            api_key        = AZURE_OPENAI_API_KEY,
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_version    = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    # ── Utilities ─────────────────────────────────────────────────────────────

    def normalize(self, text):
        text = text.lower().replace("_", " ").replace(".", " ")
        return re.sub(r"[^a-z0-9 ]", "", text)

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
                    print(f"⏳ Azure rate limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Azure OpenAI API Error: {error_str}")

        raise Exception("Max retries exceeded")

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        # Fix: replace Python list comprehensions with literal JSON arrays
        # e.g. [0 for _ in range(57)] → [0, 0, 0, ..., 0]
        def expand_comprehension(match):
            try:
                value = match.group(1).strip()
                count = int(match.group(2))
                return "[" + ", ".join([value] * count) + "]"
            except Exception:
                return match.group(0)

        content = re.sub(
            r"\[(\S+)\s+for\s+_\s+in\s+range\((\d+)\)\]",
            expand_comprehension,
            content
        )

        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def _safe_json_load_object(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    # ── STEP 1: Identify which tables a rule involves ─────────────────────────

    def identify_tables_for_rule(self, rule, table_names):
        """
        Ask the LLM which tables from the dataset are involved in this rule.
        Returns a list of table names e.g. ["Rep", "Territory"]
        """
        prompt = f"""
You are a data analyst. Given a business rule and a list of table names,
identify which tables are needed to validate this rule.

Available tables:
{table_names}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

OUTPUT FORMAT — strict JSON object, no markdown, no explanation:
{{
  "involved_tables": ["TableName1", "TableName2"]
}}

Rules:
- Only include tables from the available list above.
- Include a table if any column from it is mentioned or implied in the rule.
- If the rule involves joining data across tables, include all relevant tables.
- If the rule applies to only one table, return just that one.
- Return ONLY the JSON object. Start with {{ and end with }}.
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You identify which database tables are involved in a business rule. Output strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result = self._call_api_with_retry(payload, {})

        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        parsed  = self._safe_json_load_object(content)
        involved = parsed.get("involved_tables", [])

        # Validate — only keep names that actually exist in the dataset
        valid = [t for t in involved if t in table_names]

        # Fallback: if nothing matched, use all tables
        if not valid:
            print(f"⚠️ No valid tables identified for rule '{rule.get('name')}', using all tables")
            valid = list(table_names)

        print(f"📋 Rule '{rule.get('name')}' → tables: {valid}")
        return valid

    # ── STEP 2: Extract entities and score against scoped column pool ─────────

    def extract_entity_and_conversion(self, rule):
        """
        Extract entities from rule and score them against self.dataset_columns.
        self.dataset_columns should already be scoped to the relevant tables
        before calling this method.
        """
        columns_str  = ", ".join(self.dataset_columns)
        column_index = {i: c for i, c in enumerate(self.dataset_columns)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the dataset.

Dataset columns:
{columns_str}

Column index reference:
{column_index}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the Business Rule",
    "column"    : "best matching column from the list above",
    "llm_scores": [<float per column, same length as dataset columns, values 0-1>]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- llm_scores length MUST equal {len(self.dataset_columns)}.
- llm_scores[i] = probability that dataset_columns[i] is the right match.
- If an entity has no good match, fill llm_scores with {len(self.dataset_columns)} literal zeros like: [0, 0, 0, ...]
- entity extracted from the Business Rule should be the exact word from the Business Rule , DO NOT make your own entity.
- CRITICAL: NEVER use Python syntax like [0 for _ in range(N)] — JSON only, literal numbers.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to dataset columns and output strict JSON arrays. Never use Python list comprehensions in JSON output."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result = self._call_api_with_retry(payload, {})

        if "choices" not in result or not result["choices"]:
            raise Exception("Invalid API response")

        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)

    # ── STEP 3: Weighted scoring ───────────────────────────────────────────────

    def _score_entities(self, final_result, weights):
        """
        Given extracted entities with llm_scores, compute the weighted
        final score using LLM + cosine + fuzzy and return the best column match.
        """
        mapping = {}
        ranked_scores = {}

        for item in final_result:
            entity     = item.get("entity")
            llm_scores = item.get("llm_scores", [])

            if not entity or not llm_scores:
                continue

            entity_norm      = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]
            cosine_scores    = cosine_similarity(
                [entity_embedding], self.column_embeddings
            )[0]

            scores = []
            for j, col in enumerate(self.dataset_columns):
                try:
                    col_norm     = self.normalize(col)
                    fuzzy_score  = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = float(cosine_scores[j])
                    llm_score    = float(llm_scores[j]) if j < len(llm_scores) else 0.0

                    final_score = (
                        weights["llm"]    / 100 * llm_score +
                        weights["cosine"] / 100 * cosine_score +
                        weights["fuzzy"]  / 100 * fuzzy_score
                    )
                    scores.append((col, final_score))
                except Exception as e:
                    print(f"⚠️ Skipping column '{col}': {e}")

            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity] = scores[0][0]
                ranked_scores[entity] = scores
                print(f"   ✅ '{entity}' → '{scores[0][0]}' (score: {scores[0][1]:.3f})")

        return mapping, ranked_scores

    # ── Full resolve pipeline (single-table — original behavior) ──────────────

    def resolve(self, rules_df, weights):
        """
        Original single-table resolve — iterates all rules,
        extracts entities, scores against self.dataset_columns.
        """
        mapping      = {}
        final_result = []

        for _, row in rules_df.iterrows():
            rule = {
                "name":          row.get("name", ""),
                "description":   row.get("description", ""),
                "business_rule": row.get("business_rule", ""),
                "complexity":    row.get("complexity", ""),
                "category":      row.get("category", ""),
            }
            try:
                result = self.extract_entity_and_conversion(rule)
                final_result.extend(result)
                time.sleep(1.5)
            except Exception as e:
                print(f"❌ Error processing rule '{rule['name']}': {e}")

        mapping, ranked_scores = self._score_entities(final_result, weights)
        return mapping, ranked_scores

    # ── Multi-table resolve per rule ───────────────────────────────────────────

    def resolve_for_rule(self, rule, tables_meta, weights):
        """
        Multi-table resolve for a SINGLE rule:
        1. Ask LLM which tables are involved
        2. Build scoped column pool from those tables only
        3. Re-init embeddings for scoped pool
        4. Extract entities and score

        Returns:
            mapped_dict  : { entity: column_name }
            involved_tables: [ "Sheet1", "Sheet2" ]
        """
        #table_names = list(tables_meta.keys())

        # Step 1 — identify involved tables
        involved_tables = self.identify_tables_for_rule(rule, tables_meta)

        # Step 2 — build scoped column pool from involved tables only
        scoped_columns = []
        for tbl in involved_tables:
            cols = tables_meta[tbl]["columns"]   # already sanitized
            scoped_columns.extend(cols)

        if not scoped_columns:
            print(f"⚠️ No columns found for tables {involved_tables}, falling back to all columns")
            for tbl in table_names:
                scoped_columns.extend(tables_meta[tbl]["columns"])

        # Step 3 — re-init embeddings for the scoped pool
        self.dataset_columns   = scoped_columns
        self.column_embeddings = self.model.encode(scoped_columns)

        # Step 4 — extract entities and score
        try:
            extracted = self.extract_entity_and_conversion(rule)
            print(extracted)
            time.sleep(1.5)
        except Exception as e:
            print(f"❌ Entity extraction failed for rule '{rule.get('name')}': {e}")
            return {}, involved_tables

        mapped_dict, ranked_scores = self._score_entities(extracted, weights)

        return mapped_dict, ranked_scores, involved_tables
'''

'''
import re
import json
import os
import time
import httpx
from openai import AzureOpenAI
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class ColumnResolver:

    def __init__(self, dataset_columns, target_schema=None, tables_meta = None):
        """
        dataset_columns : list of raw column names from the uploaded dataset.
        target_schema   : optional list of dicts from target_schema.json, e.g.
                          [{"name": "account_number", "type": "string", "category": "account"}, ...]
                          When supplied the resolver runs the two-hop mapping:
                            entity → target-schema column → dataset column
        """
        self.dataset_columns   = list(dataset_columns)
        self.model             = SentenceTransformer("all-MiniLM-L6-v2")
        self.column_embeddings = self.model.encode(self.dataset_columns) if self.dataset_columns else []

        # ── Target-schema support ────────────────────────────────────────────
        self.target_schema = target_schema or []
        self.tables_meta   = tables_meta or {}
        self._schema_names = [col["name"] for col in self.target_schema] if self.target_schema else []
        self._schema_embeddings = (
            self.model.encode(self._schema_names) if self._schema_names else []
        )

        self.client = AzureOpenAI(
            api_key        = AZURE_OPENAI_API_KEY,
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_version    = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    # ── Utilities ─────────────────────────────────────────────────────────────

    def normalize(self, text):
        text = text.lower().replace("_", " ").replace(".", " ")
        return re.sub(r"[^a-z0-9 ]", "", text)

    def _call_api_with_retry(self, payload, headers=None, max_retries=5):
        messages    = payload.get("messages", [])
        temperature = payload.get("temperature", 0)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model       = self.deployment,
                    messages    = messages,
                    temperature = temperature,
                    max_tokens  = payload.get("max_tokens", 4000),
                )
                content = response.choices[0].message.content
                return {"choices": [{"message": {"content": content}}]}
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = (attempt + 1) * 5
                    print(f"⏳ Azure rate limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Azure OpenAI API Error: {error_str}")

        raise Exception("Max retries exceeded")

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        def expand_comprehension(match):
            try:
                value = match.group(1).strip()
                count = int(match.group(2))
                return "[" + ", ".join([value] * count) + "]"
            except Exception:
                return match.group(0)

        content = re.sub(
            r"\[(\S+)\s+for\s+_\s+in\s+range\((\d+)\)\]",
            expand_comprehension,
            content
        )

        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def _safe_json_load_object(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    # ── STEP 1: Identify which tables a rule involves ─────────────────────────

    def identify_tables_for_rule(self, rule, table_names):
        """
        Ask the LLM which tables from the dataset are involved in this rule.
        Returns a list of table names e.g. ["Rep", "Territory"]
        """
        prompt = f"""
You are a data analyst. Given a business rule and a list of table names,
identify which tables are needed to validate this rule.

Available tables:
{table_names}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

OUTPUT FORMAT — strict JSON object, no markdown, no explanation:
{{
  "involved_tables": ["TableName1", "TableName2"]
}}

Rules:
- Only include tables from the available list above.
- Include a table if any column from it is mentioned or implied in the rule.
- If the rule involves joining data across tables, include all relevant tables.
- If the rule applies to only one table, return just that one.
- Return ONLY the JSON object. Start with {{ and end with }}.
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You identify which database tables are involved in a business rule. Output strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload)
        content = result["choices"][0]["message"]["content"]
        parsed  = self._safe_json_load_object(content)
        involved = parsed.get("involved_tables", [])

        valid = [t for t in involved if t in table_names]
        if not valid:
            print(f"⚠️ No valid tables identified for rule '{rule.get('name')}', using all tables")
            valid = list(table_names)

        print(f"📋 Rule '{rule.get('name')}' → tables: {valid}")
        return valid

    # ── STEP 2-A: Extract entities and score against a dataset column pool ────

    def extract_entity_and_conversion(self, rule):
        """
        Extract entities from rule and score them against self.dataset_columns.
        self.dataset_columns should already be scoped to the relevant column pool
        before calling this method.
        """
        columns_str  = ", ".join(self.dataset_columns)
        column_index = {i: c for i, c in enumerate(self.dataset_columns)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the dataset.

Dataset columns:
{columns_str}

Column index reference:
{column_index}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}


OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the Business Rule",
    "column"    : "best matching column from the list above",
    "llm_scores": [<float per column, same length as dataset columns, values 0-1>]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- llm_scores length MUST equal {len(self.dataset_columns)}.
- llm_scores[i] = probability that dataset_columns[i] is the right match.
- If an entity has no good match, fill llm_scores with {len(self.dataset_columns)} literal zeros like: [0, 0, 0, ...]
- entity extracted from the Business Rule should be the exact word from the Business Rule, DO NOT make your own entity.
- CRITICAL: NEVER use Python syntax like [0 for _ in range(N)] — JSON only, literal numbers.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to dataset columns and output strict JSON arrays. Never use Python list comprehensions in JSON output."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload)
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)

    # ── STEP 2-B (TWO-HOP): Extract entities → target-schema columns ──────────

    def _extract_entity_to_schema(self, rule, cached_entities):
        """
        Like extract_entity_and_conversion but maps entities to TARGET SCHEMA
        columns (with their type/category context) rather than raw dataset columns.
        Used as the first hop of the two-hop mapping.
        """
        schema_desc  = ", ".join(
            f"{col['name']} ({col['type']}, {col['category']})"
            for col in self.target_schema
        )
        column_index = {i: col["name"] for i, col in enumerate(self.target_schema)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the TARGET SCHEMA below.

Target Schema columns (name, type, category):
{schema_desc}

Column index reference:
{column_index}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

Entities to map (DO NOT change these — use exactly as given):
{cached_entities}

OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the Business Rule",
    "column"    : "best matching target schema column name",
    "top_scores": [
        {{"index": <int>, "score": <float>}},
        ... (top 5 matches only, by descending score)
    ]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- top_scores: return ONLY the top 5 column indices with their scores (0-1).
- Do NOT return all {len(self.target_schema)} scores — only the top 5.
- index refers to the position in the column index reference above.
- Use type and category context to improve matching accuracy.
- entity should be the exact wording from the Business Rule.
- CRITICAL: NEVER use Python syntax like [0 for _ in range(N)] — JSON only, literal numbers.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to target schema columns using type and category context. Output strict JSON arrays only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload)
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)

    # ── STEP 3: Weighted scoring ───────────────────────────────────────────────

    def _score_entities(self, final_result, weights, target_columns=None, target_embeddings=None):
        """
        Given extracted entities with llm_scores, compute the weighted final score
        using LLM + cosine + fuzzy and return the best column match.

        target_columns   : if provided, score against these instead of self.dataset_columns
        target_embeddings: pre-computed embeddings for target_columns
        """
        col_pool   = target_columns    if target_columns    is not None else self.dataset_columns
        col_embeds = target_embeddings if target_embeddings is not None else self.column_embeddings

        mapping       = {}
        ranked_scores = {}

        for item in final_result:
            entity     = item.get("entity")
            llm_scores = item.get("llm_scores", [])
            
            if not llm_scores:
            # Reconstruct full array from compact top_scores
                top_scores = item.get("top_scores", [])
                llm_scores = [0.0] * len(col_pool)
                for entry in top_scores:
                    idx   = entry.get("index", -1)
                    score = entry.get("score", 0.0)
                    if 0 <= idx < len(llm_scores):
                        llm_scores[idx] = float(score)

            if not entity or not llm_scores:
                continue

            entity_norm      = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]
            cosine_scores    = cosine_similarity([entity_embedding], col_embeds)[0]

            scores = []
            for j, col in enumerate(col_pool):
                try:
                    col_norm     = self.normalize(col)
                    fuzzy_score  = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = float(cosine_scores[j])
                    llm_score    = float(llm_scores[j]) if j < len(llm_scores) else 0.0

                    final_score = (
                        weights["llm"]    / 100 * llm_score +
                        weights["cosine"] / 100 * cosine_score +
                        weights["fuzzy"]  / 100 * fuzzy_score
                    )
                    scores.append((col, final_score))
                except Exception as e:
                    print(f"⚠️ Skipping column '{col}': {e}")

            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity]       = scores[0][0]
                ranked_scores[entity] = scores
                print(f"   ✅ '{entity}' → '{scores[0][0]}' (score: {scores[0][1]:.3f})")

        return mapping, ranked_scores
    
    def _build_scoped_pool(self, rule):
        """
        When tables_meta is available, ask the LLM which tables are involved in
        this rule and return only those tables' columns (with their embeddings).

        Falls back to self.dataset_columns / self.column_embeddings when
        tables_meta is not set.

        Returns:
            scoped_columns   : list[str]
            scoped_embeddings: np.ndarray
            involved_tables  : list[str]   (empty when no tables_meta)
        """
        if not self.tables_meta:
            return self.dataset_columns, self.column_embeddings, []

        table_names     = list(self.tables_meta.keys())
        involved_tables = self.identify_tables_for_rule(rule, table_names)

        scoped_columns = []
        for tbl in involved_tables:
            scoped_columns.extend(self.tables_meta[tbl]["columns"])

        if not scoped_columns:
            print(f"⚠️ No columns found for tables {involved_tables}, falling back to all columns")
            for tbl in table_names:
                scoped_columns.extend(self.tables_meta[tbl]["columns"])

        scoped_embeddings = self.model.encode(scoped_columns)
        return scoped_columns, scoped_embeddings, involved_tables

    # ── TWO-HOP RESOLVE ───────────────────────────────────────────────────────

    def _resolve_two_hop(self, rules_df, weights):
        """
        Two-hop mapping when a target_schema is provided:

        Hop 1: entity → target_schema_column   (LLM + cosine + fuzzy vs. schema names)
        Hop 2: target_schema_column → dataset_column  (LLM + cosine + fuzzy vs. dataset cols)
        Final: entity → dataset_column  (composition of the two hops)

        Returns:
            final_mapping  : { entity: dataset_column }
            hop1_mapping   : { entity: target_schema_column }
            hop2_mapping   : { target_schema_column: dataset_column }
            ranked_scores  : { entity: ranked_dataset_col_scores }
        """

        is_multi_table = bool(self.tables_meta)
        print(
            f"\n🔀 Running TWO-HOP mapping (entity → schema → dataset) "
            f"[{'multi-table' if is_multi_table else 'single-table'}]"
        )

        # ── HOP 1: entity → target schema column ─────────────────────────────
        hop1_raw = []
        rule_scoped_pool: dict = {}  # rule_name → (cols, embeds, tables)

        for _, row in rules_df.iterrows():
            rule = {
                "name":          row.get("name", ""),
                "description":   row.get("description", ""),
                "business_rule": row.get("business_rule", ""),
                "complexity":    row.get("complexity", ""),
                "category":      row.get("category", ""),
            }
            cached_entities = row.get("entities") if "entities" in rules_df.columns else None
            try:
                result = self._extract_entity_to_schema(rule, cached_entities)
                hop1_raw.extend(result)
                time.sleep(1.5)

                if is_multi_table:
                    scoped_cols, scoped_embeds, involved = self._build_scoped_pool(rule)
                    rule_scoped_pool[rule["name"]] = (scoped_cols, scoped_embeds, involved)

            except Exception as e:
                print(f"❌ HOP1 error for rule '{rule['name']}': {e}")

        hop1_mapping, _ = self._score_entities(
            hop1_raw, weights,
            target_columns    = self._schema_names,
            target_embeddings = self._schema_embeddings,
        )
        print(f"✅ HOP 1 complete — {len(hop1_mapping)} entity→schema mappings")

        # ── HOP 2: target schema column → dataset column ──────────────────────

        if is_multi_table:
            # Build reverse index: entity → rule_name
            entity_to_rule: dict = {}
            for _, row in rules_df.iterrows():
                rule_name = row.get("name", "")
                rule_obj  = {
                    "name":          rule_name,
                    "description":   row.get("description", ""),
                    "business_rule": row.get("business_rule", ""),
                    "complexity":    row.get("complexity", ""),
                    "category":      row.get("category", ""),
                }
                cached_entities = row.get("entities") if "entities" in rules_df.columns else None
                try:
                    extracted = self._extract_entity_to_schema(rule_obj, cached_entities)
                    for item in extracted:
                        entity = item.get("entity")
                        if entity:
                            entity_to_rule[entity] = rule_name
                except Exception:
                    pass

            hop2_mapping_multi: dict = {}
            hop2_ranked_multi:  dict = {}

            pairs_needed: set = set()
            for entity, schema_col in hop1_mapping.items():
                rule_name = entity_to_rule.get(entity)
                if rule_name:
                    pairs_needed.add((schema_col, rule_name))

            print(pairs_needed)
            
            for schema_col, rule_name in pairs_needed:
                meta = next((c for c in self.target_schema if c["name"] == schema_col), {})

                # Priority 1: "table" field on the schema entry → direct, no LLM call needed
                # Priority 2: rule_scoped_pool built via identify_tables_for_rule in hop-1
                # Priority 3: full flat dataset column list
                schema_table = meta.get("table_name")
                if schema_table and schema_table in self.tables_meta:
                    scoped_cols   = list(self.tables_meta[schema_table]["columns"])
                    scoped_embeds = self.model.encode(scoped_cols)
                    print(
                        f"   🏷️  Using schema 'table' field → scoping hop-2 pool "
                        f"to '{schema_table}' ({len(scoped_cols)} cols) "
                        f"for schema col '{schema_col}'"
                    )
                else:
                    scoped_cols, scoped_embeds, _ = rule_scoped_pool.get(
                        rule_name,
                        (self.dataset_columns, self.column_embeddings, []),
                    )
                    if not schema_table:
                        print(
                            f"   ℹ️  No 'table' on schema col '{schema_col}'; "
                            f"using rule-scoped pool for '{rule_name}'"
                        )

                synthetic_rule = {
                    "name":          schema_col,
                    "description":   (
                        f"Map target schema column '{schema_col}' "
                        f"(type: {meta.get('type','?')}, category: {meta.get('category','?')}"
                        + (f", table: {schema_table}" if schema_table else "")
                        + f") to dataset for rule '{rule_name}'"
                    ),
                    "business_rule": f"Find the dataset column that corresponds to '{schema_col}'",
                    "complexity":    "simple",
                    "category":      meta.get("category", "general"),
                }

                saved_cols,   self.dataset_columns   = self.dataset_columns,   scoped_cols
                saved_embeds, self.column_embeddings = self.column_embeddings, scoped_embeds

                try:
                    hop2_raw = self.extract_entity_and_conversion(synthetic_rule)
                    mapped, ranked = self._score_entities(hop2_raw, weights)
                    dataset_col = mapped.get(schema_col)
                    if dataset_col:
                        hop2_mapping_multi[(schema_col, rule_name)] = dataset_col
                        hop2_ranked_multi[(schema_col, rule_name)]  = ranked.get(schema_col, [])
                    else:
                        print(f"⚠️ HOP2 found no match for schema col '{schema_col}' / rule '{rule_name}'")
                except Exception as e:
                    print(f"❌ HOP2 error for (schema='{schema_col}', rule='{rule_name}'): {e}")
                finally:
                    self.dataset_columns   = saved_cols
                    self.column_embeddings = saved_embeds

            print(f"✅ HOP 2 complete (multi-table) — {len(hop2_mapping_multi)} schema→dataset mappings")

            # ── COMPOSE (multi-table) ─────────────────────────────────────────
            final_mapping     = {}
            ranked_scores     = {}
            hop2_mapping_flat = {}

            for entity, schema_col in hop1_mapping.items():
                rule_name   = entity_to_rule.get(entity)
                key         = (schema_col, rule_name)
                dataset_col = hop2_mapping_multi.get(key)
                if dataset_col:
                    final_mapping[entity]         = dataset_col
                    ranked_scores[entity]         = hop2_ranked_multi.get(key, [])
                    hop2_mapping_flat[schema_col] = dataset_col
                else:
                    print(
                        f"⚠️ No dataset column found for schema col '{schema_col}' "
                        f"(entity: '{entity}', rule: '{rule_name}')"
                    )

            print(f"✅ COMPOSITION complete — {len(final_mapping)} entity→dataset mappings")
            return final_mapping, hop1_mapping, hop2_mapping_flat, ranked_scores
        

        # ── HOP 1: entity → target schema column ─────────────────────────────
       

        # ── HOP 2: target schema column → dataset column ──────────────────────
        unique_schema_cols = list(set(hop1_mapping.values()))

        hop2_raw = []
        for schema_col in unique_schema_cols:
            meta = next((c for c in self.target_schema if c["name"] == schema_col), {})
            synthetic_rule = {
                "name":          schema_col,
                "description":   f"Map target schema column '{schema_col}' (type: {meta.get('type','?')}, category: {meta.get('category','?')}) to dataset",
                "business_rule": f"Find the dataset column that corresponds to '{schema_col}'",
                "complexity":    "simple",
                "category":      meta.get("category", "general"),
            }
            try:
                result = self.extract_entity_and_conversion(synthetic_rule)
                hop2_raw.extend(result)
            except Exception as e:
                print(f"❌ HOP2 error for schema column '{schema_col}': {e}")

        hop2_mapping, hop2_ranked = self._score_entities(hop2_raw, weights)
        print(f"✅ HOP 2 complete — {len(hop2_mapping)} schema→dataset mappings")

        # ── COMPOSE: entity → dataset column ─────────────────────────────────
        final_mapping = {}
        ranked_scores = {}
        for entity, schema_col in hop1_mapping.items():
            dataset_col = hop2_mapping.get(schema_col)
            if dataset_col:
                final_mapping[entity] = dataset_col
                ranked_scores[entity] = hop2_ranked.get(schema_col, [])
            else:
                print(f"⚠️ No dataset column found for schema col '{schema_col}' (entity: '{entity}')")

        print(f"✅ COMPOSITION complete — {len(final_mapping)} entity→dataset mappings")
        return final_mapping, hop1_mapping, hop2_mapping, ranked_scores

    # ── Full resolve pipeline ─────────────────────────────────────────────────

    def resolve(self, rules_df, weights):
        """
        If a target_schema was supplied → run two-hop mapping.
        Otherwise → original single-hop mapping.

        Returns:
            mapping       : { entity: dataset_column }
            ranked_scores : { entity: [(col, score), ...] }
            extra_info    : dict with hop1_mapping, hop2_mapping (empty when single-hop)
        """
        if self.target_schema:
            final_mapping, hop1, hop2, ranked_scores = self._resolve_two_hop(rules_df, weights)
            return final_mapping, ranked_scores, {"hop1_mapping": hop1, "hop2_mapping": hop2}

        # ── Original single-hop path ──────────────────────────────────────────
        final_result = []
        for _, row in rules_df.iterrows():
            rule = {
                "name":          row.get("name", ""),
                "description":   row.get("description", ""),
                "business_rule": row.get("business_rule", ""),
                "complexity":    row.get("complexity", ""),
                "category":      row.get("category", ""),
            }
            try:
                result = self.extract_entity_and_conversion(rule)
                final_result.extend(result)
                time.sleep(1.5)
            except Exception as e:
                print(f"❌ Error processing rule '{rule['name']}': {e}")

        mapping, ranked_scores = self._score_entities(final_result, weights)
        return mapping, ranked_scores, {}

    # ── Multi-table resolve per rule ───────────────────────────────────────────

    def resolve_for_rule(self, rule, tables_meta, weights):
        """
        Multi-table resolve for a SINGLE rule:
        1. Ask LLM which tables are involved
        2. Build scoped column pool from those tables only
        3. Re-init embeddings for scoped pool
        4. Extract entities and score (single-hop)

        Returns:
            mapped_dict    : { entity: column_name }
            ranked_scores  : { entity: [(col, score), ...] }
            involved_tables: [ "Sheet1", "Sheet2" ]
        """
        table_names = list(tables_meta.keys())
        involved_tables = self.identify_tables_for_rule(rule, table_names)

        scoped_columns = []
        for tbl in involved_tables:
            scoped_columns.extend(tables_meta[tbl]["columns"])

        if not scoped_columns:
            print(f"⚠️ No columns found for tables {involved_tables}, falling back to all columns")
            for tbl in table_names:
                scoped_columns.extend(tables_meta[tbl]["columns"])

        self.dataset_columns   = scoped_columns
        self.column_embeddings = self.model.encode(scoped_columns)

        try:
            extracted = self.extract_entity_and_conversion(rule)
            print(extracted)
        except Exception as e:
            print(f"❌ Entity extraction failed for rule '{rule.get('name')}': {e}")
            return {}, {}, involved_tables

        mapped_dict, ranked_scores = self._score_entities(extracted, weights)
        return mapped_dict, ranked_scores, involved_tables
'''

import re
import json
import os
import time
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import AzureOpenAI
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Singleton model — loaded once per process, shared across all ColumnResolver instances.
_SHARED_MODEL = None

def _get_shared_model():
    global _SHARED_MODEL
    if _SHARED_MODEL is None:
        _SHARED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _SHARED_MODEL


class ColumnResolver:

    def __init__(self, dataset_columns, target_schema=None, tables_meta=None):
        self.dataset_columns   = list(dataset_columns)
        self.model             = _get_shared_model()
        self.column_embeddings = self.model.encode(self.dataset_columns) if self.dataset_columns else []

        self.target_schema = target_schema or []
        self.tables_meta   = tables_meta or {}
        self._schema_names = [col["name"] for col in self.target_schema] if self.target_schema else []
        self._schema_embeddings = (
            self.model.encode(self._schema_names) if self._schema_names else []
        )

        self.client = AzureOpenAI(
            api_key        = AZURE_OPENAI_API_KEY,
            azure_endpoint = AZURE_OPENAI_ENDPOINT,
            api_version    = AZURE_OPENAI_API_VERSION,
            http_client    = httpx.Client(verify=False)
        )
        self.deployment = AZURE_OPENAI_DEPLOYMENT

    def normalize(self, text):
        text = text.lower().replace("_", " ").replace(".", " ")
        return re.sub(r"[^a-z0-9 ]", "", text)

    def _call_api_with_retry(self, payload, headers=None, max_retries=5):
        messages    = payload.get("messages", [])
        temperature = payload.get("temperature", 0)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model       = self.deployment,
                    messages    = messages,
                    temperature = temperature,
                    max_tokens  = payload.get("max_tokens", 4000),
                )
                content = response.choices[0].message.content
                return {"choices": [{"message": {"content": content}}]}
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = (attempt + 1) * 5
                    print(f"⏳ Azure rate limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Azure OpenAI API Error: {error_str}")

        raise Exception("Max retries exceeded")

    def _safe_json_load_array(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        def expand_comprehension(match):
            try:
                value = match.group(1).strip()
                count = int(match.group(2))
                return "[" + ", ".join([value] * count) + "]"
            except Exception:
                return match.group(0)

        content = re.sub(
            r"\[(\S+)\s+for\s+_\s+in\s+range\((\d+)\)\]",
            expand_comprehension,
            content
        )

        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def _safe_json_load_object(self, content):
        if not content or content.strip() == "":
            raise ValueError("Empty response from model")

        content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print("❌ Failed JSON:\n", content)
            raise

    def identify_tables_for_rule(self, rule, table_names):
        prompt = f"""
You are a data analyst. Given a business rule and a list of table names,
identify which tables are needed to validate this rule.

Available tables:
{table_names}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

OUTPUT FORMAT — strict JSON object, no markdown, no explanation:
{{
  "involved_tables": ["TableName1", "TableName2"]
}}

Rules:
- Only include tables from the available list above.
- Include a table if any column from it is mentioned or implied in the rule.
- If the rule involves joining data across tables, include all relevant tables.
- If the rule applies to only one table, return just that one.
- Return ONLY the JSON object. Start with {{ and end with }}.
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You identify which database tables are involved in a business rule. Output strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result   = self._call_api_with_retry(payload)
        content  = result["choices"][0]["message"]["content"]
        parsed   = self._safe_json_load_object(content)
        involved = parsed.get("involved_tables", [])

        valid = [t for t in involved if t in table_names]
        if not valid:
            print(f"⚠️ No valid tables identified for rule '{rule.get('name')}', using all tables")
            valid = list(table_names)

        print(f"📋 Rule '{rule.get('name')}' → tables: {valid}")
        return valid

    def extract_entity_and_conversion(self, rule):
        columns_str  = ", ".join(self.dataset_columns)
        column_index = {i: c for i, c in enumerate(self.dataset_columns)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the dataset.

Dataset columns:
{columns_str}

Column index reference:
{column_index}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}


OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the Business Rule",
    "column"    : "best matching column from the list above",
    "llm_scores": [<float per column, same length as dataset columns, values 0-1>]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- llm_scores length MUST equal {len(self.dataset_columns)}.
- llm_scores[i] = probability that dataset_columns[i] is the right match.
- If an entity has no good match, fill llm_scores with {len(self.dataset_columns)} literal zeros like: [0, 0, 0, ...]
- entity extracted from the Business Rule should be the exact word from the Business Rule, DO NOT make your own entity.
- CRITICAL: NEVER use Python syntax like [0 for _ in range(N)] — JSON only, literal numbers.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to dataset columns and output strict JSON arrays. Never use Python list comprehensions in JSON output."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload)
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)

    def _extract_entity_to_schema(self, rule, cached_entities):
        schema_desc  = ", ".join(
            f"{col['name']} ({col['type']}, {col['category']})"
            for col in self.target_schema
        )
        column_index = {i: col["name"] for i, col in enumerate(self.target_schema)}

        prompt = f"""
You are a data extraction specialist. Extract column entities from the business rule
and map each one to the closest column in the TARGET SCHEMA below.

Target Schema columns (name, type, category):
{schema_desc}

Column index reference:
{column_index}

Name          : {rule['name']}
Description   : {rule['description']}
Business Rule : {rule['business_rule']}
Complexity    : {rule['complexity']}
Category      : {rule['category']}

Entities to map (DO NOT change these — use exactly as given):
{cached_entities}

OUTPUT FORMAT — strict JSON array, no markdown, no explanation:
[
  {{
    "entity"    : "exact entity wording from the Business Rule",
    "column"    : "best matching target schema column name",
    "top_scores": [
        {{"index": <int>, "score": <float>}},
        ... (top 5 matches only, by descending score)
    ]
  }}
]

Rules:
- One JSON object per entity found in the rule.
- top_scores: return ONLY the top 5 column indices with their scores (0-1).
- Do NOT return all {len(self.target_schema)} scores — only the top 5.
- index refers to the position in the column index reference above.
- Use type and category context to improve matching accuracy.
- entity should be the exact wording from the Business Rule.
- CRITICAL: NEVER use Python syntax like [0 for _ in range(N)] — JSON only, literal numbers.
- Return ONLY the JSON array. Start with [ and end with ].
"""

        payload = {
            "messages": [
                {"role": "system",
                 "content": "You map business rule entities to target schema columns using type and category context. Output strict JSON arrays only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        result  = self._call_api_with_retry(payload)
        content = result["choices"][0]["message"]["content"]
        return self._safe_json_load_array(content)

    def _score_entities(self, final_result, weights, target_columns=None, target_embeddings=None):
        col_pool   = target_columns    if target_columns    is not None else self.dataset_columns
        col_embeds = target_embeddings if target_embeddings is not None else self.column_embeddings

        mapping       = {}
        ranked_scores = {}

        for item in final_result:
            entity     = item.get("entity")
            llm_scores = item.get("llm_scores", [])

            if not llm_scores:
                top_scores = item.get("top_scores", [])
                llm_scores = [0.0] * len(col_pool)
                for entry in top_scores:
                    idx   = entry.get("index", -1)
                    score = entry.get("score", 0.0)
                    if 0 <= idx < len(llm_scores):
                        llm_scores[idx] = float(score)

            if not entity or not llm_scores:
                continue

            entity_norm      = self.normalize(entity)
            entity_embedding = self.model.encode([entity])[0]
            cosine_scores    = cosine_similarity([entity_embedding], col_embeds)[0]

            scores = []
            for j, col in enumerate(col_pool):
                try:
                    col_norm     = self.normalize(col)
                    fuzzy_score  = fuzz.token_set_ratio(entity_norm, col_norm) / 100
                    cosine_score = float(cosine_scores[j])
                    llm_score    = float(llm_scores[j]) if j < len(llm_scores) else 0.0

                    final_score = (
                        weights["llm"]    / 100 * llm_score +
                        weights["cosine"] / 100 * cosine_score +
                        weights["fuzzy"]  / 100 * fuzzy_score
                    )
                    scores.append((col, final_score))
                except Exception as e:
                    print(f"⚠️ Skipping column '{col}': {e}")

            if scores:
                scores.sort(key=lambda x: x[1], reverse=True)
                mapping[entity]       = scores[0][0]
                ranked_scores[entity] = scores
                print(f"   ✅ '{entity}' → '{scores[0][0]}' (score: {scores[0][1]:.3f})")

        return mapping, ranked_scores

    def _build_scoped_pool(self, rule):
        if not self.tables_meta:
            return self.dataset_columns, self.column_embeddings, []

        table_names     = list(self.tables_meta.keys())
        involved_tables = self.identify_tables_for_rule(rule, table_names)

        scoped_columns = []
        for tbl in involved_tables:
            scoped_columns.extend(self.tables_meta[tbl]["columns"])

        if not scoped_columns:
            print(f"⚠️ No columns found for tables {involved_tables}, falling back to all columns")
            for tbl in table_names:
                scoped_columns.extend(self.tables_meta[tbl]["columns"])

        scoped_embeddings = self.model.encode(scoped_columns)
        return scoped_columns, scoped_embeddings, involved_tables

    def _resolve_two_hop(self, rules_df, weights):
        is_multi_table = bool(self.tables_meta)
        print(
            f"\n🔀 Running TWO-HOP mapping (entity → schema → dataset) "
            f"[{'multi-table' if is_multi_table else 'single-table'}]"
        )

        # ── HOP 1: entity → target schema column ─────────────────────────────
        hop1_raw = []
        rule_scoped_pool: dict = {}

        hop1_rows = [
            (
                {
                    "name":          row.get("name", ""),
                    "description":   row.get("description", ""),
                    "business_rule": row.get("business_rule", ""),
                    "complexity":    row.get("complexity", ""),
                    "category":      row.get("category", ""),
                },
                row.get("entities") if "entities" in rules_df.columns else None,
            )
            for _, row in rules_df.iterrows()
        ]

        def _hop1_worker(rule_entities_pair):
            rule, cached_entities = rule_entities_pair
            return rule, self._extract_entity_to_schema(rule, cached_entities)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_hop1_worker, pair): pair for pair in hop1_rows}
            for future in as_completed(futures):
                rule, _ = futures[future]
                try:
                    rule_out, result = future.result()
                    hop1_raw.extend(result)
                    if is_multi_table:
                        scoped_cols, scoped_embeds, involved = self._build_scoped_pool(rule_out)
                        rule_scoped_pool[rule_out["name"]] = (scoped_cols, scoped_embeds, involved)
                except Exception as e:
                    print(f"❌ HOP1 error for rule '{rule['name']}': {e}")

        hop1_mapping, ranked_scores_schema = self._score_entities(
            hop1_raw, weights,
            target_columns    = self._schema_names,
            target_embeddings = self._schema_embeddings,
        )
        print(f"✅ HOP 1 complete — {len(hop1_mapping)} entity→schema mappings")

        # ── HOP 2: target schema column → dataset column ──────────────────────
        if is_multi_table:
            entity_to_rule: dict = {}
            for _, row in rules_df.iterrows():
                rule_name = row.get("name", "")
                rule_obj  = {
                    "name":          rule_name,
                    "description":   row.get("description", ""),
                    "business_rule": row.get("business_rule", ""),
                    "complexity":    row.get("complexity", ""),
                    "category":      row.get("category", ""),
                }
                cached_entities = row.get("entities") if "entities" in rules_df.columns else None
                try:
                    extracted = self._extract_entity_to_schema(rule_obj, cached_entities)
                    for item in extracted:
                        entity = item.get("entity")
                        if entity:
                            entity_to_rule[entity] = rule_name
                except Exception:
                    pass

            hop2_mapping_multi: dict = {}
            hop2_ranked_multi:  dict = {}

            pairs_needed: set = set()
            for entity, schema_col in hop1_mapping.items():
                rule_name = entity_to_rule.get(entity)
                if rule_name:
                    pairs_needed.add((schema_col, rule_name))

            print(pairs_needed)

            for schema_col, rule_name in pairs_needed:
                meta         = next((c for c in self.target_schema if c["name"] == schema_col), {})
                schema_table = meta.get("table_name")

                if schema_table and schema_table in self.tables_meta:
                    scoped_cols   = list(self.tables_meta[schema_table]["columns"])
                    scoped_embeds = self.model.encode(scoped_cols)
                    print(
                        f"   🏷️  Using schema 'table' field → scoping hop-2 pool "
                        f"to '{schema_table}' ({len(scoped_cols)} cols) "
                        f"for schema col '{schema_col}'"
                    )
                else:
                    scoped_cols, scoped_embeds, _ = rule_scoped_pool.get(
                        rule_name,
                        (self.dataset_columns, self.column_embeddings, []),
                    )
                    if not schema_table:
                        print(
                            f"   ℹ️  No 'table' on schema col '{schema_col}'; "
                            f"using rule-scoped pool for '{rule_name}'"
                        )

                synthetic_rule = {
                    "name":          schema_col,
                    "description":   (
                        f"Map target schema column '{schema_col}' "
                        f"(type: {meta.get('type','?')}, category: {meta.get('category','?')}"
                        + (f", table: {schema_table}" if schema_table else "")
                        + f") to dataset for rule '{rule_name}'"
                    ),
                    "business_rule": f"Find the dataset column that corresponds to '{schema_col}'",
                    "complexity":    "simple",
                    "category":      meta.get("category", "general"),
                }

                saved_cols,   self.dataset_columns   = self.dataset_columns,   scoped_cols
                saved_embeds, self.column_embeddings = self.column_embeddings, scoped_embeds

                try:
                    hop2_raw = self.extract_entity_and_conversion(synthetic_rule)
                    mapped, ranked = self._score_entities(hop2_raw, weights)
                    dataset_col = mapped.get(schema_col)
                    if dataset_col:
                        hop2_mapping_multi[(schema_col, rule_name)] = dataset_col
                        hop2_ranked_multi[(schema_col, rule_name)]  = ranked.get(schema_col, [])
                    else:
                        print(f"⚠️ HOP2 found no match for schema col '{schema_col}' / rule '{rule_name}'")
                except Exception as e:
                    print(f"❌ HOP2 error for (schema='{schema_col}', rule='{rule_name}'): {e}")
                finally:
                    self.dataset_columns   = saved_cols
                    self.column_embeddings = saved_embeds

            print(f"✅ HOP 2 complete (multi-table) — {len(hop2_mapping_multi)} schema→dataset mappings")

            # ── COMPOSE (multi-table) ─────────────────────────────────────────
            final_mapping     = {}
            ranked_scores     = {}
            hop2_mapping_flat = {}

            for entity, schema_col in hop1_mapping.items():
                rule_name   = entity_to_rule.get(entity)
                key         = (schema_col, rule_name)
                dataset_col = hop2_mapping_multi.get(key)
                if dataset_col:
                    final_mapping[entity]         = dataset_col
                    ranked_scores[entity]         = hop2_ranked_multi.get(key, [])
                    hop2_mapping_flat[schema_col] = dataset_col
                else:
                    print(
                        f"⚠️ No dataset column found for schema col '{schema_col}' "
                        f"(entity: '{entity}', rule: '{rule_name}')"
                    )

            print(f"✅ COMPOSITION complete — {len(final_mapping)} entity→dataset mappings")
            return final_mapping, hop1_mapping, hop2_mapping_flat, ranked_scores_schema

        # ── Single-table HOP 2 ────────────────────────────────────────────────
        unique_schema_cols = list(set(hop1_mapping.values()))

        hop2_raw = []
        for schema_col in unique_schema_cols:
            meta = next((c for c in self.target_schema if c["name"] == schema_col), {})
            synthetic_rule = {
                "name":          schema_col,
                "description":   f"Map target schema column '{schema_col}' (type: {meta.get('type','?')}, category: {meta.get('category','?')}) to dataset",
                "business_rule": f"Find the dataset column that corresponds to '{schema_col}'",
                "complexity":    "simple",
                "category":      meta.get("category", "general"),
            }
            try:
                result = self.extract_entity_and_conversion(synthetic_rule)
                hop2_raw.extend(result)
            except Exception as e:
                print(f"❌ HOP2 error for schema column '{schema_col}': {e}")

        hop2_mapping, hop2_ranked = self._score_entities(hop2_raw, weights)
        print(f"✅ HOP 2 complete — {len(hop2_mapping)} schema→dataset mappings")

        final_mapping = {}
        ranked_scores = {}
        for entity, schema_col in hop1_mapping.items():
            dataset_col = hop2_mapping.get(schema_col)
            if dataset_col:
                final_mapping[entity] = dataset_col
                ranked_scores[entity] = hop2_ranked.get(schema_col, [])
            else:
                print(f"⚠️ No dataset column found for schema col '{schema_col}' (entity: '{entity}')")

        print(f"✅ COMPOSITION complete — {len(final_mapping)} entity→dataset mappings")
        return final_mapping, hop1_mapping, hop2_mapping, ranked_scores_schema

    def resolve(self, rules_df, weights):
        """
        Returns:
            mapped_dict       : { entity: schema_column }
            ranked_scores     : { entity: [(col, score), ...] }
            schema_to_dataset : { schema_column: dataset_column }
                                (identity when no target_schema)
        """
        if self.target_schema:
            # Two-hop: entity → schema_col → dataset_col
            final_mapping, hop1_mapping, hop2_mapping, ranked_scores = self._resolve_two_hop(rules_df, weights)
            # Return hop1 as mapped_dict (entity→schema_col)
            # Return hop2 as schema_to_dataset (schema_col→dataset_col)
            return hop1_mapping, ranked_scores, hop2_mapping

        # Single-hop: entity → dataset_col directly (no separate schema)
        rules_list = [
            {
                "name":          row.get("name", ""),
                "description":   row.get("description", ""),
                "business_rule": row.get("business_rule", ""),
                "complexity":    row.get("complexity", ""),
                "category":      row.get("category", ""),
            }
            for _, row in rules_df.iterrows()
        ]

        final_result = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(self.extract_entity_and_conversion, rule): rule for rule in rules_list}
            for future in as_completed(futures):
                rule = futures[future]
                try:
                    result = future.result()
                    final_result.extend(result)
                except Exception as e:
                    print(f"❌ Error processing rule '{rule['name']}': {e}")

        mapping, ranked_scores = self._score_entities(final_result, weights)
        # Identity: schema_col == dataset_col, so no rename needed
        schema_to_dataset = {v: v for v in mapping.values()}
        return mapping, ranked_scores, schema_to_dataset

    def resolve_for_rule(self, rule, tables_meta, weights):
        table_names     = list(tables_meta.keys())
        involved_tables = self.identify_tables_for_rule(rule, table_names)

        scoped_columns = []
        for tbl in involved_tables:
            scoped_columns.extend(tables_meta[tbl]["columns"])

        if not scoped_columns:
            print(f"⚠️ No columns found for tables {involved_tables}, falling back to all columns")
            for tbl in table_names:
                scoped_columns.extend(tables_meta[tbl]["columns"])

        self.dataset_columns   = scoped_columns
        self.column_embeddings = self.model.encode(scoped_columns)

        try:
            extracted = self.extract_entity_and_conversion(rule)
            print(extracted)
        except Exception as e:
            print(f"❌ Entity extraction failed for rule '{rule.get('name')}': {e}")
            return {}, {}, involved_tables

        mapped_dict, ranked_scores = self._score_entities(extracted, weights)
        return mapped_dict, ranked_scores, involved_tables