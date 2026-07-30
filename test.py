import os
import sys
 
os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.functions import col
from openpyxl import load_workbook
from openpyxl.styles import Alignment
#from grok_client import GrokClient
import re
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL")
'''
def extract_entity_and_conversion(dataset_columns,rule):
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
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": "You convert column names from the rules to Dataset column names."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }

        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(GROK_BASE_URL, headers=headers, json=payload)

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

spark = SparkSession.builder.appName("DQ_ENGINE").getOrCreate()
pdf = pd.read_excel("sample_source_data.xlsx")

df = spark.createDataFrame(pdf)

dataset_columns = df.columns
'''
rules_df = pd.read_excel("Business_Validation_Rules.xlsx")
rules_list = rules_df.to_dict(orient="records") if rules_df is not None else []
print(len(rules_list))
'''
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
model = SentenceTransformer("all-MiniLM-L6-v2")
def func():
      final_result = []
      for _, row in rules_df.iterrows():

            rule = {
                "name": row["name"],
                "description": row["description"],
                "business_rule": row["business_rule"],
                "complexity": row["complexity"],
                "category": row["category"]
            }
            result = extract_entity_and_conversion(dataset_columns,rule)
            final_result.extend(result)
      print(final_result)
      
      for i in final_result:
            entity = i["entity"]   
            column_embeddings = model.encode(dataset_columns)
            entity_embeddings = model.encode([entity])[0]
            cosine_scores = cosine_similarity(
                [entity_embeddings] , column_embeddings
            )[0]
            print(cosine_scores)
func()
'''