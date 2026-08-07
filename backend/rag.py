'''
import os
import json
from typing import List
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_community.embeddings import HuggingFaceEmbeddings
import httpx

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")

INTENT_CONFIG = {
    "schema_query": {
        "description": "Questions about dataset columns, tables, schema structure",
        "examples":    ["what columns does the dataset have", "which tables are there",
                        "what fields does Territory table have", "how many columns"],
        "doc_types":   ["dataset_overview", "table_schema", "column_list"],
    },
    "rule_query": {
        "description": "Questions about specific rules, business logic, what a rule validates",
        "examples":    ["what does rule 3 do", "which rules check for null",
                        "what is the business rule for", "how many rules",
                        "what category is rule", "list all rules"],
        "doc_types":   ["rule", "rules_summary"],
    },
    "mapping_query": {
        "description": "Questions about entity-to-column mappings, which column an entity maps to",
        "examples":    ["what column does account number map to",
                        "which entity maps to Territory_ID",
                        "what are the mappings for rule 2"],
        "doc_types":   ["entity_mappings", "rule"],
    },
    "execution_query": {
        "description": "Questions about execution results, pass rates, failed records, which rules passed or failed",
        "examples":    ["which rules failed", "what is the pass rate",
                        "how many records failed", "show me execution results",
                        "which rule has the worst pass rate"],
        "doc_types":   ["execution_results", "rules_summary"],
    },
    "rule_and_schema": {
        "description": "Questions that need both rule information and schema/column information together",
        "examples":    ["which columns does rule 3 use", "what fields are validated by",
                        "which table does rule 2 apply to"],
        "doc_types":   ["rule", "rules_summary", "table_schema", "dataset_overview", "entity_mappings"],
    },
    "general": {
        "description": "General questions or unclear intent — search everything",
        "examples":    ["tell me about the data", "give me a summary"],
        "doc_types":   None,   # None means search all doc types
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT BUILDER
# Converts session data into rich text documents for indexing
# ─────────────────────────────────────────────────────────────────────────────
def build_documents_from_session(session: dict) -> List[Document]:
    """
    Converts the uploaded dataset schema and rules into LangChain Documents
    that will be embedded and stored in the vector store.
    """
    docs = []

    # ── 1. Dataset schema document ────────────────────────────────────────────
    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})
        for table_name, meta in tables_meta.items():
            columns = meta.get("columns", [])
            content = f"""Table: {table_name}
Number of columns: {len(columns)}
Columns: {', '.join(columns)}
This table is part of a multi-table dataset."""
            docs.append(Document(
                page_content=content,
                metadata={"type": "table_schema", "table": table_name}
            ))

        # Also add a combined overview
        all_tables = list(tables_meta.keys())
        overview   = f"""Dataset Overview:
Type: Multi-table Excel dataset
Number of tables/sheets: {len(all_tables)}
Table names: {', '.join(all_tables)}
Total columns across all tables: {sum(len(m['columns']) for m in tables_meta.values())}"""
        docs.append(Document(
            page_content=overview,
            metadata={"type": "dataset_overview"}
        ))

    else:
        columns = session.get("columns", [])
        content = f"""Dataset Overview:
Type: Single-table dataset
Number of columns: {len(columns)}
All columns: {', '.join(columns)}"""
        docs.append(Document(
            page_content=content,
            metadata={"type": "dataset_overview"}
        ))

        # Create a doc per column group for better retrieval
        chunk_size = 20
        for i in range(0, len(columns), chunk_size):
            chunk = columns[i:i + chunk_size]
            docs.append(Document(
                page_content=f"Dataset columns (batch {i//chunk_size + 1}): {', '.join(chunk)}",
                metadata={"type": "column_list", "batch": i//chunk_size + 1}
            ))

    # ── 2. Individual rule documents ──────────────────────────────────────────
    rules_df = session.get("rules_df")
    if rules_df is not None:
        rules = rules_df.to_dict(orient="records")
        for i, rule in enumerate(rules):
            entities     = rule.get("entities", [])
            mapped_dict  = session.get("mapped_dict", {})
            entity_mappings = {
                e: mapped_dict.get(e, "not yet mapped")
                for e in (entities if isinstance(entities, list) else [])
            }

            involved_tables = ""
            rule_table_map  = session.get("rule_table_map", {})
            if rule_table_map.get(rule.get("name", "")):
                involved_tables = f"\nInvolved tables: {', '.join(rule_table_map[rule['name']])}"

            content = f"""Rule #{i+1}: {rule.get('name', '')}
Description: {rule.get('description', '')}
Business Rule: {rule.get('business_rule', '')}
Category: {rule.get('category', '')}
Complexity: {rule.get('complexity', '')}
Entities extracted: {', '.join(entities) if isinstance(entities, list) else ''}
Entity to column mappings: {json.dumps(entity_mappings, indent=2)}
{involved_tables}
Check type: {rule.get('check_type', 'not specified')}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":       "rule",
                    "rule_index": i + 1,
                    "rule_name":  rule.get("name", ""),
                    "category":   rule.get("category", ""),
                    "complexity":  rule.get("complexity", ""),
                }
            ))

        # ── 3. Rules summary document ─────────────────────────────────────────
        categories = {}
        for r in rules:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, []).append(r.get("name", ""))

        summary_lines = [
            f"Rules Summary:",
            f"Total rules: {len(rules)}",
            f"Rules by category:",
        ]
        for cat, names in categories.items():
            summary_lines.append(f"  {cat} ({len(names)}): {', '.join(names)}")

        summary_lines.append("\nAll rule names in order:")
        for i, r in enumerate(rules):
            summary_lines.append(f"  {i+1}. {r.get('name', '')} [{r.get('category','')}]")

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "rules_summary"}
        ))

    # ── 4. Execution results document (if any runs done) ─────────────────────
    executed_rules = session.get("executed_rules",set())
    passed_df = session.get("last_passed_df")
    failed_df = session.get("last_failed_df")
    rule_metrics = session.get("rule_metrics", {})
    if executed_rules and passed_df is not None and failed_df is not None and rule_metrics:
        exec_lines = ["Execution Results:"]
        for rule_name in executed_rules:
            exec_lines.append(
                f"  {rule_name}: passed={passed_df.count()}, "
                f"failed={failed_df.count()}, "
                f"pass_rate={rule_metrics.get(rule_name)}"
            )
        docs.append(Document(
            page_content="\n".join(exec_lines),
            metadata={"type": "execution_results"}
        ))

    # ── 5. Mapped entities document ───────────────────────────────────────────
    mapped_dict = session.get("mapped_dict", {})
    if mapped_dict:
        mapping_lines = ["Entity to Column Mappings (full list):"]
        for entity, column in mapped_dict.items():
            mapping_lines.append(f"  Entity '{entity}' → column '{column}'")
        docs.append(Document(
            page_content="\n".join(mapping_lines),
            metadata={"type": "entity_mappings"}
        ))

    return docs


# ─────────────────────────────────────────────────────────────────────────────
# RAG SYSTEM CLASS
# ─────────────────────────────────────────────────────────────────────────────
class DQRagSystem:

    def __init__(self):
        http_client = httpx.Client(verify=False)   # corporate SSL bypass
        self.embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2"
        )

        self.llm = AzureChatOpenAI(
            azure_endpoint   = AZURE_OPENAI_ENDPOINT,
            api_key          = AZURE_OPENAI_API_KEY,
            api_version      = AZURE_OPENAI_API_VERSION,
            azure_deployment = AZURE_OPENAI_DEPLOYMENT,
            temperature      = 0,
            http_client      = http_client,
        )

        self.vector_store = None
        self.retriever    = None
        self.chain        = None
        self.session_id   = None
        self.chat_history = []

        # Intent classification chain (built once, reused)
        self._intent_chain = None
        self._build_intent_classifier()

        # Answer chain (built after index is ready)
        self._answer_chain = None

    def _build_intent_classifier(self):
        """
        Build a lightweight LLM chain that classifies query intent.
        Returns one of the keys in INTENT_CONFIG.
        """
        intent_descriptions = "\n".join([
            f'- "{key}": {cfg["description"]}\n  Examples: {", ".join(cfg["examples"][:2])}'
            for key, cfg in INTENT_CONFIG.items()
        ])

        system_prompt = f"""You are a query intent classifier for a Data Quality Engine.

Classify the user's question into EXACTLY ONE of these intents:

{intent_descriptions}

Return ONLY the intent key as a single word — no explanation, no punctuation.
Examples of valid responses: schema_query, rule_query, mapping_query, execution_query, rule_and_schema, general"""

        self._intent_system = system_prompt
    
    def classify_intent(self, question: str, chat_history: list = None) -> str:
        """
        Use LLM to classify the query intent.
        Includes recent chat history for context-aware classification.
        e.g. "what about rule 2?" after asking about executions
             → should still be classified as execution_query
        """
        # Build context from recent history
        history_context = ""
        if chat_history:
            recent = chat_history[-4:]   # last 2 turns
            history_context = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:150]}"
                for m in recent
            ])

        messages = [
            SystemMessage(content=self._intent_system),
            HumanMessage(content=f"Question: {question}{history_context}"),
        ]

        try:
            response = self.llm.invoke(messages)
            intent   = response.content.strip().lower().replace('"', '').replace("'", "")

            # Validate — fall back to general if LLM returns something unexpected
            if intent not in INTENT_CONFIG:
                print(f"⚠️ Unknown intent '{intent}', falling back to general")
                intent = "general"

            print(f"🎯 Intent classified: '{question[:60]}...' → {intent}")
            return intent

        except Exception as e:
            print(f"⚠️ Intent classification failed: {e}, using general")
            return "general"
        

    def _get_chat_history(self,k=3):
        history = self.chat_history[-k:]
        return "\n".join(
            [f"User: {q}\nAssistant:{a}" for q,a in history]
        )
   
    def build_index(self, session: dict, session_id: str):
        """
        Build the FAISS vector index from session data.
        Called after upload or whenever the session changes significantly
        (new rules added, mappings generated, etc.).
        """
        print(f"🔍 Building RAG index for session {session_id}...")

        docs = build_documents_from_session(session)

        # Split long documents into smaller chunks for better retrieval
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=600, chunk_overlap=80
        )
        split_docs = splitter.split_documents(docs)

        print(f"📄 Indexing {len(split_docs)} document chunks from {len(docs)} source documents...")

        # Build FAISS vector store
        self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
       
        self.session_id   = session_id

        # Build the RAG chain
        self._build_chain()

        print(f"✅ RAG index built with {len(split_docs)} chunks")
        return len(split_docs)

    def update_index(self, session: dict):
        """
        Incrementally update the index when new data is added
        (e.g. after add_rule, after get_mappings, after execute_code).
        Rebuilds the full index — FAISS is fast enough for session-scale data.
        """
        if self.session_id is None:
            return
        self.build_index(session, self.session_id)
        
    def _get_filtered_retriever(self, intent: str):
        """
        Returns a retriever scoped to the document types
        relevant to the classified intent.
        """
        doc_types = INTENT_CONFIG[intent]["doc_types"]

        if doc_types is None:
            # general — search everything, no filter
            return self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 5},
            )

        # FAISS supports metadata filtering via filter dict
        return self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k":      6,
                "filter": {"type": {"$in": doc_types}},
            },
        )
    
    def _build_chain(self):
        """Build the LangChain RAG chain."""
        self._answer_prompt = ChatPromptTemplate.from_template("""
You are a Data Quality Engine assistant. Answer the user's question using ONLY 
the context and the chat history provided below from the uploaded dataset and rules
and what user is saying in the conversation.
                                                  
If the question is related to greeting or asking about you, say "Hi I am DQ agent I can answer you 
questions regarding Dataset, rules, entity mappings , rule execution results".

If the answer is not in the context and the chat history, say "I don't have that information in the 
current session" — do not make up answers.

Be concise and precise. When listing rules or columns, use numbered lists.
When referencing rule numbers, use the index from the context (Rule #1, Rule #2, etc.).

Chat history:
{chat_history}
                                                  
Context:
{context}

Question: {question}

Answer:""")
        #comment
        self.chain = (
            {
                "context":  self.retriever | self._format_docs,
                "question": RunnablePassthrough(),
                "chat_history": lambda _: self._get_chat_history()
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )

    @staticmethod
    def _format_docs(docs: List[Document]) -> str:
        return "\n\n---\n\n".join(d.page_content for d in docs)

    def query(self, question: str, chat_history: list) -> dict:
        """
        Run a question through the RAG chain.
        Returns answer + source document metadata for transparency.
        """
        if self.vector_store is None:
            return {
                "answer":  "RAG index not built yet. Please upload your dataset first.",
                "intent": "Unknown",
                "sources": []
            }
        
        intent   = self.classify_intent(question, chat_history)

        doc_types = INTENT_CONFIG[intent]["doc_types"]

        # ── Step 2: Get filtered retriever ────────────────────────────────────
        retriever = self._get_filtered_retriever(intent)

        try:
            retrieved_docs = retriever.invoke(question)
        except Exception as e:
            # FAISS filter may fail if no docs match — fall back to unfiltered
            print(f"⚠️ Filtered retrieval failed ({e}), falling back to unfiltered")
            retriever      = self.vector_store.as_retriever(search_kwargs={"k": 5})
            retrieved_docs = retriever.invoke(question)

        if not retrieved_docs:
            # Absolute fallback — unfiltered search
            print("⚠️ No docs retrieved after filter, using unfiltered")
            retriever      = self.vector_store.as_retriever(search_kwargs={"k": 5})
            retrieved_docs = retriever.invoke(question)

         # ── Step 4: Build context and answer ──────────────────────────────────
        context  = self._format_docs(retrieved_docs)

        # Include recent chat history in the prompt for continuity
        history_text = ""
        if chat_history:
            recent = chat_history[-4:]
            history_text = "\n\nRecent conversation context:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:200]}"
                for m in recent
            ])

        full_prompt = self._answer_prompt.format_messages(
            context  = context + history_text,
            question = question,
        )
        
        try:
            answer = self.llm.invoke(full_prompt).content
        except Exception as e:
            answer = f"Failed to generate answer: {str(e)}"

        # ── Step 5: Build source metadata ─────────────────────────────────────
        sources = []
        seen    = set()
        for doc in retrieved_docs:
            key = doc.metadata.get("rule_name") or doc.metadata.get("table") or doc.metadata.get("type")
            if key and key not in seen:
                seen.add(key)
                sources.append({
                    "type":      doc.metadata.get("type"),
                    "rule_name": doc.metadata.get("rule_name"),
                    "table":     doc.metadata.get("table"),
                    "snippet":   doc.page_content[:100] + "…",
                })

        print(f"✅ RAG answered — intent={intent}, sources={[s['type'] for s in sources]}")

        return {
            "answer":    answer,
            "intent":    intent,
            "doc_types": doc_types,
            "sources":   sources,
        }

        #comment
        try:
            answer = self.chain.invoke(question)
            self.chat_history.append((question,answer))
            # Also retrieve source docs so the caller knows what was used
            source_docs = self.retriever.invoke(question)
            sources = [
                {
                    "type":      d.metadata.get("type"),
                    "rule_name": d.metadata.get("rule_name"),
                    "table":     d.metadata.get("table"),
                    "snippet":   d.page_content[:120] + "…",
                }
                for d in source_docs
            ]

            return {"answer": answer, "sources": sources}

        except Exception as e:
            return {"answer": f"RAG query failed: {str(e)}", "sources": []}

    def is_ready(self) -> bool:
        return self.vector_store is not None


# ─────────────────────────────────────────────────────────────────────────────
# Singleton — one RAG system per server process
# Each session gets its own index via build_index()
# For multi-user, use a dict keyed by session_id
# ─────────────────────────────────────────────────────────────────────────────
RAG_STORE: dict[str, DQRagSystem] = {}


def get_or_create_rag(session_id: str) -> DQRagSystem:
    if session_id not in RAG_STORE:
        RAG_STORE[session_id] = DQRagSystem()
    return RAG_STORE[session_id]
'''
'''
import os
import sys
import re
import ssl

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable
os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

# Corporate proxy does SSL inspection — disable XetHub (hf-xet) so HuggingFace
# falls back to regular HTTPS downloads, then patch requests to skip verification
os.environ['HF_HUB_DISABLE_XET'] = '1'

ssl._create_default_https_context = ssl._create_unverified_context

import requests
requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)
_orig_send = requests.Session.send
def _patched_send(self, request, **kwargs):
    kwargs['verify'] = False
    return _orig_send(self, request, **kwargs)
requests.Session.send = _patched_send

import json
import time
from typing import List, Optional
from dotenv import load_dotenv
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
import httpx

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_table_field(col_def: dict) -> str:
    """Normalise table field — schema JSONs may use 'table' or 'table_name'."""
    return col_def.get("table_name")


def _build_dataset_col_type_map(session: dict) -> dict:
    """
    Build: dataset_column → {type, category, schema_col}

    Uses ALL available mapping paths:
      Path A: hop2_mapping (schema_col → dataset_col) reversed        ← two-hop
      Path B: hop1_mapping (entity → schema_col)
              + mapped_dict (entity → dataset_col) composed            ← two-hop
      Path C: mapped_dict (entity → dataset_col)
              + target_schema name match                               ← single-hop fallback
    """
    target_schema = session.get("target_schema", [])
    hop2_mapping  = session.get("hop2_mapping", {})
    hop1_mapping  = session.get("hop1_mapping", {})
    mapped_dict   = session.get("mapped_dict", {})

    schema_type_map: dict = {}
    for col in target_schema:
        name = col.get("name", "")
        if name:
            schema_type_map[name] = {
                "type":     col.get("type", "unknown"),
                "category": col.get("category", ""),
            }

    result: dict = {}

    # Path A: reverse hop2
    for schema_col, dataset_col in hop2_mapping.items():
        if dataset_col and schema_col in schema_type_map:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path B: compose hop1 + mapped_dict
    for entity, schema_col in hop1_mapping.items():
        dataset_col = mapped_dict.get(entity)
        if dataset_col and schema_col in schema_type_map and dataset_col not in result:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path C: single-hop fallback — match dataset col name to schema col name
    if schema_type_map:
        schema_names_lower = {
            name.lower().replace("_", " "): name
            for name in schema_type_map
        }
        for entity, dataset_col in mapped_dict.items():
            if dataset_col and dataset_col not in result:
                if dataset_col in schema_type_map:
                    info = schema_type_map[dataset_col]
                    result[dataset_col] = {
                        "type":       info["type"],
                        "category":   info["category"],
                        "schema_col": dataset_col,
                    }
                else:
                    normalised = dataset_col.lower().replace("_", " ")
                    matched_schema_col = schema_names_lower.get(normalised)
                    if matched_schema_col:
                        info = schema_type_map[matched_schema_col]
                        result[dataset_col] = {
                            "type":       info["type"],
                            "category":   info["category"],
                            "schema_col": matched_schema_col,
                        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# INTENT DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────
INTENT_CONFIG = {
    "temporal_query": {
        "description": (
            "Questions involving time, timestamps, dates — "
            "e.g. 'rules executed before 3 PM', 'latest run', "
            "'what ran today', 'execution order'"
        ),
        "examples": [
            "which rules ran before 3pm",
            "what was the last rule executed",
            "show rules executed after 2 Jan 2025",
            "which rule ran most recently",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "mathematical_query": {
        "description": (
            "Questions requiring calculation, aggregation, comparison, ranking, "
            "OR counting — including counting rows in the dataset/tables, "
            "counting columns, how many records, total rows, row counts per table, "
            "average pass rate, rule with most failures, total failed records, "
            "difference between pass rates."
        ),
        "examples": [
            "how many rows does the dataset have",
            "how many records are in the Territory table",
            "how many columns have type int",
            "count columns with type string",
            "total number of rows across all tables",
            "what is the average pass rate across all rules",
            "which rule has the most failed records",
            "rank rules by pass rate",
            "how many more records failed in rule 2 vs rule 3",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "filter_query": {
        "description": (
            "Questions that filter or search for rules/columns matching a condition — "
            "e.g. 'rules with pass rate below 80%', "
            "'rules in the financial category that failed'"
        ),
        "examples": [
            "rules with pass rate below 80 percent",
            "which rules failed more than 100 records",
            "show rules that belong to financial category and failed",
            "rules with complexity high that were executed",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "schema_data_query": {
        "description": (
            "Questions asking to LIST, SHOW, or TELL data types, categories, "
            "or properties of schema columns OR dataset columns (via mapping). "
            "Examples: 'tell me data types of all schema columns', "
            "'list all schema columns with their types', "
            "'what type is column X', "
            "'which columns are of type string', "
            "'what is the data type of <dataset_column>', "
            "'show dataset columns whose data type is string', "
            "'give columns whose data type is float', "
             "Also includes: 'what schema columns are in X table', "
            "'list schema columns for Orders table', "
            "'show me the schema of the Orders table', "
            "'what are the target schema columns in Products'. "
            "'what data type does acct_number map to'. "
            "Use for ANY question enumerating or describing column types/categories."
        ),
        "examples": [
            "tell me the data types of all schema columns",
            "list all schema columns with their types",
            "give columns whose data type is string",
            "what type is order_id",
            "show all target schema columns",
            "which columns belong to the financial category",
            "give dataset columns whose data type is string",
            "what schema columns are in the Orders table",    # ← add
            "list schema columns for the Products table",    # ← add
            "show schema columns in Orders",                 # ← add
            "what are the target schema columns in Customers",
            "what is the data type of acct_number",
            "what data type does closing_balance map to",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "schema_query": {
        "description": (
            "Questions about dataset structure, table names, which tables exist, "
            "general schema overview, which columns are in a table. "
            "NOT for listing data types — use schema_data_query for that."
        ),
        "examples": [
            "what columns does the dataset have",
            "which tables are there",
            "what fields does Territory table have",
            "show me the schema of the Orders table",
            "what is the structure of the dataset",
        ],
        "doc_types": [
            "dataset_overview", "target_schema",
            "table_schema", "column_list", "dataset_columns",
        ],
    },
    "rule_query": {
        "description": "Questions about specific rules, business logic, what a rule validates",
        "examples": [
            "what does rule 3 do", "which rules check for null",
            "what is the business rule for", "how many rules",
            "what category is rule", "list all rules",
        ],
        "doc_types": ["rule", "rules_summary"],
    },
    "mapping_query": {
        "description": (
            "Questions about entity-to-column mappings for any or all rules, "
            "which column an entity maps to, mappings for all rules, "
            "entity-to-target_column mappings, "
            "target_column-to-source_column mappings, "
            "show all mappings, what are the mappings"
        ),
        "examples": [
            "what column does account number map to",
            "show mappings for all rules",
            "what are the mappings for every rule",
            "What column in the schema is mapped to account number",
            "which entity maps to Territory_ID",
            "what are the mappings for rule 2",
        ],
        "doc_types": [
            "entity_mappings", "entity_mappings_summary",
            "entity_mappings_hop1", "entity_mappings_hop2", "rule",
        ],
    },
    "execution_query": {
        "description": (
            "Questions about execution results, pass rates, failed records, "
            "which rules passed or failed"
        ),
        "examples": [
            "which rules failed", "what is the pass rate",
            "how many records failed", "show me execution results",
            "which rule has the worst pass rate",
        ],
        "doc_types": ["execution_results", "rules_summary"],
    },
    "remediation_query": {
        "description": (
            "Questions about data remediation actions, remediation history, "
            "what remediations were applied, how many rows were fixed, "
            "remediation logic used, audit log of remediations"
        ),
        "examples": [
            "what remediations have been applied",
            "how many rows were fixed",
            "show me the remediation history",
            "what logic was used to fix the data",
            "how many records were remediated",
            "show remediation audit log",
        ],
        "doc_types": ["remediation_results", "remediation_summary"],
        "compute":   False,
    },
    "rule_and_schema": {
        "description": (
            "Questions that need both rule information and "
            "schema/column information together"
        ),
        "examples": [
            "which columns does rule 3 use",
            "what fields are validated by",
            "which table does rule 2 apply to",
        ],
        "doc_types": [
            "rule", "rules_summary", "table_schema", "dataset_overview",
            "target_schema", "entity_mappings", "entity_mappings_hop1",
        ],
    },
    "code_query": {
        "description": (
            "Questions about generated PySpark code, requests to show or give "
            "code for a rule, what code was generated, check types used. "
            "Includes: 'give code for rule 1', 'show code for rule 3', "
            "'display the pyspark code', 'was code generated for all rules', "
            "'what rules have code'"
        ),
        "examples": [
            "what code was generated for rule 3",
            "show me the pyspark code for",
            "give code for rule 1",
            "display code for rule 2",
            "what check type does rule 2 use",
            "which id column is used in the code",
            "was code generated for all rules",
            "what rules have code generated",
        ],
        "doc_types": ["generated_code", "generated_code_summary"],
    },
    "general": {
        "description": "General questions or unclear intent — search everything",
        "examples":    ["tell me about the data", "give me a summary"],
        "doc_types":   None,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def build_structured_snapshot(session: dict) -> dict:
    rules_df   = session.get("rules_df")
    rules_list = rules_df.to_dict(orient="records") if rules_df is not None else []

    rule_metrics  = session.get("rule_metrics", {})
    code_cache    = session.get("code_cache", {})
    target_schema = session.get("target_schema", [])

    run_log = []
    for i, rule in enumerate(rules_list):
        name = rule.get("name", "")
        if name in rule_metrics:
            result = session["result"][name]
            run_log.append({
                "rule_index":   i + 1,
                "rule_name":    name,
                "category":     rule.get("category", ""),
                "complexity":   rule.get("complexity", ""),
                "passed_count": result.get("passed_count", 0),
                "failed_count": result.get("failed_count", 0),
                "pass_rate":    result.get("pass_rate", 0.0),
                "timestamp":    session["timestamp"][name],
                "has_code":     name in code_cache,
                "check_type":   code_cache.get(name, {}).get("check_type", ""),
            })

    # Remediation — enriched summary for compute pipeline
    remediation_log  = session.get("remediation_log", [])
    total_rows_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
    remediation_summary = {
        "total_actions":    len(remediation_log),
        "total_rows_fixed": total_rows_fixed,
        "actions": [
            {
                "index":             i + 1,
                "rule_name":         e.get("rule_name", ""),
                "logic":             e.get("logic", ""),
                "rows_affected":     e.get("rows_affected", 0),
                "failed_ids_count":  len(e.get("failed_ids", [])),
                "timestamp":         e.get("timestamp", ""),
            }
            for i, e in enumerate(remediation_log)
        ],
    }

    # Dataset column → inferred type map (all 3 paths)
    dataset_col_type_map = _build_dataset_col_type_map(session)

    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})
        dfs         = session.get("dfs", {})
        tables_info = {}

        for table_name, meta in tables_meta.items():
            cols      = meta.get("columns", [])
            spark_df  = dfs.get(table_name)
            row_count = None
            if spark_df is not None:
                try:
                    row_count = spark_df.count()
                except Exception as e:
                    print(f"⚠️ Could not count rows for {table_name}: {e}")
            tables_info[table_name] = {
                "columns":      cols,
                "column_count": len(cols),
                "row_count":    row_count,
            }

        total_rows = sum(
            v["row_count"] for v in tables_info.values()
            if v["row_count"] is not None
        )

        schema_info: dict = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            table    = _get_table_field(col)
            name     = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            if table and name:
                schema_info.setdefault(table, {})[name] = {
                    "data_type": dtype,
                    "category":  category,
                }
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        schema = {
            "type":                         "multi_table",
            "tables":                       tables_info,
            "total_columns":                sum(len(m.get("columns", [])) for m in tables_meta.values()),
            "table_names":                  list(tables_meta.keys()),
            "total_rows_across_all_tables": total_rows,
            "target_schema":                target_schema,
            "schema_info":                  schema_info,
            "type_counts":                  type_counts,
            "category_counts":              cat_counts,
            "entity_mappings_hop1":         session.get("hop1_mapping", {}),
            "entity_mappings_hop2":         session.get("hop2_mapping", {}),
            "dataset_col_type_map":         dataset_col_type_map,
        }

    else:
        columns  = session.get("columns", [])
        spark_df = session.get("df")

        schema_columns    = []
        name_to_type      = {}
        name_to_category  = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            col_name = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            schema_columns.append(col_name)
            name_to_type[col_name]     = dtype
            name_to_category[col_name] = category
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        row_count = None
        if spark_df is not None:
            try:
                row_count = spark_df.count()
            except Exception as e:
                print(f"⚠️ Could not count rows: {e}")

        schema = {
            "type":                       "single_table",
            "columns":                    columns,
            "column_count":               len(columns),
            "row_count":                  row_count,
            "target_schema":              target_schema,
            "schema_columns":             schema_columns,
            "schema_columns_count":       len(schema_columns),
            "schema_columns_to_type":     name_to_type,
            "schema_columns_to_category": name_to_category,
            "type_counts":                type_counts,
            "category_counts":            cat_counts,
            "entity_mappings_hop1":       session.get("hop1_mapping", {}),
            "entity_mappings_hop2":       session.get("hop2_mapping", {}),
            "dataset_col_type_map":       dataset_col_type_map,
        }

    return {
        "rules":               rules_list,
        "run_log":             run_log,
        "rule_metrics":        rule_metrics,
        "remediation_log":     remediation_log,
        "remediation_summary": remediation_summary,
        "schema":              schema,
        "total_rules":         len(rules_list),
        "executed_count":      len(run_log),
        "code_generated_for":  list(code_cache.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_documents_from_session(session: dict) -> List[Document]:
    docs          = []
    target_schema = session.get("target_schema", [])

    dataset_col_type_map = _build_dataset_col_type_map(session)

    # ── Dataset schema ────────────────────────────────────────────────────────
    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})

        schema_lookup: dict = {}
        for col_def in target_schema:
            tbl  = _get_table_field(col_def)
            name = col_def.get("name", "")
            if tbl and name:
                schema_lookup.setdefault(tbl, {})[name] = {
                    "type":     col_def.get("type", "string"),
                    "category": col_def.get("category", ""),
                }

        for table_name, meta in tables_meta.items():
            columns    = meta.get("columns", [])
            tbl_schema = schema_lookup.get(table_name, {})

            raw_col_lines    = [f"  - {col}" for col in columns]
            schema_col_lines = []
            for col in columns:
                info  = tbl_schema.get(col, {})
                dtype = info.get("type")
                cat   = info.get("category", "")
                if dtype:
                    schema_col_lines.append(
                        f"  - {col}  [type: {dtype}"
                        + (f", category: {cat}]" if cat else "]")
                    )

            enriched_lines = []
            for col in columns:
                inferred = dataset_col_type_map.get(col, {})
                if inferred:
                    enriched_lines.append(
                        f"  - {col}  [inferred type: {inferred['type']}, "
                        f"via schema col: {inferred['schema_col']}]"
                    )
                else:
                    enriched_lines.append(
                        f"  - {col}  [type: unknown — not mapped to schema]"
                    )

            by_category: dict = {}
            for col in columns:
                cat = tbl_schema.get(col, {}).get("category", "unknown")
                by_category.setdefault(cat, []).append(col)

            category_summary = "; ".join(
                f"{cat}: {', '.join(cols)}"
                for cat, cols in sorted(by_category.items())
            )

            content = f"""Table: {table_name}
This table is part of a multi-table dataset.

DATASET COLUMNS (raw columns from uploaded file):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(raw_col_lines)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet)'}

TARGET SCHEMA COLUMNS for this table (explicit type from schema JSON):
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded for this table)'}
Columns grouped by category: {category_summary}"""

            docs.append(Document(
                page_content=content,
                metadata={"type": "table_schema", "table": table_name}
            ))

        

        type_counts:          dict = {}
        cat_counts:           dict = {}
        all_schema_col_lines: list = []
        all_dataset_col_lines: list = []

        for col_def in target_schema:
            tbl      = _get_table_field(col_def)
            col_name = col_def.get("name", "")
            dtype    = col_def.get("type", "string")
            category = col_def.get("category", "")
            label    = f"{tbl}.{col_name}" if tbl else col_name
            all_schema_col_lines.append(
                f"  - {label}  [type: {dtype}, category: {category}]"
            )
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        for tbl_name, meta in tables_meta.items():
            for col in meta.get("columns", []):
                all_dataset_col_lines.append(f"  - {tbl_name}.{col}")

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        all_tables = list(tables_meta.keys())
        overview   = f"""Dataset Overview:
Type: Multi-table Excel dataset
Number of tables/sheets: {len(all_tables)}
Table names: {', '.join(all_tables)}

DATASET COLUMNS (raw — no explicit type info):
Total: {sum(len(m['columns']) for m in tables_meta.values())}
{chr(10).join(all_dataset_col_lines) if all_dataset_col_lines else '  (none)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total schema columns: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(all_schema_col_lines) if all_schema_col_lines else '  (no schema loaded)'}

DATASET COLUMN INFERRED TYPES (via schema mapping):
{chr(10).join(f"  - {dc}  [type: {info['type']}, schema_col: {info['schema_col']}]" for dc, info in dataset_col_type_map.items()) if dataset_col_type_map else '  (no mappings yet)'}"""

        docs.append(Document(
            page_content=overview,
            metadata={"type": "dataset_overview"}
        ))

        for tbl_name, meta in tables_meta.items():
            cols = meta.get("columns", [])
            docs.append(Document(
                page_content=(
                    f"Raw dataset columns for table '{tbl_name}' "
                    f"(actual column names in the uploaded Excel — no type info):\n"
                    f"{', '.join(cols)}"
                ),
                metadata={"type": "dataset_columns", "table": tbl_name}
            ))

    else:
        # ── Single table ──────────────────────────────────────────────────────
        columns = session.get("columns", [])

        schema_col_lines = []
        for col_def in target_schema:
            name  = col_def.get("name", "")
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            schema_col_lines.append(
                f"  - {name}  [type: {dtype}"
                + (f", category: {cat}]" if cat else "]")
            )

        enriched_lines = []
        for col in columns:
            inferred = dataset_col_type_map.get(col, {})
            if inferred:
                enriched_lines.append(
                    f"  - {col}  [inferred type: {inferred['type']}, "
                    f"via schema col: {inferred['schema_col']}]"
                )
            else:
                enriched_lines.append(
                    f"  - {col}  [type: unknown — not mapped to schema]"
                )

        type_counts: dict = {}
        cat_counts:  dict = {}
        for col_def in target_schema:
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if cat:
                cat_counts[cat]      = cat_counts.get(cat, 0) + 1

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        content = f"""Dataset Overview:
Type: Single-table dataset

DATASET COLUMNS (raw — no explicit type info):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(f'  - {col}' for col in columns)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet — run /get_mappings first)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded)'}"""

        docs.append(Document(
            page_content=content,
            metadata={"type": "dataset_overview"}
        ))

        chunk_size = 20
        for i in range(0, len(columns), chunk_size):
            chunk = columns[i:i + chunk_size]
            docs.append(Document(
                page_content=(
                    f"DATASET COLUMNS (raw, batch {i//chunk_size + 1}): "
                    f"{', '.join(chunk)}"
                ),
                metadata={"type": "column_list", "batch": i//chunk_size + 1}
            ))

        docs.append(Document(
            page_content=(
                f"Raw dataset columns (no type info):\n{', '.join(columns)}"
            ),
            metadata={"type": "dataset_columns"}
        ))

    # ── Target schema — batched so splitter never truncates ───────────────────
    if target_schema:
        batch_size = 15
        for batch_start in range(0, len(target_schema), batch_size):
            batch         = target_schema[batch_start: batch_start + batch_size]
            batch_num     = batch_start // batch_size + 1
            total_batches = (len(target_schema) + batch_size - 1) // batch_size

            lines = [
                f"# Target Schema Reference "
                f"(batch {batch_num}/{total_batches}, "
                f"columns {batch_start+1}–{batch_start+len(batch)} "
                f"of {len(target_schema)} total)\n"
            ]

            by_category: dict = {}
            for col_def in batch:
                cat = col_def.get("category", "other")
                by_category.setdefault(cat, []).append(col_def)

            for category, cols in sorted(by_category.items()):
                lines.append(f"\n## Category: {category.upper()}")
                for col_def in cols:
                    name     = col_def.get("name", "")
                    dtype    = col_def.get("type", "string")
                    table    = _get_table_field(col_def)
                    tbl_part = f"  [table: {table}]" if table else ""
                    lines.append(f"  - {name}  [type: {dtype}]{tbl_part}")

            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":       "target_schema",
                    "batch":      batch_num,
                    "batch_cols": f"{batch_start+1}-{batch_start+len(batch)}",
                }
            ))

        # Dedicated dataset-col-type doc grouped by inferred type
        if dataset_col_type_map:
            dtype_lines = [
                "Dataset Column Inferred Data Types "
                "(inferred via schema mapping — hop2 reverse lookup):",
                "These types are NOT in the raw dataset; "
                "they are inferred by matching dataset columns to schema columns.",
                "",
            ]
            by_type: dict = {}
            for dc, info in dataset_col_type_map.items():
                by_type.setdefault(info["type"], []).append(
                    f"{dc} (via schema col: {info['schema_col']})"
                )
            for dtype, entries in sorted(by_type.items()):
                dtype_lines.append(f"Type '{dtype}':")
                for entry in entries:
                    dtype_lines.append(f"  - {entry}")

            docs.append(Document(
                page_content="\n".join(dtype_lines),
                metadata={"type": "dataset_col_types"}
            ))

    # ── Rules ─────────────────────────────────────────────────────────────────
    rules_df = session.get("rules_df")
    if rules_df is not None:
        rules = rules_df.to_dict(orient="records")
        for i, rule in enumerate(rules):
            entities    = rule.get("entities", [])
            mapped_dict = session.get("mapped_dict", {})
            entity_mappings = {
                e: mapped_dict.get(e, "not yet mapped")
                for e in (entities if isinstance(entities, list) else [])
            }
            involved_tables = ""
            rule_table_map  = session.get("rule_table_map", {})
            if rule_table_map.get(rule.get("name", "")):
                involved_tables = (
                    f"\nInvolved tables: "
                    f"{', '.join(rule_table_map[rule['name']])}"
                )

            content = f"""Rule #{i+1}: {rule.get('name', '')}
Description: {rule.get('description', '')}
Business Rule: {rule.get('business_rule', '')}
Category: {rule.get('category', '')}
Complexity: {rule.get('complexity', '')}
Entities extracted: {', '.join(entities) if isinstance(entities, list) else ''}
Entity to column mappings: {json.dumps(entity_mappings, indent=2)}
{involved_tables}
Check type: {rule.get('check_type', 'not specified')}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":       "rule",
                    "rule_index": i + 1,
                    "rule_name":  rule.get("name", ""),
                    "category":   rule.get("category", ""),
                    "complexity": rule.get("complexity", ""),
                }
            ))

        categories: dict = {}
        for r in rules:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, []).append(r.get("name", ""))

        summary_lines = [
            "Rules Summary:",
            f"Total rules: {len(rules)}",
            "Rules by category:",
        ]
        for cat, names in categories.items():
            summary_lines.append(f"  {cat} ({len(names)}): {', '.join(names)}")
        summary_lines.append("\nAll rule names in order:")
        for i, r in enumerate(rules):
            summary_lines.append(
                f"  {i+1}. {r.get('name', '')} [{r.get('category','')}]"
            )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "rules_summary"}
        ))

    # ── Execution results ─────────────────────────────────────────────────────
    executed_rules = session.get("executed_rules", set())
    rule_metrics   = session.get("rule_metrics", {})

    if executed_rules and rule_metrics:
        exec_lines = ["Execution Results:"]
        for rule_name in executed_rules:
            result = session["result"][rule_name]
            passed_count = result.get("passed_count",0)
            failed_count = result.get("failed_count",0)
            exec_lines.append(
                f"  {rule_name}: passed={passed_count}, "
                f"failed={failed_count}, "
                f"pass_rate={rule_metrics.get(rule_name)}, "
                f"timestamp: {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
            )
        docs.append(Document(
            page_content="\n".join(exec_lines),
            metadata={"type": "execution_results"}
        ))

    # ── Remediation results ───────────────────────────────────────────────────
    remediation_log = session.get("remediation_log", [])

    if remediation_log:
        for i, entry in enumerate(remediation_log):
            logic         = entry.get("logic", "")
            rows_affected = entry.get("rows_affected", 0)
            failed_ids    = entry.get("failed_ids", [])
            rule_name     = entry.get("rule_name", "not specified")
            timestamp     = entry.get(
                "timestamp",
                datetime.now().strftime('%d %b %Y %H:%M:%S')
            )

            content = f"""Remediation #{i+1}:
Rule: {rule_name}
Logic applied: {logic}
Rows affected / fixed: {rows_affected}
Failed IDs remediated: {len(failed_ids)} records
Timestamp: {timestamp}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":              "remediation_results",
                    "remediation_index": i + 1,
                    "rule_name":         rule_name,
                    "rows_affected":     rows_affected,
                }
            ))

        total_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
        rem_summary_lines = [
            "Remediation Summary:",
            f"Total remediation actions applied: {len(remediation_log)}",
            f"Total rows fixed across all remediations: {total_fixed}",
            "",
            "Remediation history:",
        ]
        for i, entry in enumerate(remediation_log):
            rem_summary_lines.append(
                f"  #{i+1}: logic='{entry.get('logic','')}', "
                f"rows_fixed={entry.get('rows_affected', 0)}, "
                f"rule='{entry.get('rule_name', 'N/A')}', "
                f"timestamp='{entry.get('timestamp', '')}'"
            )

        docs.append(Document(
            page_content="\n".join(rem_summary_lines),
            metadata={"type": "remediation_summary"}
        ))

    else:
        docs.append(Document(
            page_content=(
                "Remediation Summary:\n"
                "No remediations have been applied yet. "
                "Remediation actions appear here after you fix failed records."
            ),
            metadata={"type": "remediation_summary"}
        ))

    # ── Mapped entities — per rule + full summaries ───────────────────────────
    mapped_dict  = session.get("mapped_dict", {})
    mapped_hop_1 = session.get("hop1_mapping", {})
    mapped_hop_2 = session.get("hop2_mapping", {})

    if mapped_dict and rules_df is not None:
        rules = rules_df.to_dict(orient="records")

        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            rule_mappings      = {}
            rule_hop1_mappings = {}
            rule_hop2_mappings = {}

            for entity in entities:
                if entity in mapped_dict:
                    rule_mappings[entity] = mapped_dict[entity]
                if entity in mapped_hop_1:
                    rule_hop1_mappings[entity] = mapped_hop_1[entity]
                    schema_col = mapped_hop_1[entity]
                    if schema_col in mapped_hop_2:
                        rule_hop2_mappings[schema_col] = mapped_hop_2[schema_col]

            if not rule_mappings:
                continue

            lines = [
                f"Entity-Column Mappings for Rule #{i+1}: {rule_name}",
                f"Rule name: {rule_name}",
                f"Rule number: {i+1}",
            ]
            for entity, col in rule_mappings.items():
                inferred  = dataset_col_type_map.get(col, {})
                type_note = (
                    f" [inferred type: {inferred['type']}]"
                    if inferred else ""
                )
                lines.append(
                    f"  Entity '{entity}' → dataset column '{col}'{type_note}"
                )
            if rule_hop1_mappings:
                lines.append("Hop 1 (entity → target schema column):")
                for entity, schema_col in rule_hop1_mappings.items():
                    lines.append(
                        f"  Entity '{entity}' → schema column '{schema_col}'"
                    )
            if rule_hop2_mappings:
                lines.append("Hop 2 (schema column → dataset column):")
                for schema_col, dataset_col in rule_hop2_mappings.items():
                    inferred  = dataset_col_type_map.get(dataset_col, {})
                    type_note = (
                        f" [schema type: {inferred['type']}]"
                        if inferred else ""
                    )
                    lines.append(
                        f"  Schema column '{schema_col}' → "
                        f"dataset column '{dataset_col}'{type_note}"
                    )

            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":        "entity_mappings",
                    "rule_name":   rule_name,
                    "rule_number": i + 1,
                }
            ))

        summary_lines = [
            f"Complete Entity-Column Mappings for ALL {len(rules)} rules:",
        ]
        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            rule_pairs = [
                f"'{e}' → '{mapped_dict[e]}'"
                for e in entities if e in mapped_dict
            ]
            if rule_pairs:
                summary_lines.append(
                    f"  Rule #{i+1} ({rule_name}): {', '.join(rule_pairs)}"
                )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "entity_mappings_summary"}
        ))

        if mapped_hop_1:
            hop1_lines = [
                "Complete Entity → Target Schema Column Mappings for ALL rules:"
            ]
            for i, rule in enumerate(rules):
                entities = rule.get("entities", [])
                if not isinstance(entities, list):
                    entities = []
                pairs = [
                    f"'{e}' → '{mapped_hop_1[e]}'"
                    for e in entities if e in mapped_hop_1
                ]
                if pairs:
                    hop1_lines.append(
                        f"  Rule #{i+1} ({rule.get('name','')}): "
                        f"{', '.join(pairs)}"
                    )
            docs.append(Document(
                page_content="\n".join(hop1_lines),
                metadata={"type": "entity_mappings_hop1"}
            ))

        if mapped_hop_2:
            hop2_lines = [
                "Complete Target Schema Column → Dataset Column Mappings:"
            ]
            for schema_col, dataset_col in mapped_hop_2.items():
                inferred  = dataset_col_type_map.get(dataset_col, {})
                type_note = (
                    f" [schema type: {inferred['type']}]"
                    if inferred else ""
                )
                hop2_lines.append(
                    f"  Schema column '{schema_col}' → "
                    f"dataset column '{dataset_col}'{type_note}"
                )
            docs.append(Document(
                page_content="\n".join(hop2_lines),
                metadata={"type": "entity_mappings_hop2"}
            ))

    else:
        docs.append(Document(
            page_content=(
                "Entity-Column Mappings: No mappings generated yet. "
                "Please run /get_mappings first."
            ),
            metadata={"type": "entity_mappings"}
        ))
        docs.append(Document(
            page_content=(
                "Complete Entity-Column Mappings for ALL rules: "
                "No mappings generated yet."
            ),
            metadata={"type": "entity_mappings_summary"}
        ))

    # ── Generated code ────────────────────────────────────────────────────────
    code_cache = session.get("code_cache", {})

    if not code_cache:
        docs.append(Document(
            page_content=(
                "Generated Code Summary:\n"
                "No PySpark code has been generated yet for any rule. "
                "Code must be generated before it can be shown."
            ),
            metadata={"type": "generated_code_summary"}
        ))
    else:
        rules_df_local = session.get("rules_df")
        rule_index_map: dict = {}
        if rules_df_local is not None:
            for i, row in enumerate(rules_df_local.to_dict(orient="records")):
                rule_index_map[row.get("name", "")] = i + 1

        for rule_name, cached in code_cache.items():
            pyspark_code = cached.get("pyspark_code", "")
            mc           = cached.get("mapped_dict", {})
            check_type   = cached.get("check_type", "")
            id_column    = cached.get("id_column", "")
            rule_number  = rule_index_map.get(rule_name, "?")

            if not pyspark_code:
                continue

            content = f"""Generated PySpark Code for Rule #{rule_number}: {rule_name}
Rule number: {rule_number}
Rule name: {rule_name}
Also referred to as: rule {rule_number}, rule number {rule_number}, the {rule_number} rule
Check Type: {check_type}
ID Column used: {id_column}
Mapped columns used: {json.dumps(mc)}

Code:
{pyspark_code}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":        "generated_code",
                    "rule_name":   rule_name,
                    "rule_number": rule_number,
                    "check_type":  check_type,
                }
            ))

        code_summary_lines = [
            "Generated Code Summary:",
            f"Total rules with generated code: {len(code_cache)}",
            f"Rules with code: {', '.join(code_cache.keys())}",
        ]
        for rule_name, cached in code_cache.items():
            rn = rule_index_map.get(rule_name, "?")
            code_summary_lines.append(
                f"  Rule #{rn} - {rule_name}: "
                f"check_type={cached.get('check_type','')}, "
                f"id_column={cached.get('id_column','')}"
            )
        docs.append(Document(
            page_content="\n".join(code_summary_lines),
            metadata={"type": "generated_code_summary"}
        ))

    return docs


# ─────────────────────────────────────────────────────────────────────────────
# RAG SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
class DQRagSystem:

    def __init__(self):
        http_client = httpx.Client(verify=False)

        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

        self.llm = AzureChatOpenAI(
            azure_endpoint   = AZURE_OPENAI_ENDPOINT,
            api_key          = AZURE_OPENAI_API_KEY,
            api_version      = AZURE_OPENAI_API_VERSION,
            azure_deployment = AZURE_OPENAI_DEPLOYMENT,
            temperature      = 0,
            http_client      = http_client,
        )

        self.vector_store = None
        self._split_docs  = []
        self.all_docs     = []
        self.session_id   = None
        self._build_intent_classifier()
        self._answer_chain = None

    # ── Intent classifier ─────────────────────────────────────────────────────

    def _build_intent_classifier(self):
        intent_descriptions = "\n".join([
            f'- "{key}": {cfg["description"]}\n'
            f'  Examples: {", ".join(cfg["examples"][:2])}'
            for key, cfg in INTENT_CONFIG.items()
        ])
        self._intent_system = f"""You are a query intent classifier for a Data Quality Engine.

Classify the user's question into EXACTLY ONE of these intents:

{intent_descriptions}

Return ONLY the intent key as a single word — no explanation, no punctuation.
Valid responses: {', '.join(INTENT_CONFIG.keys())}"""

    def classify_intent(self, question: str, chat_history: list = None) -> str:
        history_context = ""
        if chat_history:
            recent = chat_history[-4:]
            history_context = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:150]}"
                for m in recent
            ])

        messages = [
            SystemMessage(content=self._intent_system),
            HumanMessage(content=f"Question: {question}{history_context}"),
        ]

        try:
            response = self.llm.invoke(messages)
            intent   = response.content.strip().lower().replace('"','').replace("'","")
            if intent not in INTENT_CONFIG:
                print(f"⚠️ Unknown intent '{intent}', falling back to general")
                intent = "general"
            print(f"🎯 Intent: '{question[:60]}' → {intent}")
            return intent
        except Exception as e:
            print(f"⚠️ Intent classification failed: {e}, using general")
            return "general"

    # ── Index building ────────────────────────────────────────────────────────

    def build_index(self, session: dict, session_id: str) -> int:
        print(f"🔍 Building RAG index for session {session_id}...")

        docs = build_documents_from_session(session)
        self.all_docs   = docs
        self.session_id = session_id

        no_split_types = {
            "generated_code",
            "entity_mappings_summary",
            "entity_mappings_hop1",
            "entity_mappings_hop2",
            "generated_code_summary",
            "target_schema",
            "dataset_columns",
            "dataset_col_types",
            "remediation_summary",
        }

        text_docs      = [d for d in docs if d.metadata.get("type") not in no_split_types]
        no_split_docs  = [d for d in docs if d.metadata.get("type") in no_split_types]

        text_splitter   = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
        split_text_docs = text_splitter.split_documents(text_docs)

        code_docs      = [d for d in no_split_docs if d.metadata.get("type") == "generated_code"]
        other_no_split = [d for d in no_split_docs if d.metadata.get("type") != "generated_code"]

        code_splitter   = RecursiveCharacterTextSplitter(
            chunk_size=4000, chunk_overlap=0,
            separators=["\ndef ", "\nclass ", "\n\n", "\n"],
        )
        split_code_docs = code_splitter.split_documents(code_docs)

        split_docs = split_text_docs + split_code_docs + other_no_split

        print(f"📄 Indexing {len(split_docs)} chunks from {len(docs)} documents...")
        self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
        self._split_docs  = split_docs
        self._build_answer_chain()
        print(f"✅ RAG index ready — {len(split_docs)} chunks indexed")
        return len(split_docs)

    def update_index(self, session: dict):
        if self.session_id:
            self.build_index(session, self.session_id)

    # ── Hybrid retriever ──────────────────────────────────────────────────────

    def _get_filtered_retriever(self, intent: str):
        doc_types = INTENT_CONFIG[intent]["doc_types"]

        if intent == "mapping_query":
            k = 20
        elif intent in ("code_query",):
            k = 8
        elif intent == "schema_query":
            k = 10
        elif intent == "remediation_query":
            k = 6
        else:
            k = 6

        if doc_types is not None:
            filtered = [
                d for d in self._split_docs
                if d.metadata.get("type") in doc_types
            ]
            if not filtered:
                filtered = self._split_docs
        else:
            filtered = self._split_docs

        bm25   = BM25Retriever.from_documents(filtered)
        bm25.k = k

        if doc_types is not None and len(filtered) < len(self._split_docs):
            try:
                faiss_filtered = FAISS.from_documents(filtered, self.embeddings)
                semantic = faiss_filtered.as_retriever(
                    search_type="similarity",
                    search_kwargs={"k": k},
                )
            except Exception:
                semantic = self.vector_store.as_retriever(
                    search_kwargs={"k": k}
                )
        else:
            semantic = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": k},
            )

        return EnsembleRetriever(
            retrievers=[bm25, semantic],
            weights=[0.5, 0.5],
        )

    def _rerank(self, query: str, docs: List[Document],
                top_n: int = 5) -> List[Document]:
        """No cross-encoder — return top_n by retrieval order."""
        return docs[:top_n]

    # ── Direct metadata lookup ────────────────────────────────────────────────

    def _direct_lookup(self, intent: str, search_question: str,
                       session_rules: list) -> Optional[List[Document]]:
        q           = search_question.lower()
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        name_to_idx = {v.lower(): k for k, v in idx_to_name.items()}

        rule_num = None
        match = re.search(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b', q, re.IGNORECASE
        )
        if match:
            rule_num = int(match.group(1))
        else:
            for name, idx in name_to_idx.items():
                if name and name in q:
                    rule_num = idx
                    break

        if rule_num is None:
            return None

        target_type = {
            "code_query":        "generated_code",
            "mapping_query":     "entity_mappings",
            "rule_query":        "rule",
            "execution_query":   "execution_results",
            "remediation_query": "remediation_results",
        }.get(intent)

        if target_type is None:
            return None

        matched = [
            d for d in self.all_docs
            if d.metadata.get("type") == target_type
            and d.metadata.get("rule_number") == rule_num
        ]

        if matched:
            print(f"🎯 Direct lookup: rule {rule_num} / {target_type} "
                  f"→ {len(matched)} docs")
            return matched
        return None

    # ── Follow-up detection ───────────────────────────────────────────────────

    def _is_followup_query(self, question: str, chat_history: list) -> bool:
        if not chat_history:
            return False

        q = question.lower().strip()

        code_request_signals = [
            "give code", "show code", "display code",
            "give me code", "show me code", "pyspark code for",
            "generate code for",
        ]
        if any(sig in q for sig in code_request_signals):
            print(f"💻 Code request — standalone: '{question}'")
            return False

        followup_signals = [
            q.startswith("it "), q.startswith("its "),
            q.startswith("that "), q.startswith("this "),
            q.startswith("they "), q.startswith("these "),
            q.startswith("those "), q.startswith("and "),
            q.startswith("but "), q.startswith("so "),
            q.startswith("also "), q.startswith("then "),
            q.startswith("what about "), q.startswith("how about "),
            q.startswith("what if "),
            "the same" in q,
            len(q.split()) <= 4 and bool(chat_history),
            q in ("why?", "how?", "when?", "who?", "which?",
                  "explain.", "elaborate.", "more?"),
            "explain in" in q, "tell me more" in q,
            "give me more" in q, "what does that mean" in q,
            "can you elaborate" in q, "simplify" in q, "in simple" in q,
        ]

        if any(followup_signals):
            print(f"🔗 Follow-up (rule-based): '{question}'")
            return True

        if 4 < len(q.split()) <= 15 and chat_history:
            return self._llm_classify_followup(question, chat_history)
        return False

    def _llm_classify_followup(self, question: str, chat_history: list) -> bool:
        recent = chat_history[-4:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
        ])
        prompt = f"""Conversation so far:
{history_str}

New question: "{question}"

Is this a follow-up or a new independent question?
Answer with exactly one word: yes or no"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            answer   = response.content.strip().lower().replace(".", "")
            is_fu    = answer.startswith("yes")
            print(f"🤖 Follow-up check: '{question}' → {answer}")
            return is_fu
        except Exception as e:
            print(f"⚠️ Follow-up check failed: {e}")
            return False

    def _rewrite_query(self, question: str, chat_history: list) -> str:
        recent = chat_history[-6:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:300]}" for m in recent
        ])
        prompt = f"""Rewrite this follow-up into a complete standalone question.

Conversation:
{history_str}

Follow-up: "{question}"

Rewritten (return ONLY the question):"""

        try:
            response  = self.llm.invoke([HumanMessage(content=prompt)])
            rewritten = response.content.strip().strip('"').strip("'")
            if rewritten and rewritten != question:
                print(f"✏️  Rewritten: '{question}' → '{rewritten}'")
                return rewritten
            return question
        except Exception as e:
            print(f"⚠️ Rewrite failed: {e}")
            return question

    def _resolve_rule_references(self, question: str,
                                  session_rules: list) -> str:
        ordinals = {
            "first": 1, "second": 2, "third": 3, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10,
        }
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        resolved    = question

        def replace_numbered(match):
            num  = int(match.group(1))
            name = idx_to_name.get(num, "")
            return f"rule {num} ({name})" if name else match.group(0)

        resolved = re.sub(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b',
            replace_numbered, resolved, flags=re.IGNORECASE
        )

        def replace_ordinal(match):
            word = match.group(1).lower()
            num  = ordinals.get(word)
            if num:
                name = idx_to_name.get(num, "")
                if name:
                    return f"rule {num} ({name})"
            return match.group(0)

        resolved = re.sub(
            r'\b(' + '|'.join(ordinals.keys()) + r')\s+rule\b',
            replace_ordinal, resolved, flags=re.IGNORECASE
        )

        if resolved != question:
            print(f"🔄 Resolved: '{question}' → '{resolved}'")
        return resolved

    # ── Compute pipeline ──────────────────────────────────────────────────────

    def _generate_compute_code(self, question: str,
                                snapshot: dict,
                                chat_history: list = None) -> str:
        history_ctx = ""
        if chat_history:
            recent = chat_history[-4:]
            history_ctx = "\nRecent conversation:\n" + "\n".join(
                f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
            )

        schema_preview = {
            "rules":               f"{len(snapshot['rules'])} rules",
            "run_log":             f"{len(snapshot['run_log'])} executed",
            "rule_metrics":        f"{len(snapshot['rule_metrics'])} entries",
            "remediation_summary": snapshot.get("remediation_summary", {}),
            "schema":              snapshot["schema"],
            "total_rules":         snapshot["total_rules"],
            "executed_count":      snapshot["executed_count"],
            "code_generated_for":  snapshot["code_generated_for"],
        }

        system_prompt = f"""You are a Python code generator for a Data Quality Engine.

Write a function `compute(data)` that answers the user's question.

`data` structure:
{json.dumps(schema_preview, indent=2, default=str)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY DATA PATHS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCHEMA — target_schema is ALWAYS complete (all columns, untruncated):
  data['schema']['target_schema']
    → list of dicts: [{{"name","type","category"[,"table"]}}]

DATASET COL INFERRED TYPES (via schema mapping):
  data['schema']['dataset_col_type_map']
    → {{dataset_col: {{"type","category","schema_col"}}}}
    → Use when user asks data type of a DATASET column (e.g. "acct_number")
    → If col not in map: it hasn't been mapped to a schema col yet

MULTI-TABLE:
  data['schema']['schema_info']     → {{table: {{col: {{data_type, category}}}}}}
  data['schema']['type_counts']     → {{dtype: count}}
  data['schema']['category_counts'] → {{category: count}}
  data['schema']['tables']          → {{table: {{columns, column_count, row_count}}}}
  data['schema']['entity_mappings_hop1'] → {{entity: schema_col}}
  data['schema']['entity_mappings_hop2'] → {{schema_col: dataset_col}}

SINGLE-TABLE:
  data['schema']['schema_columns_to_type']     → {{col: dtype}}
  data['schema']['schema_columns_to_category'] → {{col: category}}
  data['schema']['type_counts']                → {{dtype: count}}
  data['schema']['category_counts']            → {{category: count}}

EXECUTION:
  data['run_log']       → [{{rule_name, passed_count, failed_count, pass_rate, timestamp}}]
  data['rule_metrics']  → {{rule_name: pass_rate}}
  data['code_generated_for'] → [rule_name, ...]

REMEDIATION:
  data['remediation_summary']['total_actions']    → int
  data['remediation_summary']['total_rows_fixed'] → int
  data['remediation_summary']['actions']          → list of dicts:
    each: {{index, rule_name, logic, rows_affected, failed_ids_count, timestamp}}
  data['remediation_log']                         → raw list (same entries)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"tell me data types of all schema columns":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    if not cols:
        return "No schema loaded"
    return {{col.get('name'): col.get('type','unknown') for col in cols}}

"give columns whose data type is string":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('type','').lower() == 'string']

"give columns in the financial category":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('category','').lower() == 'financial']

"what is the data type of acct_number":
def compute(data):
    # Check dataset col type map first (inferred via mapping)
    m    = data['schema'].get('dataset_col_type_map', {{}})
    info = m.get('acct_number')
    if info:
        return (f"acct_number → inferred type '{{info['type']}}' "
                f"via schema column '{{info['schema_col']}}'")
    # Fallback: check if it matches a schema col directly
    cols = data['schema'].get('target_schema', [])
    for c in cols:
        if c.get('name','').lower() == 'acct_number':
            return f"acct_number is a schema column with type '{{c.get('type')}}'"
    return ("acct_number has not been mapped to a schema column yet. "
            "Run /get_mappings first.")

"how many rows were remediated":
def compute(data):
    return data.get('remediation_summary', {{}}).get('total_rows_fixed', 0)

"show remediation history":
def compute(data):
    actions = data.get('remediation_summary', {{}}).get('actions', [])
    if not actions:
        return "No remediations applied yet"
    return actions

"what logic was used in remediation 1":
def compute(data):
    actions = data.get('remediation_summary', {{}}).get('actions', [])
    if not actions:
        return "No remediations applied yet"
    return actions[0].get('logic', 'Not found')

"which dataset columns have inferred types":
def compute(data):
    m = data['schema'].get('dataset_col_type_map', {{}})
    if not m:
        return "No mappings yet — run /get_mappings first"
    return {{dc: info['type'] for dc, info in m.items()}}

"list all schema columns grouped by category":
def compute(data):
    cols   = data['schema'].get('target_schema', [])
    result = {{}}
    for c in cols:
        cat = c.get('category', 'unknown')
        result.setdefault(cat, []).append(c.get('name'))
    return result

"what are the schema columns in the Orders table":
def compute(data):
    # Get the table name from context — LLM fills this in from the question
    table_name = 'Orders'
    schema_cols = data['schema'].get('target_schema', [])
    
    # Try matching by table field first
    by_table = [
        c for c in schema_cols
        if (c.get('table') or c.get('table_name') or '') == table_name
    ]
    
    # If no table field in schema, try schema_info
    if not by_table:
        schema_info = data['schema'].get('schema_info', {{}})
        table_info  = schema_info.get(table_name, {{}})
        return [
            {{'name': col, 'type': info.get('data_type','unknown'),
             'category': info.get('category','')}}
            for col, info in table_info.items()
        ] or f"No schema columns found for table '{{table_name}}'"
    
    return [
       {{'name': c.get('name'), 'type': c.get('type'), 'category': c.get('category')}}
        for c in by_table
    ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Function named `compute(data)` only
2. Return: string, list, dict, int, or float — no DataFrames
3. Handle missing keys and empty lists gracefully
4. NO import statements — pre-injected globals available:
   datetime, date, timedelta, math, re, json, Counter, defaultdict, dateutil_parser
5. Return ONLY the function — no markdown, no backticks

{history_ctx}"""

        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Question: {question}"),
        ])

        code = response.content.strip()
        code = code.replace("```python", "").replace("```", "").strip()
        return code

    def _execute_compute_code(self, code: str, snapshot: dict) -> tuple:
        import math
        import re as re_module
        import json as json_module
        from datetime import datetime, date, timedelta
        from collections import Counter, defaultdict

        try:
            from dateutil import parser as dateutil_parser
        except ImportError:
            dateutil_parser = None

        allowed_globals = {
            "__builtins__": {
                "len": len, "range": range, "enumerate": enumerate,
                "zip": zip, "map": map, "filter": filter,
                "sorted": sorted, "reversed": reversed,
                "min": min, "max": max, "sum": sum, "abs": abs,
                "round": round, "int": int, "float": float,
                "str": str, "bool": bool, "list": list,
                "dict": dict, "set": set, "tuple": tuple,
                "isinstance": isinstance, "any": any, "all": all,
                "print": print, "type": type,
                "hasattr": hasattr, "getattr": getattr,
                "None": None, "True": True, "False": False,
            },
            "datetime": datetime, "date": date, "timedelta": timedelta,
            "math": math, "json": json_module, "re": re_module,
            "Counter": Counter, "defaultdict": defaultdict,
            "dateutil_parser": dateutil_parser,
        }

        local_vars = {}
        try:
            exec(code, allowed_globals, local_vars)
            compute_fn = local_vars.get("compute")
            if compute_fn is None:
                return None, "Generated code did not define a `compute` function"
            result = compute_fn(snapshot)
            return result, None
        except Exception as e:
            return None, f"Execution error: {str(e)}\n\nCode:\n{code}"

    def _compute_to_answer(self, question: str, result,
                            code: str, error: str = None) -> str:
        if error:
            return (
                f"I understood your question but had trouble computing the answer. "
                f"Error: {error}"
            )

        prompt = f"""The user asked: "{question}"

Python function returned:
{json.dumps(result, indent=2, default=str)}

Write a clear, concise natural-language answer.
- Include actual values (names, types, numbers) from the result
- Use bullet points if result is a list/dict with more than 3 items
- Do not mention Python, functions, or the technical process
- Keep under 400 words (longer if listing many columns)
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _run_compute_pipeline(self, question: str,
                               session: dict,
                               chat_history: list = None) -> dict:
        snapshot = build_structured_snapshot(session)
        print(f"🧮 Compute: '{question[:60]}'")

        code = self._generate_compute_code(question, snapshot, chat_history)
        print(f"📝 Code:\n{code}\n")

        result, error = self._execute_compute_code(code, snapshot)
        print(f"⚙️  Result: {str(result)[:100]}, error: {error}")

        if error and "Execution error" in error:
            print("🔄 Retrying...")
            retry_code = self._generate_compute_code(
                f"{question}\n\nPrevious attempt failed: {error}",
                snapshot, chat_history
            )
            result, error = self._execute_compute_code(retry_code, snapshot)
            code = retry_code

        answer = self._compute_to_answer(question, result, code, error)

        return {
            "answer":       answer,
            "intent":       "compute",
            "compute_code": code,
            "raw_result":   result,
            "sources":      [{"type": "structured_compute",
                              "snippet": str(result)[:100]}],
        }

    # ── Answer chain ──────────────────────────────────────────────────────────

    def _build_answer_chain(self):
        self._answer_prompt = ChatPromptTemplate.from_template("""
You are a Data Quality Engine assistant. Answer ONLY from the context below.

IMPORTANT DISTINCTIONS:
- "DATASET COLUMNS" = raw column names from the uploaded file. No explicit type info.
- "TARGET SCHEMA COLUMNS" = columns from the schema JSON with explicit data type and category.
- "INFERRED DATASET COLUMN TYPES" = types inferred by matching dataset cols to schema cols via mappings.
- If user asks data type of a dataset column, look under "DATASET COLUMNS WITH INFERRED DATA TYPES".
- If not found there, say the column hasn't been mapped to a schema column yet.
- "REMEDIATION" = actions taken to fix failed records after rule execution.

If the answer is not in the context:
"I don't have that information in the current session."

Rules:
- CODE: return COMPLETE code, never truncate
- Rules: numbered lists (#1, #2 etc.)
- Columns: bullet points
- Keep under 300 words unless listing many items requires more

Context:
{context}

Question: {question}

Answer:""")

    @staticmethod
    def _format_docs(docs: List[Document]) -> str:
        if not docs:
            return "No relevant documents found."
        return "\n\n---\n\n".join(d.page_content for d in docs)

    # ── Main query method ─────────────────────────────────────────────────────

    def query(self, question: str, chat_history: list = None,
              session: dict = None) -> dict:
        if self.vector_store is None:
            return {
                "answer":  "RAG index not built yet. Please upload your dataset first.",
                "intent":  "unknown",
                "sources": [],
            }

        effective_question = question

        if chat_history:
            if self._is_followup_query(question, chat_history):
                effective_question = self._rewrite_query(question, chat_history)
            else:
                print(f"🆕 Standalone: '{question}'")
        else:
            print("No chat history")

        intent     = self.classify_intent(effective_question, chat_history)
        is_compute = INTENT_CONFIG.get(intent, {}).get("compute", False)

        if is_compute:
            if session is None:
                return {
                    "answer":  "Session data is required for this query.",
                    "intent":  intent,
                    "sources": [],
                }
            return self._run_compute_pipeline(
                effective_question, session, chat_history
            )

        doc_types     = INTENT_CONFIG[intent]["doc_types"]
        search_question = effective_question
        session_rules   = []

        if session is not None:
            rules_df = session.get("rules_df")
            if rules_df is not None:
                session_rules   = rules_df.to_dict(orient="records")
                search_question = self._resolve_rule_references(
                    effective_question, session_rules
                )

        # Direct lookup first
        direct_docs = self._direct_lookup(intent, search_question, session_rules)

        if direct_docs:
            retrieved_docs = direct_docs
            print(f"⚡ Direct lookup: {len(retrieved_docs)} docs")
        else:
            retriever = self._get_filtered_retriever(intent)
            try:
                retrieved_docs = retriever.invoke(search_question)
            except Exception as e:
                print(f"⚠️ Retrieval failed ({e}), falling back")
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            if not retrieved_docs:
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            retrieved_docs = self._rerank(search_question, retrieved_docs, top_n=5)

        # code_query guard
        if intent == "code_query":
            summary_in = any(
                d.metadata.get("type") == "generated_code_summary"
                for d in retrieved_docs
            )
            if not summary_in:
                for doc in self.all_docs:
                    if doc.metadata.get("type") == "generated_code_summary":
                        retrieved_docs = [doc] + list(retrieved_docs)
                        break

            summary_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code_summary"
            ]
            no_code = any(
                "no pyspark code has been generated yet" in d.page_content.lower()
                for d in summary_docs
            )

            if no_code:
                return {
                    "answer": (
                        "No code has been generated yet. "
                        "Please generate code for the rule first."
                    ),
                    "intent":    intent,
                    "doc_types": doc_types,
                    "sources":   [],
                }

            code_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code"
            ]
            if code_docs:
                retrieved_docs = code_docs + summary_docs

        context = self._format_docs(retrieved_docs)

        history_text = ""
        if chat_history:
            recent = chat_history[-4:]
            history_text = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:200]}"
                for m in recent
            ])

        full_prompt = self._answer_prompt.format_messages(
            context  = context + history_text,
            question = question,
        )

        try:
            answer = self.llm.invoke(full_prompt).content
        except Exception as e:
            answer = f"Failed to generate answer: {str(e)}"

        sources = []
        seen    = set()
        for doc in retrieved_docs:
            key = (doc.metadata.get("rule_name") or
                   doc.metadata.get("table") or
                   doc.metadata.get("type"))
            if key and key not in seen:
                seen.add(key)
                sources.append({
                    "type":        doc.metadata.get("type"),
                    "rule_name":   doc.metadata.get("rule_name"),
                    "rule_number": doc.metadata.get("rule_number"),
                    "table":       doc.metadata.get("table"),
                    "snippet":     doc.page_content[:100] + "…",
                })

        print(f"✅ Answered — intent={intent}, "
              f"sources={[s['type'] for s in sources]}")

        return {
            "answer":          answer,
            "intent":          intent,
            "doc_types":       doc_types,
            "sources":         sources,
            "rewritten_query": (
                effective_question if effective_question != question else None
            ),
        }

    def is_ready(self) -> bool:
        return self.vector_store is not None


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped RAG store
# ─────────────────────────────────────────────────────────────────────────────
RAG_STORE: dict = {}

def get_or_create_rag(session_id: str) -> DQRagSystem:
    if session_id not in RAG_STORE:
        RAG_STORE[session_id] = DQRagSystem()
    return RAG_STORE[session_id]
'''
'''
import os
import sys
import re
import ssl

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable
os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

os.environ['HF_HUB_DISABLE_XET'] = '1'

ssl._create_default_https_context = ssl._create_unverified_context

import requests
requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)
_orig_send = requests.Session.send
def _patched_send(self, request, **kwargs):
    kwargs['verify'] = False
    return _orig_send(self, request, **kwargs)
requests.Session.send = _patched_send

import json
import time
from typing import List, Optional
from dotenv import load_dotenv
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
import httpx

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_table_field(col_def: dict) -> str:
    return col_def.get("table_name")


def _build_dataset_col_type_map(session: dict) -> dict:
    """
    Build: dataset_column → {type, category, schema_col}

    NEW mapping model:
      mapped_dict       = entity → schema_col        (was entity → dataset_col)
      schema_to_dataset = schema_col → dataset_col   (was hop2_mapping)

    Paths:
      Path A: schema_to_dataset reversed (schema_col → dataset_col)
      Path B: mapped_dict (entity → schema_col) + schema_to_dataset composition
      Path C: name-match fallback for single-hop (no target schema)
    """
    target_schema     = session.get("target_schema", [])
    schema_to_dataset = session.get("schema_to_dataset", {})  # schema_col → dataset_col
    mapped_dict       = session.get("mapped_dict", {})         # entity → schema_col

    # Build schema_col → {type, category} lookup
    schema_type_map: dict = {}
    for col in target_schema:
        name = col.get("name", "")
        if name:
            schema_type_map[name] = {
                "type":     col.get("type", "unknown"),
                "category": col.get("category", ""),
            }

    result: dict = {}

    # Path A: reverse schema_to_dataset to get dataset_col → schema_col
    for schema_col, dataset_col in schema_to_dataset.items():
        if dataset_col and schema_col in schema_type_map and dataset_col != schema_col:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path B: entity → schema_col (mapped_dict) → dataset_col (schema_to_dataset)
    for entity, schema_col in mapped_dict.items():
        dataset_col = schema_to_dataset.get(schema_col)
        if dataset_col and schema_col in schema_type_map and dataset_col not in result:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path C: single-hop fallback — schema_col == dataset_col (identity mapping)
    # In this case mapped_dict values ARE schema col names; check name match
    if schema_type_map:
        schema_names_lower = {
            name.lower().replace("_", " "): name
            for name in schema_type_map
        }
        for entity, schema_col in mapped_dict.items():
            if schema_col and schema_col not in result:
                if schema_col in schema_type_map:
                    info = schema_type_map[schema_col]
                    result[schema_col] = {
                        "type":       info["type"],
                        "category":   info["category"],
                        "schema_col": schema_col,
                    }
                else:
                    normalised = schema_col.lower().replace("_", " ")
                    matched = schema_names_lower.get(normalised)
                    if matched:
                        info = schema_type_map[matched]
                        result[schema_col] = {
                            "type":       info["type"],
                            "category":   info["category"],
                            "schema_col": matched,
                        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# INTENT DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────
INTENT_CONFIG = {
    "temporal_query": {
        "description": (
            "Questions involving time, timestamps, dates — "
            "e.g. 'rules executed before 3 PM', 'latest run', "
            "'what ran today', 'execution order'"
        ),
        "examples": [
            "which rules ran before 3pm",
            "what was the last rule executed",
            "show rules executed after 2 Jan 2025",
            "which rule ran most recently",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "mathematical_query": {
        "description": (
            "Questions requiring calculation, aggregation, comparison, ranking, "
            "OR counting — including counting rows in the dataset/tables, "
            "counting columns, how many records, total rows, row counts per table, "
            "average pass rate, rule with most failures, total failed records, "
            "difference between pass rates."
        ),
        "examples": [
            "how many rows does the dataset have",
            "how many records are in the Territory table",
            "how many columns have type int",
            "count columns with type string",
            "total number of rows across all tables",
            "what is the average pass rate across all rules",
            "which rule has the most failed records",
            "rank rules by pass rate",
            "how many more records failed in rule 2 vs rule 3",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "filter_query": {
        "description": (
            "Questions that filter or search for rules/columns matching a condition — "
            "e.g. 'rules with pass rate below 80%', "
            "'rules in the financial category that failed'"
        ),
        "examples": [
            "rules with pass rate below 80 percent",
            "which rules failed more than 100 records",
            "show rules that belong to financial category and failed",
            "rules with complexity high that were executed",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "schema_data_query": {
        "description": (
            "Questions asking to LIST, SHOW, or TELL data types, categories, "
            "or properties of schema columns OR dataset columns (via mapping). "
            "Examples: 'tell me data types of all schema columns', "
            "'list all schema columns with their types', "
            "'what type is column X', "
            "'which columns are of type string', "
            "'what is the data type of <dataset_column>', "
            "'show dataset columns whose data type is string', "
            "'give columns whose data type is float', "
            "Also includes: 'what schema columns are in X table', "
            "'list schema columns for Orders table', "
            "'show me the schema of the Orders table', "
            "'what are the target schema columns in Products'. "
            "'what data type does acct_number map to'. "
            "Use for ANY question enumerating or describing column types/categories."
        ),
        "examples": [
            "tell me the data types of all schema columns",
            "list all schema columns with their types",
            "give columns whose data type is string",
            "what type is order_id",
            "show all target schema columns",
            "which columns belong to the financial category",
            "give dataset columns whose data type is string",
            "what schema columns are in the Orders table",
            "list schema columns for the Products table",
            "show schema columns in Orders",
            "what are the target schema columns in Customers",
            "what is the data type of acct_number",
            "what data type does closing_balance map to",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "schema_query": {
        "description": (
            "Questions about dataset structure, table names, which tables exist, "
            "general schema overview, which columns are in a table. "
            "NOT for listing data types — use schema_data_query for that."
        ),
        "examples": [
            "what columns does the dataset have",
            "which tables are there",
            "what fields does Territory table have",
            "show me the schema of the Orders table",
            "what is the structure of the dataset",
        ],
        "doc_types": [
            "dataset_overview", "target_schema",
            "table_schema", "column_list", "dataset_columns",
        ],
    },
    "rule_query": {
        "description": "Questions about specific rules, business logic, what a rule validates",
        "examples": [
            "what does rule 3 do", "which rules check for null",
            "what is the business rule for", "how many rules",
            "what category is rule", "list all rules",
        ],
        "doc_types": ["rule", "rules_summary"],
    },
    "mapping_query": {
        "description": (
            "Questions about entity-to-column mappings for any or all rules, "
            "which column an entity maps to, mappings for all rules, "
            "entity-to-target_column mappings, "
            "target_column-to-source_column mappings, "
            "show all mappings, what are the mappings"
        ),
        "examples": [
            "what column does account number map to",
            "show mappings for all rules",
            "what are the mappings for every rule",
            "What column in the schema is mapped to account number",
            "which entity maps to Territory_ID",
            "what are the mappings for rule 2",
        ],
        "doc_types": [
            "entity_mappings", "entity_mappings_summary",
            "entity_mappings_hop1", "entity_mappings_hop2", "rule",
        ],
    },
    "execution_query": {
        "description": (
            "Questions about execution results, pass rates, failed records, "
            "which rules passed or failed"
        ),
        "examples": [
            "which rules failed", "what is the pass rate",
            "how many records failed", "show me execution results",
            "which rule has the worst pass rate",
        ],
        "doc_types": ["execution_results", "rules_summary"],
    },
    "remediation_query": {
        "description": (
            "Questions about data remediation actions, remediation history, "
            "what remediations were applied, how many rows were fixed, "
            "remediation logic used, audit log of remediations"
        ),
        "examples": [
            "what remediations have been applied",
            "how many rows were fixed",
            "show me the remediation history",
            "what logic was used to fix the data",
            "how many records were remediated",
            "show remediation audit log",
        ],
        "doc_types": ["remediation_results", "remediation_summary"],
        "compute":   False,
    },
    "rule_and_schema": {
        "description": (
            "Questions that need both rule information and "
            "schema/column information together"
        ),
        "examples": [
            "which columns does rule 3 use",
            "what fields are validated by",
            "which table does rule 2 apply to",
        ],
        "doc_types": [
            "rule", "rules_summary", "table_schema", "dataset_overview",
            "target_schema", "entity_mappings", "entity_mappings_hop1",
        ],
    },
    "code_query": {
        "description": (
            "Questions about generated PySpark code, requests to show or give "
            "code for a rule, what code was generated, check types used. "
            "Includes: 'give code for rule 1', 'show code for rule 3', "
            "'display the pyspark code', 'was code generated for all rules', "
            "'what rules have code'"
        ),
        "examples": [
            "what code was generated for rule 3",
            "show me the pyspark code for",
            "give code for rule 1",
            "display code for rule 2",
            "what check type does rule 2 use",
            "which id column is used in the code",
            "was code generated for all rules",
            "what rules have code generated",
        ],
        "doc_types": ["generated_code", "generated_code_summary"],
    },
    "general": {
        "description": "General questions or unclear intent — search everything",
        "examples":    ["tell me about the data", "give me a summary"],
        "doc_types":   None,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def build_structured_snapshot(session: dict) -> dict:
    rules_df   = session.get("rules_df")
    rules_list = rules_df.to_dict(orient="records") if rules_df is not None else []

    rule_metrics  = session.get("rule_metrics", {})
    code_cache    = session.get("code_cache", {})
    target_schema = session.get("target_schema", [])

    run_log = []
    for i, rule in enumerate(rules_list):
        name = rule.get("name", "")
        if name in rule_metrics:
            result = session["result"][name]
            run_log.append({
                "rule_index":   i + 1,
                "rule_name":    name,
                "category":     rule.get("category", ""),
                "complexity":   rule.get("complexity", ""),
                "passed_count": result.get("passed_count", 0),
                "failed_count": result.get("failed_count", 0),
                "pass_rate":    result.get("pass_rate", 0.0),
                "timestamp":    session["timestamp"][name],
                "has_code":     name in code_cache,
                "check_type":   code_cache.get(name, {}).get("check_type", ""),
            })

    remediation_log  = session.get("remediation_log", [])
    total_rows_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
    remediation_summary = {
        "total_actions":    len(remediation_log),
        "total_rows_fixed": total_rows_fixed,
        "actions": [
            {
                "index":            i + 1,
                "rule_name":        e.get("rule_name", ""),
                "logic":            e.get("logic", ""),
                "rows_affected":    e.get("rows_affected", 0),
                "failed_ids_count": len(e.get("failed_ids", [])),
                "timestamp":        e.get("timestamp", ""),
            }
            for i, e in enumerate(remediation_log)
        ],
    }

    dataset_col_type_map = _build_dataset_col_type_map(session)

    # NEW: mapped_dict = entity → schema_col; schema_to_dataset = schema_col → dataset_col
    mapped_dict       = session.get("mapped_dict", {})        # entity → schema_col
    schema_to_dataset = session.get("schema_to_dataset", {})  # schema_col → dataset_col

    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})
        dfs         = session.get("dfs", {})
        tables_info = {}

        for table_name, meta in tables_meta.items():
            cols      = meta.get("columns", [])
            spark_df  = dfs.get(table_name)
            row_count = None
            if spark_df is not None:
                try:
                    row_count = spark_df.count()
                except Exception as e:
                    print(f"⚠️ Could not count rows for {table_name}: {e}")
            tables_info[table_name] = {
                "columns":      cols,
                "column_count": len(cols),
                "row_count":    row_count,
            }

        total_rows = sum(
            v["row_count"] for v in tables_info.values()
            if v["row_count"] is not None
        )

        schema_info: dict = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            table    = _get_table_field(col)
            name     = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            if table and name:
                schema_info.setdefault(table, {})[name] = {
                    "data_type": dtype,
                    "category":  category,
                }
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        schema = {
            "type":                         "multi_table",
            "tables":                       tables_info,
            "total_columns":                sum(len(m.get("columns", [])) for m in tables_meta.values()),
            "table_names":                  list(tables_meta.keys()),
            "total_rows_across_all_tables": total_rows,
            "target_schema":                target_schema,
            "schema_info":                  schema_info,
            "type_counts":                  type_counts,
            "category_counts":              cat_counts,
            # NEW: entity → schema_col and schema_col → dataset_col
            "entity_to_schema_col":         mapped_dict,
            "schema_col_to_dataset_col":    schema_to_dataset,
            "dataset_col_type_map":         dataset_col_type_map,
        }

    else:
        columns  = session.get("columns", [])
        spark_df = session.get("df")

        schema_columns    = []
        name_to_type      = {}
        name_to_category  = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            col_name = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            schema_columns.append(col_name)
            name_to_type[col_name]     = dtype
            name_to_category[col_name] = category
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        row_count = None
        if spark_df is not None:
            try:
                row_count = spark_df.count()
            except Exception as e:
                print(f"⚠️ Could not count rows: {e}")

        schema = {
            "type":                       "single_table",
            "columns":                    columns,
            "column_count":               len(columns),
            "row_count":                  row_count,
            "target_schema":              target_schema,
            "schema_columns":             schema_columns,
            "schema_columns_count":       len(schema_columns),
            "schema_columns_to_type":     name_to_type,
            "schema_columns_to_category": name_to_category,
            "type_counts":                type_counts,
            "category_counts":            cat_counts,
            # NEW: entity → schema_col and schema_col → dataset_col
            "entity_to_schema_col":       mapped_dict,
            "schema_col_to_dataset_col":  schema_to_dataset,
            "dataset_col_type_map":       dataset_col_type_map,
        }

    return {
        "rules":               rules_list,
        "run_log":             run_log,
        "rule_metrics":        rule_metrics,
        "remediation_summary": remediation_summary,
        "schema":              schema,
        "total_rules":         len(rules_list),
        "executed_count":      len(run_log),
        "code_generated_for":  list(code_cache.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_documents_from_session(session: dict) -> List[Document]:
    docs              = []
    target_schema     = session.get("target_schema", [])
    # NEW mapping model
    mapped_dict       = session.get("mapped_dict", {})        # entity → schema_col
    schema_to_dataset = session.get("schema_to_dataset", {})  # schema_col → dataset_col

    dataset_col_type_map = _build_dataset_col_type_map(session)

    # ── Dataset schema ────────────────────────────────────────────────────────
    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})

        schema_lookup: dict = {}
        for col_def in target_schema:
            tbl  = _get_table_field(col_def)
            name = col_def.get("name", "")
            if tbl and name:
                schema_lookup.setdefault(tbl, {})[name] = {
                    "type":     col_def.get("type", "string"),
                    "category": col_def.get("category", ""),
                }

        for table_name, meta in tables_meta.items():
            columns    = meta.get("columns", [])
            tbl_schema = schema_lookup.get(table_name, {})

            raw_col_lines    = [f"  - {col}" for col in columns]
            schema_col_lines = []
            for col in columns:
                info  = tbl_schema.get(col, {})
                dtype = info.get("type")
                cat   = info.get("category", "")
                if dtype:
                    schema_col_lines.append(
                        f"  - {col}  [type: {dtype}"
                        + (f", category: {cat}]" if cat else "]")
                    )

            enriched_lines = []
            for col in columns:
                inferred = dataset_col_type_map.get(col, {})
                if inferred:
                    enriched_lines.append(
                        f"  - {col}  [inferred type: {inferred['type']}, "
                        f"via schema col: {inferred['schema_col']}]"
                    )
                else:
                    enriched_lines.append(
                        f"  - {col}  [type: unknown — not mapped to schema]"
                    )

            by_category: dict = {}
            for col in columns:
                cat = tbl_schema.get(col, {}).get("category", "unknown")
                by_category.setdefault(cat, []).append(col)

            category_summary = "; ".join(
                f"{cat}: {', '.join(cols)}"
                for cat, cols in sorted(by_category.items())
            )

            content = f"""Table: {table_name}
This table is part of a multi-table dataset.

DATASET COLUMNS (raw columns from uploaded file):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(raw_col_lines)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet)'}

TARGET SCHEMA COLUMNS for this table (explicit type from schema JSON):
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded for this table)'}
Columns grouped by category: {category_summary}"""

            docs.append(Document(
                page_content=content,
                metadata={"type": "table_schema", "table": table_name}
            ))

        type_counts:          dict = {}
        cat_counts:           dict = {}
        all_schema_col_lines: list = []
        all_dataset_col_lines: list = []

        for col_def in target_schema:
            tbl      = _get_table_field(col_def)
            col_name = col_def.get("name", "")
            dtype    = col_def.get("type", "string")
            category = col_def.get("category", "")
            label    = f"{tbl}.{col_name}" if tbl else col_name
            all_schema_col_lines.append(
                f"  - {label}  [type: {dtype}, category: {category}]"
            )
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        for tbl_name, meta in tables_meta.items():
            for col in meta.get("columns", []):
                all_dataset_col_lines.append(f"  - {tbl_name}.{col}")

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        all_tables = list(tables_meta.keys())
        overview   = f"""Dataset Overview:
Type: Multi-table Excel dataset
Number of tables/sheets: {len(all_tables)}
Table names: {', '.join(all_tables)}

DATASET COLUMNS (raw — no explicit type info):
Total: {sum(len(m['columns']) for m in tables_meta.values())}
{chr(10).join(all_dataset_col_lines) if all_dataset_col_lines else '  (none)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total schema columns: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(all_schema_col_lines) if all_schema_col_lines else '  (no schema loaded)'}

DATASET COLUMN INFERRED TYPES (via schema mapping):
{chr(10).join(f"  - {dc}  [type: {info['type']}, schema_col: {info['schema_col']}]" for dc, info in dataset_col_type_map.items()) if dataset_col_type_map else '  (no mappings yet)'}"""

        docs.append(Document(
            page_content=overview,
            metadata={"type": "dataset_overview"}
        ))

        for tbl_name, meta in tables_meta.items():
            cols = meta.get("columns", [])
            docs.append(Document(
                page_content=(
                    f"Raw dataset columns for table '{tbl_name}' "
                    f"(actual column names in the uploaded Excel — no type info):\n"
                    f"{', '.join(cols)}"
                ),
                metadata={"type": "dataset_columns", "table": tbl_name}
            ))

    else:
        # ── Single table ──────────────────────────────────────────────────────
        columns = session.get("columns", [])

        schema_col_lines = []
        for col_def in target_schema:
            name  = col_def.get("name", "")
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            schema_col_lines.append(
                f"  - {name}  [type: {dtype}"
                + (f", category: {cat}]" if cat else "]")
            )

        enriched_lines = []
        for col in columns:
            inferred = dataset_col_type_map.get(col, {})
            if inferred:
                enriched_lines.append(
                    f"  - {col}  [inferred type: {inferred['type']}, "
                    f"via schema col: {inferred['schema_col']}]"
                )
            else:
                enriched_lines.append(
                    f"  - {col}  [type: unknown — not mapped to schema]"
                )

        type_counts: dict = {}
        cat_counts:  dict = {}
        for col_def in target_schema:
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if cat:
                cat_counts[cat]      = cat_counts.get(cat, 0) + 1

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        content = f"""Dataset Overview:
Type: Single-table dataset

DATASET COLUMNS (raw — no explicit type info):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(f'  - {col}' for col in columns)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet — run /get_mappings first)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded)'}"""

        docs.append(Document(
            page_content=content,
            metadata={"type": "dataset_overview"}
        ))

        chunk_size = 20
        for i in range(0, len(columns), chunk_size):
            chunk = columns[i:i + chunk_size]
            docs.append(Document(
                page_content=(
                    f"DATASET COLUMNS (raw, batch {i//chunk_size + 1}): "
                    f"{', '.join(chunk)}"
                ),
                metadata={"type": "column_list", "batch": i//chunk_size + 1}
            ))

        docs.append(Document(
            page_content=(
                f"Raw dataset columns (no type info):\n{', '.join(columns)}"
            ),
            metadata={"type": "dataset_columns"}
        ))

    # ── Target schema — batched ───────────────────────────────────────────────
    if target_schema:
        batch_size = 15
        for batch_start in range(0, len(target_schema), batch_size):
            batch         = target_schema[batch_start: batch_start + batch_size]
            batch_num     = batch_start // batch_size + 1
            total_batches = (len(target_schema) + batch_size - 1) // batch_size

            lines = [
                f"# Target Schema Reference "
                f"(batch {batch_num}/{total_batches}, "
                f"columns {batch_start+1}–{batch_start+len(batch)} "
                f"of {len(target_schema)} total)\n"
            ]

            by_category: dict = {}
            for col_def in batch:
                cat = col_def.get("category", "other")
                by_category.setdefault(cat, []).append(col_def)

            for category, cols in sorted(by_category.items()):
                lines.append(f"\n## Category: {category.upper()}")
                for col_def in cols:
                    name     = col_def.get("name", "")
                    dtype    = col_def.get("type", "string")
                    table    = _get_table_field(col_def)
                    tbl_part = f"  [table: {table}]" if table else ""
                    lines.append(f"  - {name}  [type: {dtype}]{tbl_part}")

            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":       "target_schema",
                    "batch":      batch_num,
                    "batch_cols": f"{batch_start+1}-{batch_start+len(batch)}",
                }
            ))

        if dataset_col_type_map:
            dtype_lines = [
                "Dataset Column Inferred Data Types "
                "(inferred via schema mapping — schema_to_dataset reverse lookup):",
                "These types are NOT in the raw dataset; "
                "they are inferred by matching dataset columns to schema columns.",
                "",
            ]
            by_type: dict = {}
            for dc, info in dataset_col_type_map.items():
                by_type.setdefault(info["type"], []).append(
                    f"{dc} (via schema col: {info['schema_col']})"
                )
            for dtype, entries in sorted(by_type.items()):
                dtype_lines.append(f"Type '{dtype}':")
                for entry in entries:
                    dtype_lines.append(f"  - {entry}")

            docs.append(Document(
                page_content="\n".join(dtype_lines),
                metadata={"type": "dataset_col_types"}
            ))

    # ── Rules ─────────────────────────────────────────────────────────────────
    rules_df = session.get("rules_df")
    if rules_df is not None:
        rules = rules_df.to_dict(orient="records")
        for i, rule in enumerate(rules):
            entities    = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            # mapped_dict: entity → schema_col
            # For each entity, show: entity → schema_col → dataset_col
            entity_mappings_text = {}
            for e in entities:
                schema_col  = mapped_dict.get(e, "not yet mapped")
                dataset_col = schema_to_dataset.get(schema_col, schema_col) if schema_col != "not yet mapped" else "not yet mapped"
                if dataset_col and dataset_col != schema_col:
                    entity_mappings_text[e] = f"{schema_col} (dataset: {dataset_col})"
                else:
                    entity_mappings_text[e] = schema_col

            involved_tables = ""
            rule_table_map  = session.get("rule_table_map", {})
            if rule_table_map.get(rule.get("name", "")):
                involved_tables = (
                    f"\nInvolved tables: "
                    f"{', '.join(rule_table_map[rule['name']])}"
                )

            content = f"""Rule #{i+1}: {rule.get('name', '')}
Description: {rule.get('description', '')}
Business Rule: {rule.get('business_rule', '')}
Category: {rule.get('category', '')}
Complexity: {rule.get('complexity', '')}
Entities extracted: {', '.join(entities)}
Entity to schema column mappings: {json.dumps(entity_mappings_text, indent=2)}
{involved_tables}
Check type: {rule.get('check_type', 'not specified')}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":       "rule",
                    "rule_index": i + 1,
                    "rule_name":  rule.get("name", ""),
                    "category":   rule.get("category", ""),
                    "complexity": rule.get("complexity", ""),
                }
            ))

        categories: dict = {}
        for r in rules:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, []).append(r.get("name", ""))

        summary_lines = [
            "Rules Summary:",
            f"Total rules: {len(rules)}",
            "Rules by category:",
        ]
        for cat, names in categories.items():
            summary_lines.append(f"  {cat} ({len(names)}): {', '.join(names)}")
        summary_lines.append("\nAll rule names in order:")
        for i, r in enumerate(rules):
            summary_lines.append(
                f"  {i+1}. {r.get('name', '')} [{r.get('category','')}]"
            )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "rules_summary"}
        ))

    # ── Execution results ─────────────────────────────────────────────────────
    executed_rules = session.get("executed_rules", set())
    rule_metrics   = session.get("rule_metrics", {})

    if executed_rules and rule_metrics:
        exec_lines = ["Execution Results:"]
        for rule_name in executed_rules:
            result       = session["result"][rule_name]
            passed_count = result.get("passed_count", 0)
            failed_count = result.get("failed_count", 0)
            exec_lines.append(
                f"  {rule_name}: passed={passed_count}, "
                f"failed={failed_count}, "
                f"pass_rate={rule_metrics.get(rule_name)}, "
                f"timestamp: {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
            )
        docs.append(Document(
            page_content="\n".join(exec_lines),
            metadata={"type": "execution_results"}
        ))

    # ── Remediation results ───────────────────────────────────────────────────
    remediation_log = session.get("remediation_log", [])

    if remediation_log:
        for i, entry in enumerate(remediation_log):
            logic         = entry.get("logic", "")
            rows_affected = entry.get("rows_affected", 0)
            failed_ids    = entry.get("failed_ids", [])
            rule_name     = entry.get("rule_name", "not specified")
            timestamp     = entry.get(
                "timestamp",
                datetime.now().strftime('%d %b %Y %H:%M:%S')
            )

            content = f"""Remediation #{i+1}:
Rule: {rule_name}
Logic applied: {logic}
Rows affected / fixed: {rows_affected}
Failed IDs remediated: {len(failed_ids)} records
Timestamp: {timestamp}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":              "remediation_results",
                    "remediation_index": i + 1,
                    "rule_name":         rule_name,
                    "rows_affected":     rows_affected,
                }
            ))

        total_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
        rem_summary_lines = [
            "Remediation Summary:",
            f"Total remediation actions applied: {len(remediation_log)}",
            f"Total rows fixed across all remediations: {total_fixed}",
            "",
            "Remediation history:",
        ]
        for i, entry in enumerate(remediation_log):
            rem_summary_lines.append(
                f"  #{i+1}: logic='{entry.get('logic','')}', "
                f"rows_fixed={entry.get('rows_affected', 0)}, "
                f"rule='{entry.get('rule_name', 'N/A')}', "
                f"timestamp='{entry.get('timestamp', '')}'"
            )

        docs.append(Document(
            page_content="\n".join(rem_summary_lines),
            metadata={"type": "remediation_summary"}
        ))

    else:
        docs.append(Document(
            page_content=(
                "Remediation Summary:\n"
                "No remediations have been applied yet. "
                "Remediation actions appear here after you fix failed records."
            ),
            metadata={"type": "remediation_summary"}
        ))

    # ── Mapped entities — per rule + full summaries ───────────────────────────
    # mapped_dict       = entity → schema_col
    # schema_to_dataset = schema_col → dataset_col

    if mapped_dict and rules_df is not None:
        rules = rules_df.to_dict(orient="records")

        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            rule_entity_schema  = {}  # entity → schema_col
            rule_schema_dataset = {}  # schema_col → dataset_col (for entities in this rule)

            for entity in entities:
                if entity in mapped_dict:
                    schema_col = mapped_dict[entity]
                    rule_entity_schema[entity] = schema_col
                    dataset_col = schema_to_dataset.get(schema_col)
                    if dataset_col and dataset_col != schema_col:
                        rule_schema_dataset[schema_col] = dataset_col

            if not rule_entity_schema:
                continue

            lines = [
                f"Entity-Column Mappings for Rule #{i+1}: {rule_name}",
                f"Rule name: {rule_name}",
                f"Rule number: {i+1}",
                "",
                "Hop 1 — Entity → Schema Column:",
            ]
            for entity, schema_col in rule_entity_schema.items():
                lines.append(f"  Entity '{entity}' → schema column '{schema_col}'")

            if rule_schema_dataset:
                lines.append("")
                lines.append("Hop 2 — Schema Column → Dataset Column:")
                for schema_col, dataset_col in rule_schema_dataset.items():
                    inferred  = dataset_col_type_map.get(dataset_col, {})
                    type_note = (
                        f" [schema type: {inferred['type']}]"
                        if inferred else ""
                    )
                    lines.append(
                        f"  Schema column '{schema_col}' → "
                        f"dataset column '{dataset_col}'{type_note}"
                    )
            else:
                lines.append("")
                lines.append("(Single-hop mapping: schema col == dataset col)")

            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":        "entity_mappings",
                    "rule_name":   rule_name,
                    "rule_number": i + 1,
                }
            ))

        # Full summary: entity → schema_col for all rules
        summary_lines = [
            f"Complete Entity → Schema Column Mappings for ALL {len(rules)} rules:",
        ]
        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            rule_pairs = [
                f"'{e}' → '{mapped_dict[e]}'"
                for e in entities if e in mapped_dict
            ]
            if rule_pairs:
                summary_lines.append(
                    f"  Rule #{i+1} ({rule_name}): {', '.join(rule_pairs)}"
                )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "entity_mappings_summary"}
        ))

        # Hop 1 doc: entity → schema_col
        hop1_lines = [
            "Complete Entity → Target Schema Column Mappings (Hop 1) for ALL rules:"
        ]
        for i, rule in enumerate(rules):
            entities = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            pairs = [
                f"'{e}' → '{mapped_dict[e]}'"
                for e in entities if e in mapped_dict
            ]
            if pairs:
                hop1_lines.append(
                    f"  Rule #{i+1} ({rule.get('name','')}): "
                    f"{', '.join(pairs)}"
                )
        docs.append(Document(
            page_content="\n".join(hop1_lines),
            metadata={"type": "entity_mappings_hop1"}
        ))

        # Hop 2 doc: schema_col → dataset_col
        # Only meaningful when schema_to_dataset has non-identity entries
        non_identity = {k: v for k, v in schema_to_dataset.items() if k != v}
        if non_identity:
            hop2_lines = [
                "Complete Target Schema Column → Dataset Column Mappings (Hop 2):"
            ]
            for schema_col, dataset_col in non_identity.items():
                inferred  = dataset_col_type_map.get(dataset_col, {})
                type_note = (
                    f" [schema type: {inferred['type']}]"
                    if inferred else ""
                )
                hop2_lines.append(
                    f"  Schema column '{schema_col}' → "
                    f"dataset column '{dataset_col}'{type_note}"
                )
            docs.append(Document(
                page_content="\n".join(hop2_lines),
                metadata={"type": "entity_mappings_hop2"}
            ))
        else:
            docs.append(Document(
                page_content=(
                    "Schema Column → Dataset Column Mappings (Hop 2):\n"
                    "Identity mapping — schema column names equal dataset column names. "
                    "No renaming was needed."
                ),
                metadata={"type": "entity_mappings_hop2"}
            ))

    else:
        docs.append(Document(
            page_content=(
                "Entity-Column Mappings: No mappings generated yet. "
                "Please run /get_mappings first."
            ),
            metadata={"type": "entity_mappings"}
        ))
        docs.append(Document(
            page_content=(
                "Complete Entity-Column Mappings for ALL rules: "
                "No mappings generated yet."
            ),
            metadata={"type": "entity_mappings_summary"}
        ))

    # ── Generated code ────────────────────────────────────────────────────────
    code_cache = session.get("code_cache", {})

    if not code_cache:
        docs.append(Document(
            page_content=(
                "Generated Code Summary:\n"
                "No PySpark code has been generated yet for any rule. "
                "Code must be generated before it can be shown."
            ),
            metadata={"type": "generated_code_summary"}
        ))
    else:
        rules_df_local = session.get("rules_df")
        rule_index_map: dict = {}
        if rules_df_local is not None:
            for i, row in enumerate(rules_df_local.to_dict(orient="records")):
                rule_index_map[row.get("name", "")] = i + 1

        for rule_name, cached in code_cache.items():
            pyspark_code = cached.get("pyspark_code", "")
            mc           = cached.get("mapped_dict", {})
            check_type   = cached.get("check_type", "")
            id_column    = cached.get("id_column", "")
            rule_number  = rule_index_map.get(rule_name, "?")

            if not pyspark_code:
                continue

            content = f"""Generated PySpark Code for Rule #{rule_number}: {rule_name}
Rule number: {rule_number}
Rule name: {rule_name}
Also referred to as: rule {rule_number}, rule number {rule_number}, the {rule_number} rule
Check Type: {check_type}
ID Column used: {id_column}
Mapped schema columns used: {json.dumps(mc)}

Code:
{pyspark_code}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":        "generated_code",
                    "rule_name":   rule_name,
                    "rule_number": rule_number,
                    "check_type":  check_type,
                }
            ))

        code_summary_lines = [
            "Generated Code Summary:",
            f"Total rules with generated code: {len(code_cache)}",
            f"Rules with code: {', '.join(code_cache.keys())}",
        ]
        for rule_name, cached in code_cache.items():
            rn = rule_index_map.get(rule_name, "?")
            code_summary_lines.append(
                f"  Rule #{rn} - {rule_name}: "
                f"check_type={cached.get('check_type','')}, "
                f"id_column={cached.get('id_column','')}"
            )
        docs.append(Document(
            page_content="\n".join(code_summary_lines),
            metadata={"type": "generated_code_summary"}
        ))

    return docs


# ─────────────────────────────────────────────────────────────────────────────
# RAG SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
class DQRagSystem:

    def __init__(self):
        http_client = httpx.Client(verify=False)

        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

        self.llm = AzureChatOpenAI(
            azure_endpoint   = AZURE_OPENAI_ENDPOINT,
            api_key          = AZURE_OPENAI_API_KEY,
            api_version      = AZURE_OPENAI_API_VERSION,
            azure_deployment = AZURE_OPENAI_DEPLOYMENT,
            temperature      = 0,
            http_client      = http_client,
        )

        self.vector_store = None
        self._split_docs  = []
        self.all_docs     = []
        self.session_id   = None
        self._build_intent_classifier()
        self._answer_chain = None

    def _build_intent_classifier(self):
        intent_descriptions = "\n".join([
            f'- "{key}": {cfg["description"]}\n'
            f'  Examples: {", ".join(cfg["examples"][:2])}'
            for key, cfg in INTENT_CONFIG.items()
        ])
        self._intent_system = f"""You are a query intent classifier for a Data Quality Engine.

Classify the user's question into EXACTLY ONE of these intents:

{intent_descriptions}

Return ONLY the intent key as a single word — no explanation, no punctuation.
Valid responses: {', '.join(INTENT_CONFIG.keys())}"""

    def classify_intent(self, question: str, chat_history: list = None) -> str:
        history_context = ""
        if chat_history:
            recent = chat_history[-4:]
            history_context = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:150]}"
                for m in recent
            ])

        messages = [
            SystemMessage(content=self._intent_system),
            HumanMessage(content=f"Question: {question}{history_context}"),
        ]

        try:
            response = self.llm.invoke(messages)
            intent   = response.content.strip().lower().replace('"','').replace("'","")
            if intent not in INTENT_CONFIG:
                print(f"⚠️ Unknown intent '{intent}', falling back to general")
                intent = "general"
            print(f"🎯 Intent: '{question[:60]}' → {intent}")
            return intent
        except Exception as e:
            print(f"⚠️ Intent classification failed: {e}, using general")
            return "general"

    def build_index(self, session: dict, session_id: str) -> int:
        print(f"🔍 Building RAG index for session {session_id}...")

        docs = build_documents_from_session(session)
        self.all_docs   = docs
        self.session_id = session_id

        no_split_types = {
            "generated_code",
            "entity_mappings_summary",
            "entity_mappings_hop1",
            "entity_mappings_hop2",
            "generated_code_summary",
            "target_schema",
            "dataset_columns",
            "dataset_col_types",
            "remediation_summary",
        }

        text_docs      = [d for d in docs if d.metadata.get("type") not in no_split_types]
        no_split_docs  = [d for d in docs if d.metadata.get("type") in no_split_types]

        text_splitter   = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
        split_text_docs = text_splitter.split_documents(text_docs)

        code_docs      = [d for d in no_split_docs if d.metadata.get("type") == "generated_code"]
        other_no_split = [d for d in no_split_docs if d.metadata.get("type") != "generated_code"]

        code_splitter   = RecursiveCharacterTextSplitter(
            chunk_size=4000, chunk_overlap=0,
            separators=["\ndef ", "\nclass ", "\n\n", "\n"],
        )
        split_code_docs = code_splitter.split_documents(code_docs)

        split_docs = split_text_docs + split_code_docs + other_no_split

        print(f"📄 Indexing {len(split_docs)} chunks from {len(docs)} documents...")
        self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
        self._split_docs  = split_docs
        self._build_answer_chain()
        print(f"✅ RAG index ready — {len(split_docs)} chunks indexed")
        return len(split_docs)

    def update_index(self, session: dict):
        if self.session_id:
            self.build_index(session, self.session_id)

    def _get_filtered_retriever(self, intent: str):
        doc_types = INTENT_CONFIG[intent]["doc_types"]

        if intent == "mapping_query":
            k = 20
        elif intent in ("code_query",):
            k = 8
        elif intent == "schema_query":
            k = 10
        elif intent == "remediation_query":
            k = 6
        else:
            k = 6

        if doc_types is not None:
            filtered = [
                d for d in self._split_docs
                if d.metadata.get("type") in doc_types
            ]
            if not filtered:
                filtered = self._split_docs
        else:
            filtered = self._split_docs

        bm25   = BM25Retriever.from_documents(filtered)
        bm25.k = k

        if doc_types is not None and len(filtered) < len(self._split_docs):
            try:
                faiss_filtered = FAISS.from_documents(filtered, self.embeddings)
                semantic = faiss_filtered.as_retriever(
                    search_type="similarity",
                    search_kwargs={"k": k},
                )
            except Exception:
                semantic = self.vector_store.as_retriever(
                    search_kwargs={"k": k}
                )
        else:
            semantic = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": k},
            )

        return EnsembleRetriever(
            retrievers=[bm25, semantic],
            weights=[0.5, 0.5],
        )

    def _rerank(self, query: str, docs: List[Document], top_n: int = 5) -> List[Document]:
        return docs[:top_n]

    def _direct_lookup(self, intent: str, search_question: str,
                       session_rules: list) -> Optional[List[Document]]:
        q           = search_question.lower()
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        name_to_idx = {v.lower(): k for k, v in idx_to_name.items()}

        rule_num = None
        match = re.search(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b', q, re.IGNORECASE
        )
        if match:
            rule_num = int(match.group(1))
        else:
            for name, idx in name_to_idx.items():
                if name and name in q:
                    rule_num = idx
                    break

        if rule_num is None:
            return None

        target_type = {
            "code_query":        "generated_code",
            "mapping_query":     "entity_mappings",
            "rule_query":        "rule",
            "execution_query":   "execution_results",
            "remediation_query": "remediation_results",
        }.get(intent)

        if target_type is None:
            return None

        matched = [
            d for d in self.all_docs
            if d.metadata.get("type") == target_type
            and d.metadata.get("rule_number") == rule_num
        ]

        if matched:
            print(f"🎯 Direct lookup: rule {rule_num} / {target_type} → {len(matched)} docs")
            return matched
        return None

    def _is_followup_query(self, question: str, chat_history: list) -> bool:
        if not chat_history:
            return False

        q = question.lower().strip()

        code_request_signals = [
            "give code", "show code", "display code",
            "give me code", "show me code", "pyspark code for",
            "generate code for",
        ]
        if any(sig in q for sig in code_request_signals):
            print(f"💻 Code request — standalone: '{question}'")
            return False

        followup_signals = [
            q.startswith("it "), q.startswith("its "),
            q.startswith("that "), q.startswith("this "),
            q.startswith("they "), q.startswith("these "),
            q.startswith("those "), q.startswith("and "),
            q.startswith("but "), q.startswith("so "),
            q.startswith("also "), q.startswith("then "),
            q.startswith("what about "), q.startswith("how about "),
            q.startswith("what if "),
            "the same" in q,
            len(q.split()) <= 4 and bool(chat_history),
            q in ("why?", "how?", "when?", "who?", "which?",
                  "explain.", "elaborate.", "more?"),
            "explain in" in q, "tell me more" in q,
            "give me more" in q, "what does that mean" in q,
            "can you elaborate" in q, "simplify" in q, "in simple" in q,
        ]

        if any(followup_signals):
            print(f"🔗 Follow-up (rule-based): '{question}'")
            return True

        if 4 < len(q.split()) <= 15 and chat_history:
            return self._llm_classify_followup(question, chat_history)
        return False

    def _llm_classify_followup(self, question: str, chat_history: list) -> bool:
        recent = chat_history[-4:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
        ])
        prompt = f"""Conversation so far:
{history_str}

New question: "{question}"

Is this a follow-up or a new independent question?
Answer with exactly one word: yes or no"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            answer   = response.content.strip().lower().replace(".", "")
            is_fu    = answer.startswith("yes")
            print(f"🤖 Follow-up check: '{question}' → {answer}")
            return is_fu
        except Exception as e:
            print(f"⚠️ Follow-up check failed: {e}")
            return False

    def _rewrite_query(self, question: str, chat_history: list) -> str:
        recent = chat_history[-6:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:300]}" for m in recent
        ])
        prompt = f"""Rewrite this follow-up into a complete standalone question.

Conversation:
{history_str}

Follow-up: "{question}"

Rewritten (return ONLY the question):"""

        try:
            response  = self.llm.invoke([HumanMessage(content=prompt)])
            rewritten = response.content.strip().strip('"').strip("'")
            if rewritten and rewritten != question:
                print(f"✏️  Rewritten: '{question}' → '{rewritten}'")
                return rewritten
            return question
        except Exception as e:
            print(f"⚠️ Rewrite failed: {e}")
            return question

    def _resolve_rule_references(self, question: str,
                                  session_rules: list) -> str:
        ordinals = {
            "first": 1, "second": 2, "third": 3, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10,
        }
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        resolved    = question

        def replace_numbered(match):
            num  = int(match.group(1))
            name = idx_to_name.get(num, "")
            return f"rule {num} ({name})" if name else match.group(0)

        resolved = re.sub(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b',
            replace_numbered, resolved, flags=re.IGNORECASE
        )

        def replace_ordinal(match):
            word = match.group(1).lower()
            num  = ordinals.get(word)
            if num:
                name = idx_to_name.get(num, "")
                if name:
                    return f"rule {num} ({name})"
            return match.group(0)

        resolved = re.sub(
            r'\b(' + '|'.join(ordinals.keys()) + r')\s+rule\b',
            replace_ordinal, resolved, flags=re.IGNORECASE
        )

        if resolved != question:
            print(f"🔄 Resolved: '{question}' → '{resolved}'")
        return resolved

    def _generate_compute_code(self, question: str,
                                snapshot: dict,
                                chat_history: list = None) -> str:
        history_ctx = ""
        if chat_history:
            recent = chat_history[-4:]
            history_ctx = "\nRecent conversation:\n" + "\n".join(
                f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
            )

        schema_preview = {
            "rules":               f"{len(snapshot['rules'])} rules",
            "run_log":             f"{len(snapshot['run_log'])} executed",
            "rule_metrics":        f"{len(snapshot['rule_metrics'])} entries",
            "remediation_summary": snapshot.get("remediation_summary", {}),
            "schema":              snapshot["schema"],
            "total_rules":         snapshot["total_rules"],
            "executed_count":      snapshot["executed_count"],
            "code_generated_for":  snapshot["code_generated_for"],
        }

        system_prompt = f"""You are a Python code generator for a Data Quality Engine.

Write a function `compute(data)` that answers the user's question.

`data` structure:
{json.dumps(schema_preview, indent=2, default=str)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY DATA PATHS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCHEMA — target_schema is ALWAYS complete (all columns, untruncated):
  data['schema']['target_schema']
    → list of dicts: [{{"name","type","category"[,"table"]}}]

DATASET COL INFERRED TYPES (via schema mapping):
  data['schema']['dataset_col_type_map']
    → {{dataset_col: {{"type","category","schema_col"}}}}
    → Use when user asks data type of a DATASET column (e.g. "acct_number")
    → If col not in map: it hasn't been mapped to a schema col yet

MAPPING MODEL (NEW):
  data['schema']['entity_to_schema_col']    → {{entity: schema_col}}
  data['schema']['schema_col_to_dataset_col'] → {{schema_col: dataset_col}}
  NOTE: mapped_dict = entity → schema_col (NOT dataset_col directly)
        To get dataset_col for an entity:
          schema_col  = entity_to_schema_col[entity]
          dataset_col = schema_col_to_dataset_col.get(schema_col, schema_col)

MULTI-TABLE:
  data['schema']['schema_info']       → {{table: {{col: {{data_type, category}}}}}}
  data['schema']['type_counts']       → {{dtype: count}}
  data['schema']['category_counts']   → {{category: count}}
  data['schema']['tables']            → {{table: {{columns, column_count, row_count}}}}

SINGLE-TABLE:
  data['schema']['schema_columns_to_type']     → {{col: dtype}}
  data['schema']['schema_columns_to_category'] → {{col: category}}
  data['schema']['type_counts']                → {{dtype: count}}
  data['schema']['category_counts']            → {{category: count}}

EXECUTION:
  data['run_log']       → [{{rule_name, passed_count, failed_count, pass_rate, timestamp}}]
  data['rule_metrics']  → {{rule_name: pass_rate}}
  data['code_generated_for'] → [rule_name, ...]

REMEDIATION:
  data['remediation_summary']['total_actions']    → int
  data['remediation_summary']['total_rows_fixed'] → int
  data['remediation_summary']['actions']          → list of dicts:
    each: {{index, rule_name, logic, rows_affected, failed_ids_count, timestamp}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"tell me data types of all schema columns":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    if not cols:
        return "No schema loaded"
    return {{col.get('name'): col.get('type','unknown') for col in cols}}

"give columns whose data type is string":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('type','').lower() == 'string']

"give columns in the financial category":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('category','').lower() == 'financial']

"what is the data type of acct_number":
def compute(data):
    # Check dataset col type map first (inferred via schema mapping)
    m    = data['schema'].get('dataset_col_type_map', {{}})
    info = m.get('acct_number')
    if info:
        return (f"acct_number → inferred type '{{info['type']}}' "
                f"via schema column '{{info['schema_col']}}'")
    # Fallback: check if it matches a schema col directly
    cols = data['schema'].get('target_schema', [])
    for c in cols:
        if c.get('name','').lower() == 'acct_number':
            return f"acct_number is a schema column with type '{{c.get('type')}}'"
    return ("acct_number has not been mapped to a schema column yet. "
            "Run /get_mappings first.")

"what entity maps to schema column net_return_value":
def compute(data):
    e2s = data['schema'].get('entity_to_schema_col', {{}})
    return {{e: s for e, s in e2s.items() if s == 'net_return_value'}} or "Not found"

"what dataset column does entity X map to":
def compute(data):
    e2s = data['schema'].get('entity_to_schema_col', {{}})
    s2d = data['schema'].get('schema_col_to_dataset_col', {{}})
    schema_col  = e2s.get('X')
    if not schema_col:
        return "Entity X not in mappings"
    dataset_col = s2d.get(schema_col, schema_col)
    return f"Entity 'X' → schema col '{{schema_col}}' → dataset col '{{dataset_col}}'"

"how many rows were remediated":
def compute(data):
    return data.get('remediation_summary', {{}}).get('total_rows_fixed', 0)

"show remediation history":
def compute(data):
    actions = data.get('remediation_summary', {{}}).get('actions', [])
    if not actions:
        return "No remediations applied yet"
    return actions

"which dataset columns have inferred types":
def compute(data):
    m = data['schema'].get('dataset_col_type_map', {{}})
    if not m:
        return "No mappings yet — run /get_mappings first"
    return {{dc: info['type'] for dc, info in m.items()}}

"list all schema columns grouped by category":
def compute(data):
    cols   = data['schema'].get('target_schema', [])
    result = {{}}
    for c in cols:
        cat = c.get('category', 'unknown')
        result.setdefault(cat, []).append(c.get('name'))
    return result

"what are the schema columns in the Orders table":
def compute(data):
    table_name  = 'Orders'
    schema_cols = data['schema'].get('target_schema', [])
    by_table = [
        c for c in schema_cols
        if (c.get('table') or c.get('table_name') or '') == table_name
    ]
    if not by_table:
        schema_info = data['schema'].get('schema_info', {{}})
        table_info  = schema_info.get(table_name, {{}})
        return [
            {{'name': col, 'type': info.get('data_type','unknown'),
             'category': info.get('category','')}}
            for col, info in table_info.items()
        ] or f"No schema columns found for table '{{table_name}}'"
    return [
        {{'name': c.get('name'), 'type': c.get('type'), 'category': c.get('category')}}
        for c in by_table
    ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Function named `compute(data)` only
2. Return: string, list, dict, int, or float — no DataFrames
3. Handle missing keys and empty lists gracefully
4. NO import statements — pre-injected globals available:
   datetime, date, timedelta, math, re, json, Counter, defaultdict, dateutil_parser
5. Return ONLY the function — no markdown, no backticks

{history_ctx}"""

        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Question: {question}"),
        ])

        code = response.content.strip()
        code = code.replace("```python", "").replace("```", "").strip()
        return code

    def _execute_compute_code(self, code: str, snapshot: dict) -> tuple:
        import math
        import re as re_module
        import json as json_module
        from datetime import datetime, date, timedelta
        from collections import Counter, defaultdict

        try:
            from dateutil import parser as dateutil_parser
        except ImportError:
            dateutil_parser = None

        allowed_globals = {
            "__builtins__": {
                "len": len, "range": range, "enumerate": enumerate,
                "zip": zip, "map": map, "filter": filter,
                "sorted": sorted, "reversed": reversed,
                "min": min, "max": max, "sum": sum, "abs": abs,
                "round": round, "int": int, "float": float,
                "str": str, "bool": bool, "list": list,
                "dict": dict, "set": set, "tuple": tuple,
                "isinstance": isinstance, "any": any, "all": all,
                "print": print, "type": type,
                "hasattr": hasattr, "getattr": getattr,
                "None": None, "True": True, "False": False,
            },
            "datetime": datetime, "date": date, "timedelta": timedelta,
            "math": math, "json": json_module, "re": re_module,
            "Counter": Counter, "defaultdict": defaultdict,
            "dateutil_parser": dateutil_parser,
        }

        local_vars = {}
        try:
            exec(code, allowed_globals, local_vars)
            compute_fn = local_vars.get("compute")
            if compute_fn is None:
                return None, "Generated code did not define a `compute` function"
            result = compute_fn(snapshot)
            return result, None
        except Exception as e:
            return None, f"Execution error: {str(e)}\n\nCode:\n{code}"

    def _compute_to_answer(self, question: str, result,
                            code: str, error: str = None) -> str:
        if error:
            return (
                f"I understood your question but had trouble computing the answer. "
                f"Error: {error}"
            )

        prompt = f"""The user asked: "{question}"

Python function returned:
{json.dumps(result, indent=2, default=str)}

Write a clear, concise natural-language answer.
- Include actual values (names, types, numbers) from the result
- Use bullet points if result is a list/dict with more than 3 items
- Do not mention Python, functions, or the technical process
- Keep under 400 words (longer if listing many columns)
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _run_compute_pipeline(self, question: str,
                               session: dict,
                               chat_history: list = None) -> dict:
        snapshot = build_structured_snapshot(session)
        print(f"🧮 Compute: '{question[:60]}'")

        code = self._generate_compute_code(question, snapshot, chat_history)
        print(f"📝 Code:\n{code}\n")

        result, error = self._execute_compute_code(code, snapshot)
        print(f"⚙️  Result: {str(result)[:100]}, error: {error}")

        if error and "Execution error" in error:
            print("🔄 Retrying...")
            retry_code = self._generate_compute_code(
                f"{question}\n\nPrevious attempt failed: {error}",
                snapshot, chat_history
            )
            result, error = self._execute_compute_code(retry_code, snapshot)
            code = retry_code

        answer = self._compute_to_answer(question, result, code, error)

        return {
            "answer":       answer,
            "intent":       "compute",
            "compute_code": code,
            "raw_result":   result,
            "sources":      [{"type": "structured_compute",
                              "snippet": str(result)[:100]}],
        }

    def _build_answer_chain(self):
        self._answer_prompt = ChatPromptTemplate.from_template("""
You are a Data Quality Engine assistant. Answer ONLY from the context below.

IMPORTANT DISTINCTIONS:
- "DATASET COLUMNS" = raw column names from the uploaded file. No explicit type info.
- "TARGET SCHEMA COLUMNS" = columns from the schema JSON with explicit data type and category.
- "INFERRED DATASET COLUMN TYPES" = types inferred by matching dataset cols to schema cols via mappings.
- If user asks data type of a dataset column, look under "DATASET COLUMNS WITH INFERRED DATA TYPES".
- If not found there, say the column hasn't been mapped to a schema column yet.
- "REMEDIATION" = actions taken to fix failed records after rule execution.
- MAPPING MODEL: entity → schema_col (Hop 1), schema_col → dataset_col (Hop 2).
  The generated PySpark code uses SCHEMA column names (not dataset column names).
  Dataset columns are renamed to schema names before code runs.

If the answer is not in the context:
"I don't have that information in the current session."

Rules:
- CODE: return COMPLETE code, never truncate
- Rules: numbered lists (#1, #2 etc.)
- Columns: bullet points
- Keep under 300 words unless listing many items requires more

Context:
{context}

Question: {question}

Answer:""")

    @staticmethod
    def _format_docs(docs: List[Document]) -> str:
        if not docs:
            return "No relevant documents found."
        return "\n\n---\n\n".join(d.page_content for d in docs)

    def query(self, question: str, chat_history: list = None,
              session: dict = None) -> dict:
        if self.vector_store is None:
            return {
                "answer":  "RAG index not built yet. Please upload your dataset first.",
                "intent":  "unknown",
                "sources": [],
            }

        effective_question = question

        if chat_history:
            if self._is_followup_query(question, chat_history):
                effective_question = self._rewrite_query(question, chat_history)
            else:
                print(f"🆕 Standalone: '{question}'")
        else:
            print("No chat history")

        intent     = self.classify_intent(effective_question, chat_history)
        is_compute = INTENT_CONFIG.get(intent, {}).get("compute", False)

        if is_compute:
            if session is None:
                return {
                    "answer":  "Session data is required for this query.",
                    "intent":  intent,
                    "sources": [],
                }
            return self._run_compute_pipeline(
                effective_question, session, chat_history
            )

        doc_types     = INTENT_CONFIG[intent]["doc_types"]
        search_question = effective_question
        session_rules   = []

        if session is not None:
            rules_df = session.get("rules_df")
            if rules_df is not None:
                session_rules   = rules_df.to_dict(orient="records")
                search_question = self._resolve_rule_references(
                    effective_question, session_rules
                )

        direct_docs = self._direct_lookup(intent, search_question, session_rules)

        if direct_docs:
            retrieved_docs = direct_docs
            print(f"⚡ Direct lookup: {len(retrieved_docs)} docs")
        else:
            retriever = self._get_filtered_retriever(intent)
            try:
                retrieved_docs = retriever.invoke(search_question)
            except Exception as e:
                print(f"⚠️ Retrieval failed ({e}), falling back")
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            if not retrieved_docs:
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            retrieved_docs = self._rerank(search_question, retrieved_docs, top_n=5)

        if intent == "code_query":
            summary_in = any(
                d.metadata.get("type") == "generated_code_summary"
                for d in retrieved_docs
            )
            if not summary_in:
                for doc in self.all_docs:
                    if doc.metadata.get("type") == "generated_code_summary":
                        retrieved_docs = [doc] + list(retrieved_docs)
                        break

            summary_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code_summary"
            ]
            no_code = any(
                "no pyspark code has been generated yet" in d.page_content.lower()
                for d in summary_docs
            )

            if no_code:
                return {
                    "answer": (
                        "No code has been generated yet. "
                        "Please generate code for the rule first."
                    ),
                    "intent":    intent,
                    "doc_types": doc_types,
                    "sources":   [],
                }

            code_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code"
            ]
            if code_docs:
                retrieved_docs = code_docs + summary_docs

        context = self._format_docs(retrieved_docs)

        history_text = ""
        if chat_history:
            recent = chat_history[-4:]
            history_text = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:200]}"
                for m in recent
            ])

        full_prompt = self._answer_prompt.format_messages(
            context  = context + history_text,
            question = question,
        )

        try:
            answer = self.llm.invoke(full_prompt).content
        except Exception as e:
            answer = f"Failed to generate answer: {str(e)}"

        sources = []
        seen    = set()
        for doc in retrieved_docs:
            key = (doc.metadata.get("rule_name") or
                   doc.metadata.get("table") or
                   doc.metadata.get("type"))
            if key and key not in seen:
                seen.add(key)
                sources.append({
                    "type":        doc.metadata.get("type"),
                    "rule_name":   doc.metadata.get("rule_name"),
                    "rule_number": doc.metadata.get("rule_number"),
                    "table":       doc.metadata.get("table"),
                    "snippet":     doc.page_content[:100] + "…",
                })

        print(f"✅ Answered — intent={intent}, "
              f"sources={[s['type'] for s in sources]}")

        return {
            "answer":          answer,
            "intent":          intent,
            "doc_types":       doc_types,
            "sources":         sources,
            "rewritten_query": (
                effective_question if effective_question != question else None
            ),
        }

    def is_ready(self) -> bool:
        return self.vector_store is not None


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped RAG store
# ─────────────────────────────────────────────────────────────────────────────
RAG_STORE: dict = {}

def get_or_create_rag(session_id: str) -> DQRagSystem:
    if session_id not in RAG_STORE:
        RAG_STORE[session_id] = DQRagSystem()
    return RAG_STORE[session_id]
'''

import os
import sys
import re
import ssl

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable
# setdefault, not assignment: a container/CI JAVA_HOME must win. The literal below is only a Windows dev fallback.
os.environ.setdefault('JAVA_HOME', r"C:\Program Files\Java\jdk-17.0.19")

os.environ['HF_HUB_DISABLE_XET'] = '1'

ssl._create_default_https_context = ssl._create_unverified_context

import requests
requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)
_orig_send = requests.Session.send
def _patched_send(self, request, **kwargs):
    kwargs['verify'] = False
    return _orig_send(self, request, **kwargs)
requests.Session.send = _patched_send

import json
import time
from typing import List, Optional
from dotenv import load_dotenv
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
import httpx

load_dotenv()

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_table_field(col_def: dict) -> str:
    return col_def.get("table_name")


def _build_dataset_col_type_map(session: dict) -> dict:
    """
    Build: dataset_column → {type, category, schema_col}

    Mapping model:
      mapped_dict       = entity → schema_col
      schema_to_dataset = schema_col → dataset_col

    Paths:
      Path A: schema_to_dataset reversed (schema_col → dataset_col)
      Path B: mapped_dict (entity → schema_col) + schema_to_dataset composition
      Path C: name-match fallback for single-hop (no target schema)
    """
    target_schema     = session.get("target_schema", [])
    schema_to_dataset = session.get("schema_to_dataset", {})
    mapped_dict       = session.get("mapped_dict", {})

    schema_type_map: dict = {}
    for col in target_schema:
        name = col.get("name", "")
        if name:
            schema_type_map[name] = {
                "type":     col.get("type", "unknown"),
                "category": col.get("category", ""),
            }

    result: dict = {}

    # Path A
    for schema_col, dataset_col in schema_to_dataset.items():
        if dataset_col and schema_col in schema_type_map and dataset_col != schema_col:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path B
    for entity, schema_col in mapped_dict.items():
        dataset_col = schema_to_dataset.get(schema_col)
        if dataset_col and schema_col in schema_type_map and dataset_col not in result:
            info = schema_type_map[schema_col]
            result[dataset_col] = {
                "type":       info["type"],
                "category":   info["category"],
                "schema_col": schema_col,
            }

    # Path C: single-hop fallback
    if schema_type_map:
        schema_names_lower = {
            name.lower().replace("_", " "): name
            for name in schema_type_map
        }
        for entity, schema_col in mapped_dict.items():
            if schema_col and schema_col not in result:
                if schema_col in schema_type_map:
                    info = schema_type_map[schema_col]
                    result[schema_col] = {
                        "type":       info["type"],
                        "category":   info["category"],
                        "schema_col": schema_col,
                    }
                else:
                    normalised = schema_col.lower().replace("_", " ")
                    matched = schema_names_lower.get(normalised)
                    if matched:
                        info = schema_type_map[matched]
                        result[schema_col] = {
                            "type":       info["type"],
                            "category":   info["category"],
                            "schema_col": matched,
                        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# INTENT DEFINITIONS
#
# FIX 1: schema_data_query now has doc_types=None so it always hits compute.
# FIX 2: schema_query description tightened to exclude enumeration questions,
#         and compute=True added so listing questions that slip through still
#         get a complete deterministic answer.
# ─────────────────────────────────────────────────────────────────────────────
INTENT_CONFIG = {
    "temporal_query": {
        "description": (
            "Questions involving time, timestamps, dates — "
            "e.g. 'rules executed before 3 PM', 'latest run', "
            "'what ran today', 'execution order'"
        ),
        "examples": [
            "which rules ran before 3pm",
            "what was the last rule executed",
            "show rules executed after 2 Jan 2025",
            "which rule ran most recently",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "mathematical_query": {
        "description": (
            "Questions requiring calculation, aggregation, comparison, ranking, "
            "OR counting — including counting rows in the dataset/tables, "
            "counting columns, how many records, total rows, row counts per table, "
            "average pass rate, rule with most failures, total failed records, "
            "difference between pass rates."
        ),
        "examples": [
            "how many rows does the dataset have",
            "how many records are in the Territory table",
            "how many columns have type int",
            "count columns with type string",
            "total number of rows across all tables",
            "what is the average pass rate across all rules",
            "which rule has the most failed records",
            "rank rules by pass rate",
            "how many more records failed in rule 2 vs rule 3",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "filter_query": {
        "description": (
            "Questions that filter or search for rules/columns matching a condition — "
            "e.g. 'rules with pass rate below 80%', "
            "'rules in the financial category that failed'"
        ),
        "examples": [
            "rules with pass rate below 80 percent",
            "which rules failed more than 100 records",
            "show rules that belong to financial category and failed",
            "rules with complexity high that were executed",
        ],
        "doc_types": None,
        "compute":   True,
    },
    "schema_data_query": {
        "description": (
            "Questions asking to LIST, SHOW, GIVE, or TELL data types, categories, "
            "or properties of schema columns OR dataset columns (via mapping). "
            "Use for ANY question that enumerates or describes column types/categories. "
            "Examples: 'give me all schema columns', 'tell me data types of all schema columns', "
            "'list all schema columns with their types', 'what type is column X', "
            "'which columns are of type string', 'show dataset columns with type float', "
            "'what schema columns are in X table', 'show me all target schema columns', "
            "'give columns in the financial category', 'what data type does acct_number map to'."
        ),
        "examples": [
            "give me all schema columns",
            "tell me the data types of all schema columns",
            "list all schema columns with their types",
            "give columns whose data type is string",
            "what type is order_id",
            "show all target schema columns",
            "which columns belong to the financial category",
            "give dataset columns whose data type is string",
            "what schema columns are in the Orders table",
            "list schema columns for the Products table",
            "show schema columns in Orders",
            "what are the target schema columns in Customers",
            "what is the data type of acct_number",
            "what data type does closing_balance map to",
        ],
        "doc_types": None,   # always compute — no retrieval
        "compute":   True,
    },
    "schema_query": {
        "description": (
            "Questions about dataset STRUCTURE OVERVIEW ONLY — which tables exist, "
            "general dataset shape, what the dataset looks like at a high level. "
            "Do NOT use for listing column names, data types, or enumerating schema columns — "
            "those go to schema_data_query. "
            "Examples: 'what tables are in the dataset', 'describe the dataset structure', "
            "'how many tables are there'."
        ),
        "examples": [
            "what tables are in the dataset",
            "describe the dataset structure",
            "how many tables are there",
            "what is the structure of the dataset",
            "give me an overview of the dataset",
        ],
        # FIX: compute=True so listing questions that slip through here still
        # get a complete deterministic answer instead of partial RAG results.
        "doc_types": [
            "dataset_overview", "target_schema",
            "table_schema", "column_list", "dataset_columns",
        ],
        "compute":   True,
    },
    "rule_query": {
        "description": "Questions about specific rules, business logic, what a rule validates",
        "examples": [
            "what does rule 3 do", "which rules check for null",
            "what is the business rule for", "how many rules",
            "what category is rule", "list all rules",
        ],
        "doc_types": ["rule", "rules_summary"],
    },
    "mapping_query": {
        "description": (
            "Questions about entity-to-column mappings for any or all rules, "
            "which column an entity maps to, mappings for all rules, "
            "entity-to-target_column mappings, "
            "target_column-to-source_column mappings, "
            "show all mappings, what are the mappings"
        ),
        "examples": [
            "what column does account number map to",
            "show mappings for all rules",
            "what are the mappings for every rule",
            "What column in the schema is mapped to account number",
            "which entity maps to Territory_ID",
            "what are the mappings for rule 2",
        ],
        "doc_types": [
            "entity_mappings", "entity_mappings_summary",
            "entity_mappings_hop1", "entity_mappings_hop2", "rule",
        ],
    },
    "execution_query": {
        "description": (
            "Questions about execution results, pass rates, failed records, "
            "which rules passed or failed"
        ),
        "examples": [
            "which rules failed", "what is the pass rate",
            "how many records failed", "show me execution results",
            "which rule has the worst pass rate",
        ],
        "doc_types": ["execution_results", "rules_summary"],
    },
    "remediation_query": {
        "description": (
            "Questions about data remediation actions, remediation history, "
            "what remediations were applied, how many rows were fixed, "
            "remediation logic used, audit log of remediations"
        ),
        "examples": [
            "what remediations have been applied",
            "how many rows were fixed",
            "show me the remediation history",
            "what logic was used to fix the data",
            "how many records were remediated",
            "show remediation audit log",
        ],
        "doc_types": ["remediation_results", "remediation_summary"],
        "compute":   False,
    },
    "rule_and_schema": {
        "description": (
            "Questions that need both rule information and "
            "schema/column information together"
        ),
        "examples": [
            "which columns does rule 3 use",
            "what fields are validated by",
            "which table does rule 2 apply to",
        ],
        "doc_types": [
            "rule", "rules_summary", "table_schema", "dataset_overview",
            "target_schema", "entity_mappings", "entity_mappings_hop1",
        ],
    },
    "code_query": {
        "description": (
            "Questions about generated PySpark code, requests to show or give "
            "code for a rule, what code was generated, check types used. "
            "Includes: 'give code for rule 1', 'show code for rule 3', "
            "'display the pyspark code', 'was code generated for all rules', "
            "'what rules have code'"
        ),
        "examples": [
            "what code was generated for rule 3",
            "show me the pyspark code for",
            "give code for rule 1",
            "display code for rule 2",
            "what check type does rule 2 use",
            "which id column is used in the code",
            "was code generated for all rules",
            "what rules have code generated",
        ],
        "doc_types": ["generated_code", "generated_code_summary"],
    },
    "general": {
        "description": "General questions or unclear intent — search everything",
        "examples":    ["tell me about the data", "give me a summary"],
        "doc_types":   None,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────
def build_structured_snapshot(session: dict) -> dict:
    rules_df   = session.get("rules_df")
    rules_list = rules_df.to_dict(orient="records") if rules_df is not None else []

    rule_metrics  = session.get("rule_metrics", {})
    code_cache    = session.get("code_cache", {})
    target_schema = session.get("target_schema", [])

    run_log = []
    for i, rule in enumerate(rules_list):
        name = rule.get("name", "")
        if name in rule_metrics:
            result = session["result"][name]
            run_log.append({
                "rule_index":   i + 1,
                "rule_name":    name,
                "category":     rule.get("category", ""),
                "complexity":   rule.get("complexity", ""),
                "passed_count": result.get("passed_count", 0),
                "failed_count": result.get("failed_count", 0),
                "pass_rate":    result.get("pass_rate", 0.0),
                "timestamp":    session["timestamp"][name],
                "has_code":     name in code_cache,
                "check_type":   code_cache.get(name, {}).get("check_type", ""),
            })

    remediation_log  = session.get("remediation_log", [])
    total_rows_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
    remediation_summary = {
        "total_actions":    len(remediation_log),
        "total_rows_fixed": total_rows_fixed,
        "actions": [
            {
                "index":            i + 1,
                "rule_name":        e.get("rule_name", ""),
                "logic":            e.get("logic", ""),
                "rows_affected":    e.get("rows_affected", 0),
                "failed_ids_count": len(e.get("failed_ids", [])),
                "timestamp":        e.get("timestamp", ""),
            }
            for i, e in enumerate(remediation_log)
        ],
    }

    dataset_col_type_map = _build_dataset_col_type_map(session)

    mapped_dict       = session.get("mapped_dict", {})
    schema_to_dataset = session.get("schema_to_dataset", {})

    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})
        dfs         = session.get("dfs", {})
        tables_info = {}

        for table_name, meta in tables_meta.items():
            cols      = meta.get("columns", [])
            spark_df  = dfs.get(table_name)
            row_count = None
            if spark_df is not None:
                try:
                    row_count = spark_df.count()
                except Exception as e:
                    print(f"⚠️ Could not count rows for {table_name}: {e}")
            tables_info[table_name] = {
                "columns":      cols,
                "column_count": len(cols),
                "row_count":    row_count,
            }

        total_rows = sum(
            v["row_count"] for v in tables_info.values()
            if v["row_count"] is not None
        )

        schema_info: dict = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            table    = _get_table_field(col)
            name     = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            if table and name:
                schema_info.setdefault(table, {})[name] = {
                    "data_type": dtype,
                    "category":  category,
                }
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        schema = {
            "type":                         "multi_table",
            "tables":                       tables_info,
            "total_columns":                sum(len(m.get("columns", [])) for m in tables_meta.values()),
            "table_names":                  list(tables_meta.keys()),
            "total_rows_across_all_tables": total_rows,
            "target_schema":                target_schema,
            "schema_info":                  schema_info,
            "type_counts":                  type_counts,
            "category_counts":              cat_counts,
            "entity_to_schema_col":         mapped_dict,
            "schema_col_to_dataset_col":    schema_to_dataset,
            "dataset_col_type_map":         dataset_col_type_map,
        }

    else:
        columns  = session.get("columns", [])
        spark_df = session.get("df")

        schema_columns    = []
        name_to_type      = {}
        name_to_category  = {}
        type_counts: dict = {}
        cat_counts:  dict = {}

        for col in target_schema:
            col_name = col.get("name")
            dtype    = col.get("type", "string")
            category = col.get("category", "")
            schema_columns.append(col_name)
            name_to_type[col_name]     = dtype
            name_to_category[col_name] = category
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        row_count = None
        if spark_df is not None:
            try:
                row_count = spark_df.count()
            except Exception as e:
                print(f"⚠️ Could not count rows: {e}")

        schema = {
            "type":                       "single_table",
            "columns":                    columns,
            "column_count":               len(columns),
            "row_count":                  row_count,
            "target_schema":              target_schema,
            "schema_columns":             schema_columns,
            "schema_columns_count":       len(schema_columns),
            "schema_columns_to_type":     name_to_type,
            "schema_columns_to_category": name_to_category,
            "type_counts":                type_counts,
            "category_counts":            cat_counts,
            "entity_to_schema_col":       mapped_dict,
            "schema_col_to_dataset_col":  schema_to_dataset,
            "dataset_col_type_map":       dataset_col_type_map,
        }

    return {
        "rules":               rules_list,
        "run_log":             run_log,
        "rule_metrics":        rule_metrics,
        "remediation_summary": remediation_summary,
        "schema":              schema,
        "total_rules":         len(rules_list),
        "executed_count":      len(run_log),
        "code_generated_for":  list(code_cache.keys()),
        "rule_table_map":      session.get("rule_table_map", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_documents_from_session(session: dict) -> List[Document]:
    docs              = []
    target_schema     = session.get("target_schema", [])
    mapped_dict       = session.get("mapped_dict", {})
    schema_to_dataset = session.get("schema_to_dataset", {})

    dataset_col_type_map = _build_dataset_col_type_map(session)

    # ── Dataset schema ────────────────────────────────────────────────────────
    if session.get("is_multi_table"):
        tables_meta = session.get("tables_meta", {})

        schema_lookup: dict = {}
        for col_def in target_schema:
            tbl  = _get_table_field(col_def)
            name = col_def.get("name", "")
            if tbl and name:
                schema_lookup.setdefault(tbl, {})[name] = {
                    "type":     col_def.get("type", "string"),
                    "category": col_def.get("category", ""),
                }

        for table_name, meta in tables_meta.items():
            columns    = meta.get("columns", [])
            tbl_schema = schema_lookup.get(table_name, {})

            raw_col_lines    = [f"  - {col}" for col in columns]
            schema_col_lines = []
            for col in columns:
                info  = tbl_schema.get(col, {})
                dtype = info.get("type")
                cat   = info.get("category", "")
                if dtype:
                    schema_col_lines.append(
                        f"  - {col}  [type: {dtype}"
                        + (f", category: {cat}]" if cat else "]")
                    )

            enriched_lines = []
            for col in columns:
                inferred = dataset_col_type_map.get(col, {})
                if inferred:
                    enriched_lines.append(
                        f"  - {col}  [inferred type: {inferred['type']}, "
                        f"via schema col: {inferred['schema_col']}]"
                    )
                else:
                    enriched_lines.append(
                        f"  - {col}  [type: unknown — not mapped to schema]"
                    )

            by_category: dict = {}
            for col in columns:
                cat = tbl_schema.get(col, {}).get("category", "unknown")
                by_category.setdefault(cat, []).append(col)

            category_summary = "; ".join(
                f"{cat}: {', '.join(cols)}"
                for cat, cols in sorted(by_category.items())
            )

            content = f"""Table: {table_name}
This table is part of a multi-table dataset.

DATASET COLUMNS (raw columns from uploaded file):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(raw_col_lines)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet)'}

TARGET SCHEMA COLUMNS for this table (explicit type from schema JSON):
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded for this table)'}
Columns grouped by category: {category_summary}"""

            docs.append(Document(
                page_content=content,
                metadata={"type": "table_schema", "table": table_name}
            ))

        type_counts:          dict = {}
        cat_counts:           dict = {}
        all_schema_col_lines: list = []
        all_dataset_col_lines: list = []

        for col_def in target_schema:
            tbl      = _get_table_field(col_def)
            col_name = col_def.get("name", "")
            dtype    = col_def.get("type", "string")
            category = col_def.get("category", "")
            label    = f"{tbl}.{col_name}" if tbl else col_name
            all_schema_col_lines.append(
                f"  - {label}  [type: {dtype}, category: {category}]"
            )
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1

        for tbl_name, meta in tables_meta.items():
            for col in meta.get("columns", []):
                all_dataset_col_lines.append(f"  - {tbl_name}.{col}")

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        all_tables = list(tables_meta.keys())
        overview   = f"""Dataset Overview:
Type: Multi-table Excel dataset
Number of tables/sheets: {len(all_tables)}
Table names: {', '.join(all_tables)}

DATASET COLUMNS (raw — no explicit type info):
Total: {sum(len(m['columns']) for m in tables_meta.values())}
{chr(10).join(all_dataset_col_lines) if all_dataset_col_lines else '  (none)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total schema columns: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(all_schema_col_lines) if all_schema_col_lines else '  (no schema loaded)'}

DATASET COLUMN INFERRED TYPES (via schema mapping):
{chr(10).join(f"  - {dc}  [type: {info['type']}, schema_col: {info['schema_col']}]" for dc, info in dataset_col_type_map.items()) if dataset_col_type_map else '  (no mappings yet)'}"""

        docs.append(Document(
            page_content=overview,
            metadata={"type": "dataset_overview"}
        ))

        for tbl_name, meta in tables_meta.items():
            cols = meta.get("columns", [])
            docs.append(Document(
                page_content=(
                    f"Raw dataset columns for table '{tbl_name}' "
                    f"(actual column names in the uploaded Excel — no type info):\n"
                    f"{', '.join(cols)}"
                ),
                metadata={"type": "dataset_columns", "table": tbl_name}
            ))

    else:
        # ── Single table ──────────────────────────────────────────────────────
        columns = session.get("columns", [])

        schema_col_lines = []
        for col_def in target_schema:
            name  = col_def.get("name", "")
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            schema_col_lines.append(
                f"  - {name}  [type: {dtype}"
                + (f", category: {cat}]" if cat else "]")
            )

        enriched_lines = []
        for col in columns:
            inferred = dataset_col_type_map.get(col, {})
            if inferred:
                enriched_lines.append(
                    f"  - {col}  [inferred type: {inferred['type']}, "
                    f"via schema col: {inferred['schema_col']}]"
                )
            else:
                enriched_lines.append(
                    f"  - {col}  [type: unknown — not mapped to schema]"
                )

        type_counts: dict = {}
        cat_counts:  dict = {}
        for col_def in target_schema:
            dtype = col_def.get("type", "string")
            cat   = col_def.get("category", "")
            if dtype:
                type_counts[dtype]   = type_counts.get(dtype, 0) + 1
            if cat:
                cat_counts[cat]      = cat_counts.get(cat, 0) + 1

        type_summary = ", ".join(
            f"{dtype}: {count}" for dtype, count in sorted(type_counts.items())
        )
        cat_summary = ", ".join(
            f"{cat}: {count}" for cat, count in sorted(cat_counts.items())
        )

        content = f"""Dataset Overview:
Type: Single-table dataset

DATASET COLUMNS (raw — no explicit type info):
Number of dataset columns: {len(columns)}
Dataset column names: {', '.join(columns)}
{chr(10).join(f'  - {col}' for col in columns)}

DATASET COLUMNS WITH INFERRED DATA TYPES (via schema mapping):
{chr(10).join(enriched_lines) if enriched_lines else '  (no mappings yet — run /get_mappings first)'}

TARGET SCHEMA COLUMNS (explicit type + category from schema JSON):
Total: {len(target_schema)}
Type breakdown: {type_summary}
Category breakdown: {cat_summary}
{chr(10).join(schema_col_lines) if schema_col_lines else '  (no schema loaded)'}"""

        docs.append(Document(
            page_content=content,
            metadata={"type": "dataset_overview"}
        ))

        chunk_size = 20
        for i in range(0, len(columns), chunk_size):
            chunk = columns[i:i + chunk_size]
            docs.append(Document(
                page_content=(
                    f"DATASET COLUMNS (raw, batch {i//chunk_size + 1}): "
                    f"{', '.join(chunk)}"
                ),
                metadata={"type": "column_list", "batch": i//chunk_size + 1}
            ))

        docs.append(Document(
            page_content=(
                f"Raw dataset columns (no type info):\n{', '.join(columns)}"
            ),
            metadata={"type": "dataset_columns"}
        ))

    # ── Target schema — batched ───────────────────────────────────────────────
    if target_schema:
        batch_size = 15
        for batch_start in range(0, len(target_schema), batch_size):
            batch         = target_schema[batch_start: batch_start + batch_size]
            batch_num     = batch_start // batch_size + 1
            total_batches = (len(target_schema) + batch_size - 1) // batch_size

            lines = [
                f"# Target Schema Reference "
                f"(batch {batch_num}/{total_batches}, "
                f"columns {batch_start+1}–{batch_start+len(batch)} "
                f"of {len(target_schema)} total)\n"
            ]

            by_category: dict = {}
            for col_def in batch:
                cat = col_def.get("category", "other")
                by_category.setdefault(cat, []).append(col_def)

            for category, cols in sorted(by_category.items()):
                lines.append(f"\n## Category: {category.upper()}")
                for col_def in cols:
                    name     = col_def.get("name", "")
                    dtype    = col_def.get("type", "string")
                    table    = _get_table_field(col_def)
                    tbl_part = f"  [table: {table}]" if table else ""
                    lines.append(f"  - {name}  [type: {dtype}]{tbl_part}")

            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":       "target_schema",
                    "batch":      batch_num,
                    "batch_cols": f"{batch_start+1}-{batch_start+len(batch)}",
                }
            ))

        if dataset_col_type_map:
            dtype_lines = [
                "Dataset Column Inferred Data Types "
                "(inferred via schema mapping — schema_to_dataset reverse lookup):",
                "These types are NOT in the raw dataset; "
                "they are inferred by matching dataset columns to schema columns.",
                "",
            ]
            by_type: dict = {}
            for dc, info in dataset_col_type_map.items():
                by_type.setdefault(info["type"], []).append(
                    f"{dc} (via schema col: {info['schema_col']})"
                )
            for dtype, entries in sorted(by_type.items()):
                dtype_lines.append(f"Type '{dtype}':")
                for entry in entries:
                    dtype_lines.append(f"  - {entry}")

            docs.append(Document(
                page_content="\n".join(dtype_lines),
                metadata={"type": "dataset_col_types"}
            ))

    # ── Rules ─────────────────────────────────────────────────────────────────
    rules_df = session.get("rules_df")
    if rules_df is not None:
        rules = rules_df.to_dict(orient="records")
        for i, rule in enumerate(rules):
            entities    = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            entity_mappings_text = {}
            for e in entities:
                schema_col  = mapped_dict.get(e, "not yet mapped")
                dataset_col = schema_to_dataset.get(schema_col, schema_col) if schema_col != "not yet mapped" else "not yet mapped"
                if dataset_col and dataset_col != schema_col:
                    entity_mappings_text[e] = f"{schema_col} (dataset: {dataset_col})"
                else:
                    entity_mappings_text[e] = schema_col

            involved_tables = ""
            rule_table_map  = session.get("rule_table_map", {})
            if rule_table_map.get(rule.get("name", "")):
                involved_tables = (
                    f"\nInvolved tables: "
                    f"{', '.join(rule_table_map[rule['name']])}"
                )

            content = f"""Rule #{i+1}: {rule.get('name', '')}
Description: {rule.get('description', '')}
Business Rule: {rule.get('business_rule', '')}
Category: {rule.get('category', '')}
Complexity: {rule.get('complexity', '')}
Entities extracted: {', '.join(entities)}
Entity to schema column mappings: {json.dumps(entity_mappings_text, indent=2)}
{involved_tables}
Check type: {rule.get('check_type', 'not specified')}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":       "rule",
                    "rule_index": i + 1,
                    "rule_name":  rule.get("name", ""),
                    "category":   rule.get("category", ""),
                    "complexity": rule.get("complexity", ""),
                }
            ))

        categories: dict = {}
        for r in rules:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, []).append(r.get("name", ""))

        summary_lines = [
            "Rules Summary:",
            f"Total rules: {len(rules)}",
            "Rules by category:",
        ]
        for cat, names in categories.items():
            summary_lines.append(f"  {cat} ({len(names)}): {', '.join(names)}")
        summary_lines.append("\nAll rule names in order:")
        for i, r in enumerate(rules):
            summary_lines.append(
                f"  {i+1}. {r.get('name', '')} [{r.get('category','')}]"
            )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "rules_summary"}
        ))

    # ── Execution results ─────────────────────────────────────────────────────
    executed_rules = session.get("executed_rules", set())
    rule_metrics   = session.get("rule_metrics", {})

    if executed_rules and rule_metrics:
        exec_lines = ["Execution Results:"]
        for rule_name in executed_rules:
            result       = session["result"][rule_name]
            passed_count = result.get("passed_count", 0)
            failed_count = result.get("failed_count", 0)
            exec_lines.append(
                f"  {rule_name}: passed={passed_count}, "
                f"failed={failed_count}, "
                f"pass_rate={rule_metrics.get(rule_name)}, "
                f"timestamp: {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
            )
        docs.append(Document(
            page_content="\n".join(exec_lines),
            metadata={"type": "execution_results"}
        ))

    # ── Remediation results ───────────────────────────────────────────────────
    remediation_log = session.get("remediation_log", [])

    if remediation_log:
        for i, entry in enumerate(remediation_log):
            logic         = entry.get("logic", "")
            rows_affected = entry.get("rows_affected", 0)
            failed_ids    = entry.get("failed_ids", [])
            rule_name     = entry.get("rule_name", "not specified")
            timestamp     = entry.get(
                "timestamp",
                datetime.now().strftime('%d %b %Y %H:%M:%S')
            )

            content = f"""Remediation #{i+1}:
Rule: {rule_name}
Logic applied: {logic}
Rows affected / fixed: {rows_affected}
Failed IDs remediated: {len(failed_ids)} records
Timestamp: {timestamp}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":              "remediation_results",
                    "remediation_index": i + 1,
                    "rule_name":         rule_name,
                    "rows_affected":     rows_affected,
                }
            ))

        total_fixed = sum(e.get("rows_affected", 0) for e in remediation_log)
        rem_summary_lines = [
            "Remediation Summary:",
            f"Total remediation actions applied: {len(remediation_log)}",
            f"Total rows fixed across all remediations: {total_fixed}",
            "",
            "Remediation history:",
        ]
        for i, entry in enumerate(remediation_log):
            rem_summary_lines.append(
                f"  #{i+1}: logic='{entry.get('logic','')}', "
                f"rows_fixed={entry.get('rows_affected', 0)}, "
                f"rule='{entry.get('rule_name', 'N/A')}', "
                f"timestamp='{entry.get('timestamp', '')}'"
            )

        docs.append(Document(
            page_content="\n".join(rem_summary_lines),
            metadata={"type": "remediation_summary"}
        ))

    else:
        docs.append(Document(
            page_content=(
                "Remediation Summary:\n"
                "No remediations have been applied yet. "
                "Remediation actions appear here after you fix failed records."
            ),
            metadata={"type": "remediation_summary"}
        ))

    # ── Mapped entities — per rule + full summaries ───────────────────────────
    if mapped_dict and rules_df is not None:
        rules = rules_df.to_dict(orient="records")

        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            rule_entity_schema  = {}
            rule_schema_dataset = {}

            for entity in entities:
                if entity in mapped_dict:
                    schema_col = mapped_dict[entity]
                    rule_entity_schema[entity] = schema_col
                    dataset_col = schema_to_dataset.get(schema_col)
                    if dataset_col and dataset_col != schema_col:
                        rule_schema_dataset[schema_col] = dataset_col

            if not rule_entity_schema:
                continue

            lines = [
                f"Entity-Column Mappings for Rule #{i+1}: {rule_name}",
                f"Rule name: {rule_name}",
                f"Rule number: {i+1}",
                "",
                "Hop 1 — Entity → Schema Column:",
            ]
            for entity, schema_col in rule_entity_schema.items():
                lines.append(f"  Entity '{entity}' → schema column '{schema_col}'")

            if rule_schema_dataset:
                lines.append("")
                lines.append("Hop 2 — Schema Column → Dataset Column:")
                for schema_col, dataset_col in rule_schema_dataset.items():
                    inferred  = dataset_col_type_map.get(dataset_col, {})
                    type_note = (
                        f" [schema type: {inferred['type']}]"
                        if inferred else ""
                    )
                    lines.append(
                        f"  Schema column '{schema_col}' → "
                        f"dataset column '{dataset_col}'{type_note}"
                    )
            else:
                lines.append("")
                lines.append("(Single-hop mapping: schema col == dataset col)")

            # FIX: entity_mappings docs are in no_split_types in build_index
            # so metadata (rule_number etc.) is never lost across chunk boundaries.
            docs.append(Document(
                page_content="\n".join(lines),
                metadata={
                    "type":        "entity_mappings",
                    "rule_name":   rule_name,
                    "rule_number": i + 1,
                }
            ))

        # Full summary: entity → schema_col for all rules
        summary_lines = [
            f"Complete Entity → Schema Column Mappings for ALL {len(rules)} rules:",
        ]
        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            entities  = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            rule_pairs = [
                f"'{e}' → '{mapped_dict[e]}'"
                for e in entities if e in mapped_dict
            ]
            if rule_pairs:
                summary_lines.append(
                    f"  Rule #{i+1} ({rule_name}): {', '.join(rule_pairs)}"
                )

        docs.append(Document(
            page_content="\n".join(summary_lines),
            metadata={"type": "entity_mappings_summary"}
        ))

        # Hop 1 doc
        hop1_lines = [
            "Complete Entity → Target Schema Column Mappings (Hop 1) for ALL rules:"
        ]
        for i, rule in enumerate(rules):
            entities = rule.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            pairs = [
                f"'{e}' → '{mapped_dict[e]}'"
                for e in entities if e in mapped_dict
            ]
            if pairs:
                hop1_lines.append(
                    f"  Rule #{i+1} ({rule.get('name','')}): "
                    f"{', '.join(pairs)}"
                )
        docs.append(Document(
            page_content="\n".join(hop1_lines),
            metadata={"type": "entity_mappings_hop1"}
        ))

        # Hop 2 doc
        non_identity = {k: v for k, v in schema_to_dataset.items() if k != v}
        if non_identity:
            hop2_lines = [
                "Complete Target Schema Column → Dataset Column Mappings (Hop 2):"
            ]
            for schema_col, dataset_col in non_identity.items():
                inferred  = dataset_col_type_map.get(dataset_col, {})
                type_note = (
                    f" [schema type: {inferred['type']}]"
                    if inferred else ""
                )
                hop2_lines.append(
                    f"  Schema column '{schema_col}' → "
                    f"dataset column '{dataset_col}'{type_note}"
                )
            docs.append(Document(
                page_content="\n".join(hop2_lines),
                metadata={"type": "entity_mappings_hop2"}
            ))
        else:
            docs.append(Document(
                page_content=(
                    "Schema Column → Dataset Column Mappings (Hop 2):\n"
                    "Identity mapping — schema column names equal dataset column names. "
                    "No renaming was needed."
                ),
                metadata={"type": "entity_mappings_hop2"}
            ))

    else:
        docs.append(Document(
            page_content=(
                "Entity-Column Mappings: No mappings generated yet. "
                "Please run /get_mappings first."
            ),
            metadata={"type": "entity_mappings"}
        ))
        docs.append(Document(
            page_content=(
                "Complete Entity-Column Mappings for ALL rules: "
                "No mappings generated yet."
            ),
            metadata={"type": "entity_mappings_summary"}
        ))

    # ── Generated code ────────────────────────────────────────────────────────
    code_cache = session.get("code_cache", {})

    if not code_cache:
        docs.append(Document(
            page_content=(
                "Generated Code Summary:\n"
                "No PySpark code has been generated yet for any rule. "
                "Code must be generated before it can be shown."
            ),
            metadata={"type": "generated_code_summary"}
        ))
    else:
        rules_df_local = session.get("rules_df")
        rule_index_map: dict = {}
        if rules_df_local is not None:
            for i, row in enumerate(rules_df_local.to_dict(orient="records")):
                rule_index_map[row.get("name", "")] = i + 1

        for rule_name, cached in code_cache.items():
            pyspark_code = cached.get("pyspark_code", "")
            mc           = cached.get("mapped_dict", {})
            check_type   = cached.get("check_type", "")
            id_column    = cached.get("id_column", "")
            rule_number  = rule_index_map.get(rule_name, "?")

            if not pyspark_code:
                continue

            content = f"""Generated PySpark Code for Rule #{rule_number}: {rule_name}
Rule number: {rule_number}
Rule name: {rule_name}
Also referred to as: rule {rule_number}, rule number {rule_number}, the {rule_number} rule
Check Type: {check_type}
ID Column used: {id_column}
Mapped schema columns used: {json.dumps(mc)}

Code:
{pyspark_code}"""

            docs.append(Document(
                page_content=content,
                metadata={
                    "type":        "generated_code",
                    "rule_name":   rule_name,
                    "rule_number": rule_number,
                    "check_type":  check_type,
                }
            ))

        code_summary_lines = [
            "Generated Code Summary:",
            f"Total rules with generated code: {len(code_cache)}",
            f"Rules with code: {', '.join(code_cache.keys())}",
        ]
        for rule_name, cached in code_cache.items():
            rn = rule_index_map.get(rule_name, "?")
            code_summary_lines.append(
                f"  Rule #{rn} - {rule_name}: "
                f"check_type={cached.get('check_type','')}, "
                f"id_column={cached.get('id_column','')}"
            )
        docs.append(Document(
            page_content="\n".join(code_summary_lines),
            metadata={"type": "generated_code_summary"}
        ))

    return docs


# ─────────────────────────────────────────────────────────────────────────────
# RAG SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
class DQRagSystem:

    def __init__(self):
        http_client = httpx.Client(verify=False)

        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

        self.llm = AzureChatOpenAI(
            azure_endpoint   = AZURE_OPENAI_ENDPOINT,
            api_key          = AZURE_OPENAI_API_KEY,
            api_version      = AZURE_OPENAI_API_VERSION,
            azure_deployment = AZURE_OPENAI_DEPLOYMENT,
            temperature      = 0,
            http_client      = http_client,
        )

        self.vector_store = None
        self._split_docs  = []
        self.all_docs     = []
        self.session_id   = None
        self._build_intent_classifier()
        self._answer_chain = None

    def _build_intent_classifier(self):
        intent_descriptions = "\n".join([
            f'- "{key}": {cfg["description"]}\n'
            f'  Examples: {", ".join(cfg["examples"][:2])}'
            for key, cfg in INTENT_CONFIG.items()
        ])
        self._intent_system = f"""You are a query intent classifier for a Data Quality Engine.

Classify the user's question into EXACTLY ONE of these intents:

{intent_descriptions}

CLASSIFICATION RULES (apply in order, these override everything):
1. If the question asks to LIST, SHOW, GIVE, ENUMERATE, or TELL about schema columns,
   their types, or their categories → always use schema_data_query, NOT schema_query.
2. If the question asks about STRUCTURE OVERVIEW only (which tables exist, general shape,
   dataset overview) with no enumeration of columns → schema_query.
3. If the question asks for ALL mappings, every mapping, mappings across all rules → mapping_query.
4. If the question asks to COUNT or CALCULATE anything → mathematical_query.

Return ONLY the intent key as a single word — no explanation, no punctuation.
Valid responses: {', '.join(INTENT_CONFIG.keys())}"""

    def classify_intent(self, question: str, chat_history: list = None) -> str:
        history_context = ""
        if chat_history:
            recent = chat_history[-4:]
            history_context = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:150]}"
                for m in recent
            ])

        messages = [
            SystemMessage(content=self._intent_system),
            HumanMessage(content=f"Question: {question}{history_context}"),
        ]

        try:
            response = self.llm.invoke(messages)
            intent   = response.content.strip().lower().replace('"','').replace("'","")
            if intent not in INTENT_CONFIG:
                print(f"⚠️ Unknown intent '{intent}', falling back to general")
                intent = "general"

            # ── SAFETY NET: keyword-based override ────────────────────────────
            # Prevents schema_query from intercepting column-listing/enumeration
            # questions even if the LLM misclassifies them.
            q_lower = question.lower()
            enumeration_keywords = [
                "list", "give", "show", "tell", "what are", "give me all",
                "all schema", "all target", "schema columns", "target schema columns",
            ]
            if intent == "schema_query" and any(kw in q_lower for kw in enumeration_keywords):
                print(f"⚠️ Overriding schema_query → schema_data_query for enumeration question")
                intent = "schema_data_query"

            print(f"🎯 Intent: '{question[:60]}' → {intent}")
            return intent
        except Exception as e:
            print(f"⚠️ Intent classification failed: {e}, using general")
            return "general"

    def build_index(self, session: dict, session_id: str) -> int:
        print(f"🔍 Building RAG index for session {session_id}...")

        docs = build_documents_from_session(session)
        self.all_docs   = docs
        self.session_id = session_id

        # FIX: "entity_mappings" added to no_split_types.
        # Per-rule mapping docs were previously chunked at 600 chars, which
        # caused metadata (rule_number, rule_name) to be lost on split
        # boundaries, silently breaking _direct_lookup and ensemble retrieval
        # for specific-rule mapping questions.
        no_split_types = {
            "generated_code",
            "entity_mappings",            # ← NEW
            "entity_mappings_summary",
            "entity_mappings_hop1",
            "entity_mappings_hop2",
            "generated_code_summary",
            "target_schema",
            "dataset_columns",
            "dataset_col_types",
            "remediation_summary",
        }

        text_docs      = [d for d in docs if d.metadata.get("type") not in no_split_types]
        no_split_docs  = [d for d in docs if d.metadata.get("type") in no_split_types]

        text_splitter   = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
        split_text_docs = text_splitter.split_documents(text_docs)

        code_docs      = [d for d in no_split_docs if d.metadata.get("type") == "generated_code"]
        other_no_split = [d for d in no_split_docs if d.metadata.get("type") != "generated_code"]

        code_splitter   = RecursiveCharacterTextSplitter(
            chunk_size=4000, chunk_overlap=0,
            separators=["\ndef ", "\nclass ", "\n\n", "\n"],
        )
        split_code_docs = code_splitter.split_documents(code_docs)

        split_docs = split_text_docs + split_code_docs + other_no_split

        print(f"📄 Indexing {len(split_docs)} chunks from {len(docs)} documents...")
        self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
        self._split_docs  = split_docs
        self._build_answer_chain()
        print(f"✅ RAG index ready — {len(split_docs)} chunks indexed")
        return len(split_docs)

    def update_index(self, session: dict):
        if self.session_id:
            self.build_index(session, self.session_id)

    def _get_filtered_retriever(self, intent: str):
        doc_types = INTENT_CONFIG[intent]["doc_types"]

        if intent == "mapping_query":
            k = 20
        elif intent in ("code_query",):
            k = 8
        elif intent == "schema_query":
            k = 10
        elif intent == "remediation_query":
            k = 6
        else:
            k = 6

        if doc_types is not None:
            filtered = [
                d for d in self._split_docs
                if d.metadata.get("type") in doc_types
            ]
            if not filtered:
                filtered = self._split_docs
        else:
            filtered = self._split_docs

        bm25   = BM25Retriever.from_documents(filtered)
        bm25.k = k

        if doc_types is not None and len(filtered) < len(self._split_docs):
            try:
                faiss_filtered = FAISS.from_documents(filtered, self.embeddings)
                semantic = faiss_filtered.as_retriever(
                    search_type="similarity",
                    search_kwargs={"k": k},
                )
            except Exception:
                semantic = self.vector_store.as_retriever(
                    search_kwargs={"k": k}
                )
        else:
            semantic = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": k},
            )

        return EnsembleRetriever(
            retrievers=[bm25, semantic],
            weights=[0.5, 0.5],
        )

    def _rerank(self, query: str, docs: List[Document], top_n: int = 5) -> List[Document]:
        return docs[:top_n]

    def _direct_lookup(self, intent: str, search_question: str,
                       session_rules: list) -> Optional[List[Document]]:
        q           = search_question.lower()
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        name_to_idx = {v.lower(): k for k, v in idx_to_name.items()}

        rule_num = None
        match = re.search(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b', q, re.IGNORECASE
        )
        if match:
            rule_num = int(match.group(1))
        else:
            for name, idx in name_to_idx.items():
                if name and name in q:
                    rule_num = idx
                    break

        if rule_num is None:
            return None

        target_type = {
            "code_query":        "generated_code",
            "mapping_query":     "entity_mappings",
            "rule_query":        "rule",
            "execution_query":   "execution_results",
            "remediation_query": "remediation_results",
        }.get(intent)

        if target_type is None:
            return None

        matched = [
            d for d in self.all_docs
            if d.metadata.get("type") == target_type
            and d.metadata.get("rule_number") == rule_num
        ]

        if matched:
            print(f"🎯 Direct lookup: rule {rule_num} / {target_type} → {len(matched)} docs")
            return matched
        return None

    def _force_inject_all_mapping_docs(self, question: str) -> Optional[List[Document]]:
        """
        FIX: For broad 'all mappings' questions, bypass retrieval entirely and
        pull the complete pre-built summary documents directly from all_docs.

        RAG retrieval is non-deterministic and lossy for exhaustive enumeration:
        top-k may silently omit some rules. Forced injection from all_docs is
        always complete because these summary docs are built to cover every rule.
        """
        q = question.lower()
        all_mappings_signals = [
            "all", "every", "each", "complete", "across all",
            "for all rules", "all rules", "every rule",
            "full mapping", "all mappings",
        ]
        if not any(sig in q for sig in all_mappings_signals):
            return None

        summary_types = {
            "entity_mappings_summary",
            "entity_mappings_hop1",
            "entity_mappings_hop2",
        }
        forced_docs = [
            d for d in self.all_docs
            if d.metadata.get("type") in summary_types
        ]

        if forced_docs:
            print(f"📌 Force-injecting {len(forced_docs)} mapping summary docs "
                  f"(bypassing retrieval for completeness)")
            return forced_docs

        return None

    def _is_followup_query(self, question: str, chat_history: list) -> bool:
        if not chat_history:
            return False

        q = question.lower().strip()

        code_request_signals = [
            "give code", "show code", "display code",
            "give me code", "show me code", "pyspark code for",
            "generate code for",
        ]
        if any(sig in q for sig in code_request_signals):
            print(f"💻 Code request — standalone: '{question}'")
            return False

        followup_signals = [
            q.startswith("it "), q.startswith("its "),
            q.startswith("that "), q.startswith("this "),
            q.startswith("they "), q.startswith("these "),
            q.startswith("those "), q.startswith("and "),
            q.startswith("but "), q.startswith("so "),
            q.startswith("also "), q.startswith("then "),
            q.startswith("what about "), q.startswith("how about "),
            q.startswith("what if "),
            "the same" in q,
            len(q.split()) <= 4 and bool(chat_history),
            q in ("why?", "how?", "when?", "who?", "which?",
                  "explain.", "elaborate.", "more?"),
            "explain in" in q, "tell me more" in q,
            "give me more" in q, "what does that mean" in q,
            "can you elaborate" in q, "simplify" in q, "in simple" in q,
        ]

        if any(followup_signals):
            print(f"🔗 Follow-up (rule-based): '{question}'")
            return True

        if 4 < len(q.split()) <= 15 and chat_history:
            return self._llm_classify_followup(question, chat_history)
        return False

    def _llm_classify_followup(self, question: str, chat_history: list) -> bool:
        recent = chat_history[-4:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
        ])
        prompt = f"""Conversation so far:
{history_str}

New question: "{question}"

Is this a follow-up or a new independent question?
Answer with exactly one word: yes or no"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            answer   = response.content.strip().lower().replace(".", "")
            is_fu    = answer.startswith("yes")
            print(f"🤖 Follow-up check: '{question}' → {answer}")
            return is_fu
        except Exception as e:
            print(f"⚠️ Follow-up check failed: {e}")
            return False

    def _rewrite_query(self, question: str, chat_history: list) -> str:
        recent = chat_history[-6:]
        history_str = "\n".join([
            f"{m['role'].upper()}: {m['content'][:300]}" for m in recent
        ])
        prompt = f"""Rewrite this follow-up into a complete standalone question.

Conversation:
{history_str}

Follow-up: "{question}"

Rewritten (return ONLY the question):"""

        try:
            response  = self.llm.invoke([HumanMessage(content=prompt)])
            rewritten = response.content.strip().strip('"').strip("'")
            if rewritten and rewritten != question:
                print(f"✏️  Rewritten: '{question}' → '{rewritten}'")
                return rewritten
            return question
        except Exception as e:
            print(f"⚠️ Rewrite failed: {e}")
            return question

    def _resolve_rule_references(self, question: str,
                                  session_rules: list) -> str:
        ordinals = {
            "first": 1, "second": 2, "third": 3, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10,
        }
        idx_to_name = {i+1: r.get("name","") for i, r in enumerate(session_rules)}
        resolved    = question

        def replace_numbered(match):
            num  = int(match.group(1))
            name = idx_to_name.get(num, "")
            return f"rule {num} ({name})" if name else match.group(0)

        resolved = re.sub(
            r'\brule\s+(?:#\s*|no\.?\s*|number\s*)?(\d+)\b',
            replace_numbered, resolved, flags=re.IGNORECASE
        )

        def replace_ordinal(match):
            word = match.group(1).lower()
            num  = ordinals.get(word)
            if num:
                name = idx_to_name.get(num, "")
                if name:
                    return f"rule {num} ({name})"
            return match.group(0)

        resolved = re.sub(
            r'\b(' + '|'.join(ordinals.keys()) + r')\s+rule\b',
            replace_ordinal, resolved, flags=re.IGNORECASE
        )

        if resolved != question:
            print(f"🔄 Resolved: '{question}' → '{resolved}'")
        return resolved

    def _generate_compute_code(self, question: str,
                                snapshot: dict,
                                chat_history: list = None) -> str:
        history_ctx = ""
        if chat_history:
            recent = chat_history[-4:]
            history_ctx = "\nRecent conversation:\n" + "\n".join(
                f"{m['role'].upper()}: {m['content'][:150]}" for m in recent
            )

        schema_preview = {
            "rules":               snapshot["rules"],         #f"{len(snapshot['rules'])} rules",
            "run_log":             snapshot["run_log"],       #f"{len(snapshot['run_log'])} executed",
            "rule_metrics":        snapshot["rule_metrics"],  #f"{len(snapshot['rule_metrics'])} entries",
            "remediation_summary": snapshot.get("remediation_summary", {}),
            "schema":              snapshot["schema"],
            "total_rules":         snapshot["total_rules"],
            "executed_count":      snapshot["executed_count"],
            "code_generated_for":  snapshot["code_generated_for"],
        }

        system_prompt = f"""You are a Python code generator for a Data Quality Engine.

Write a function `compute(data)` that answers the user's question.

`data` structure:
{json.dumps(schema_preview, indent=2, default=str)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY DATA PATHS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCHEMA — target_schema is ALWAYS complete (all columns, untruncated):
  data['schema']['target_schema']
    → list of dicts: [{{"name","type","category"[,"table"]}}]

DATASET COL INFERRED TYPES (via schema mapping):
  data['schema']['dataset_col_type_map']
    → {{dataset_col: {{"type","category","schema_col"}}}}
    → Use when user asks data type of a DATASET column (e.g. "acct_number")
    → If col not in map: it hasn't been mapped to a schema col yet

MAPPING MODEL:
  data['schema']['entity_to_schema_col']      → {{entity: schema_col}}
  data['schema']['schema_col_to_dataset_col'] → {{schema_col: dataset_col}}
  NOTE: mapped_dict = entity → schema_col (NOT dataset_col directly)
        To get dataset_col for an entity:
          schema_col  = entity_to_schema_col[entity]
          dataset_col = schema_col_to_dataset_col.get(schema_col, schema_col)

MULTI-TABLE:
  data['schema']['schema_info']       → {{table: {{col: {{data_type, category}}}}}}
  data['schema']['type_counts']       → {{dtype: count}}
  data['schema']['category_counts']   → {{category: count}}
  data['schema']['tables']            → {{table: {{columns, column_count, row_count}}}}

SINGLE-TABLE:
  data['schema']['schema_columns_to_type']     → {{col: dtype}}
  data['schema']['schema_columns_to_category'] → {{col: category}}
  data['schema']['type_counts']                → {{dtype: count}}
  data['schema']['category_counts']            → {{category: count}}

EXECUTION:
  data['run_log']       → [{{rule_name, passed_count, failed_count, pass_rate, timestamp}}]
  data['rule_metrics']  → {{rule_name: pass_rate}}
  data['code_generated_for'] → [rule_name, ...]

RULE → TABLE MAPPING:
  data['rule_table_map']
    → {{rule_name: [table_name, ...]}}
    → Use to find which tables a rule involves, or which rules involve a table
    → Example: {{"Rule A": ["Payments", "Customers"], "Rule B": ["Orders"]}}

RULES LIST (full, always complete):
  data['rules']
    → list of dicts: [{{name, description, business_rule, category,
                       complexity, entities, check_type}}]
    → Use for any question about rule properties, filtering rules,
      or listing rules matching a condition

REMEDIATION:
  data['remediation_summary']['total_actions']    → int
  data['remediation_summary']['total_rows_fixed'] → int
  data['remediation_summary']['actions']          → list of dicts:
    each: {{index, rule_name, logic, rows_affected, failed_ids_count, timestamp}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"give me all schema columns":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    if not cols:
        return "No schema loaded"
    return [c.get('name') for c in cols]

"tell me data types of all schema columns":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    if not cols:
        return "No schema loaded"
    return {{col.get('name'): col.get('type','unknown') for col in cols}}

"give columns whose data type is string":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('type','').lower() == 'string']

"give columns in the financial category":
def compute(data):
    cols = data['schema'].get('target_schema', [])
    return [c.get('name') for c in cols if c.get('category','').lower() == 'financial']

"what is the data type of acct_number":
def compute(data):
    m    = data['schema'].get('dataset_col_type_map', {{}})
    info = m.get('acct_number')
    if info:
        return (f"acct_number → inferred type '{{info['type']}}' "
                f"via schema column '{{info['schema_col']}}'")
    cols = data['schema'].get('target_schema', [])
    for c in cols:
        if c.get('name','').lower() == 'acct_number':
            return f"acct_number is a schema column with type '{{c.get('type')}}'"
    return ("acct_number has not been mapped to a schema column yet. "
            "Run /get_mappings first.")

"what entity maps to schema column net_return_value":
def compute(data):
    e2s = data['schema'].get('entity_to_schema_col', {{}})
    return {{e: s for e, s in e2s.items() if s == 'net_return_value'}} or "Not found"

"what dataset column does entity X map to":
def compute(data):
    e2s = data['schema'].get('entity_to_schema_col', {{}})
    s2d = data['schema'].get('schema_col_to_dataset_col', {{}})
    schema_col  = e2s.get('X')
    if not schema_col:
        return "Entity X not in mappings"
    dataset_col = s2d.get(schema_col, schema_col)
    return f"Entity 'X' → schema col '{{schema_col}}' → dataset col '{{dataset_col}}'"

"how many rows were remediated":
def compute(data):
    return data.get('remediation_summary', {{}}).get('total_rows_fixed', 0)

"show remediation history":
def compute(data):
    actions = data.get('remediation_summary', {{}}).get('actions', [])
    if not actions:
        return "No remediations applied yet"
    return actions

"which dataset columns have inferred types":
def compute(data):
    m = data['schema'].get('dataset_col_type_map', {{}})
    if not m:
        return "No mappings yet — run /get_mappings first"
    return {{dc: info['type'] for dc, info in m.items()}}

"list all schema columns grouped by category":
def compute(data):
    cols   = data['schema'].get('target_schema', [])
    result = {{}}
    for c in cols:
        cat = c.get('category', 'unknown')
        result.setdefault(cat, []).append(c.get('name'))
    return result

"what are the schema columns in the Orders table":
def compute(data):
    table_name  = 'Orders'
    schema_cols = data['schema'].get('target_schema', [])
    by_table = [
        c for c in schema_cols
        if (c.get('table') or c.get('table_name') or '') == table_name
    ]
    if not by_table:
        schema_info = data['schema'].get('schema_info', {{}})
        table_info  = schema_info.get(table_name, {{}})
        return [
            {{'name': col, 'type': info.get('data_type','unknown'),
             'category': info.get('category','')}}
            for col, info in table_info.items()
        ] or f"No schema columns found for table '{{table_name}}'"
    return [
        {{'name': c.get('name'), 'type': c.get('type'), 'category': c.get('category')}}
        for c in by_table
    ]

"how many rules involve the Payments table":
def compute(data):
    rtm = data.get('rule_table_map', {{}})
    target = 'Payments'
    matching = [
        rule_name for rule_name, tables in rtm.items()
        if any(t.lower() == target.lower() for t in tables)
    ]
    return len(matching)

"give me rules that involve the Customers table":
def compute(data):
    rtm = data.get('rule_table_map', {{}})
    target = 'Customers'
    matching = [
        rule_name for rule_name, tables in rtm.items()
        if any(t.lower() == target.lower() for t in tables)
    ]
    if not matching:
        return f"No rules found involving the '{{target}}' table"
    return matching

"which tables does rule 3 involve":
def compute(data):
    rules = data.get('rules', [])
    if not rules or len(rules) < 3:
        return "Rule 3 not found"
    rule_name = rules[2].get('name', '')
    rtm = data.get('rule_table_map', {{}})
    tables = rtm.get(rule_name, [])
    return tables or f"No table mapping found for '{{rule_name}}'"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Function named `compute(data)` only
2. Return: string, list, dict, int, or float — no DataFrames
3. Handle missing keys and empty lists gracefully
4. NO import statements — pre-injected globals available:
   datetime, date, timedelta, math, re, json, Counter, defaultdict, dateutil_parser
5. Return ONLY the function — no markdown, no backticks

{history_ctx}"""

        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Question: {question}"),
        ])

        code = response.content.strip()
        code = code.replace("```python", "").replace("```", "").strip()
        return code

    def _execute_compute_code(self, code: str, snapshot: dict) -> tuple:
        import math
        import re as re_module
        import json as json_module
        from datetime import datetime, date, timedelta
        from collections import Counter, defaultdict

        try:
            from dateutil import parser as dateutil_parser
        except ImportError:
            dateutil_parser = None

        allowed_globals = {
            "__builtins__": {
                "len": len, "range": range, "enumerate": enumerate,
                "zip": zip, "map": map, "filter": filter,
                "sorted": sorted, "reversed": reversed,
                "min": min, "max": max, "sum": sum, "abs": abs,
                "round": round, "int": int, "float": float,
                "str": str, "bool": bool, "list": list,
                "dict": dict, "set": set, "tuple": tuple,
                "isinstance": isinstance, "any": any, "all": all,
                "print": print, "type": type,
                "hasattr": hasattr, "getattr": getattr,
                "None": None, "True": True, "False": False,
            },
            "datetime": datetime, "date": date, "timedelta": timedelta,
            "math": math, "json": json_module, "re": re_module,
            "Counter": Counter, "defaultdict": defaultdict,
            "dateutil_parser": dateutil_parser,
        }

        local_vars = {}
        try:
            exec(code, allowed_globals, local_vars)
            compute_fn = local_vars.get("compute")
            if compute_fn is None:
                return None, "Generated code did not define a `compute` function"
            result = compute_fn(snapshot)
            return result, None
        except Exception as e:
            return None, f"Execution error: {str(e)}\n\nCode:\n{code}"

    def _compute_to_answer(self, question: str, result,
                            code: str, error: str = None) -> str:
        if error:
            return (
                f"I understood your question but had trouble computing the answer. "
                f"Error: {error}"
            )

        prompt = f"""The user asked: "{question}"

Python function returned:
{json.dumps(result, indent=2, default=str)}

Write a clear, concise natural-language answer.
- Include actual values (names, types, numbers) from the result
- Use bullet points if result is a list/dict with more than 3 items
- Do not mention Python, functions, or the technical process
- Keep under 400 words (longer if listing many columns)
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _run_compute_pipeline(self, question: str,
                               session: dict,
                               chat_history: list = None) -> dict:
        snapshot = build_structured_snapshot(session)
        print(f"🧮 Compute: '{question[:60]}'")

        code = self._generate_compute_code(question, snapshot, chat_history)
        print(f"📝 Code:\n{code}\n")

        result, error = self._execute_compute_code(code, snapshot)
        print(f"⚙️  Result: {str(result)[:100]}, error: {error}")

        if error and "Execution error" in error:
            print("🔄 Retrying...")
            retry_code = self._generate_compute_code(
                f"{question}\n\nPrevious attempt failed: {error}",
                snapshot, chat_history
            )
            result, error = self._execute_compute_code(retry_code, snapshot)
            code = retry_code

        answer = self._compute_to_answer(question, result, code, error)

        return {
            "answer":       answer,
            "intent":       "compute",
            "compute_code": code,
            "raw_result":   result,
            "sources":      [{"type": "structured_compute",
                              "snippet": str(result)[:100]}],
        }

    def _build_answer_chain(self):
        self._answer_prompt = ChatPromptTemplate.from_template("""
You are a Data Quality Engine assistant. Answer ONLY from the context below.

IMPORTANT DISTINCTIONS:
- "DATASET COLUMNS" = raw column names from the uploaded file. No explicit type info.
- "TARGET SCHEMA COLUMNS" = columns from the schema JSON with explicit data type and category.
- "INFERRED DATASET COLUMN TYPES" = types inferred by matching dataset cols to schema cols via mappings.
- If user asks data type of a dataset column, look under "DATASET COLUMNS WITH INFERRED DATA TYPES".
- If not found there, say the column hasn't been mapped to a schema column yet.
- "REMEDIATION" = actions taken to fix failed records after rule execution.
- MAPPING MODEL: entity → schema_col (Hop 1), schema_col → dataset_col (Hop 2).
  The generated PySpark code uses SCHEMA column names (not dataset column names).
  Dataset columns are renamed to schema names before code runs.

If the answer is not in the context:
"I don't have that information in the current session."

Rules:
- CODE: return COMPLETE code, never truncate
- Rules: numbered lists (#1, #2 etc.)
- Columns: bullet points
- Keep under 300 words unless listing many items requires more

Context:
{context}

Question: {question}

Answer:""")

    @staticmethod
    def _format_docs(docs: List[Document]) -> str:
        if not docs:
            return "No relevant documents found."
        return "\n\n---\n\n".join(d.page_content for d in docs)

    def query(self, question: str, chat_history: list = None,
              session: dict = None) -> dict:
        if self.vector_store is None:
            return {
                "answer":  "RAG index not built yet. Please upload your dataset first.",
                "intent":  "unknown",
                "sources": [],
            }

        effective_question = question

        if chat_history:
            if self._is_followup_query(question, chat_history):
                effective_question = self._rewrite_query(question, chat_history)
            else:
                print(f"🆕 Standalone: '{question}'")
        else:
            print("No chat history")

        intent     = self.classify_intent(effective_question, chat_history)
        is_compute = INTENT_CONFIG.get(intent, {}).get("compute", False)

        if is_compute:
            if session is None:
                return {
                    "answer":  "Session data is required for this query.",
                    "intent":  intent,
                    "sources": [],
                }
            return self._run_compute_pipeline(
                effective_question, session, chat_history
            )

        doc_types       = INTENT_CONFIG[intent]["doc_types"]
        search_question = effective_question
        session_rules   = []

        if session is not None:
            rules_df = session.get("rules_df")
            if rules_df is not None:
                session_rules   = rules_df.to_dict(orient="records")
                search_question = self._resolve_rule_references(
                    effective_question, session_rules
                )

        # ── Mapping query: force-inject summary docs for broad questions ──────
        # FIX: Bypasses retrieval entirely for "all mappings" style questions,
        # guaranteeing completeness. Top-k retrieval is non-deterministic and
        # can silently omit rules when there are many mapping documents.
        direct_docs = None
        if intent == "mapping_query":
            direct_docs = self._force_inject_all_mapping_docs(search_question)

        # ── Specific rule lookup by number/name ───────────────────────────────
        if direct_docs is None:
            direct_docs = self._direct_lookup(intent, search_question, session_rules)

        if direct_docs:
            retrieved_docs = direct_docs
            print(f"⚡ Direct/forced lookup: {len(retrieved_docs)} docs")
        else:
            retriever = self._get_filtered_retriever(intent)
            try:
                retrieved_docs = retriever.invoke(search_question)
            except Exception as e:
                print(f"⚠️ Retrieval failed ({e}), falling back")
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            if not retrieved_docs:
                retrieved_docs = self.vector_store.as_retriever(
                    search_kwargs={"k": 5}
                ).invoke(search_question)

            retrieved_docs = self._rerank(search_question, retrieved_docs, top_n=5)

        if intent == "code_query":
            summary_in = any(
                d.metadata.get("type") == "generated_code_summary"
                for d in retrieved_docs
            )
            if not summary_in:
                for doc in self.all_docs:
                    if doc.metadata.get("type") == "generated_code_summary":
                        retrieved_docs = [doc] + list(retrieved_docs)
                        break

            summary_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code_summary"
            ]
            no_code = any(
                "no pyspark code has been generated yet" in d.page_content.lower()
                for d in summary_docs
            )

            if no_code:
                return {
                    "answer": (
                        "No code has been generated yet. "
                        "Please generate code for the rule first."
                    ),
                    "intent":    intent,
                    "doc_types": doc_types,
                    "sources":   [],
                }

            code_docs = [
                d for d in retrieved_docs
                if d.metadata.get("type") == "generated_code"
            ]
            if code_docs:
                retrieved_docs = code_docs + summary_docs

        context = self._format_docs(retrieved_docs)

        history_text = ""
        if chat_history:
            recent = chat_history[-4:]
            history_text = "\n\nRecent conversation:\n" + "\n".join([
                f"{m['role'].upper()}: {m['content'][:200]}"
                for m in recent
            ])

        full_prompt = self._answer_prompt.format_messages(
            context  = context + history_text,
            question = question,
        )

        try:
            answer = self.llm.invoke(full_prompt).content
        except Exception as e:
            answer = f"Failed to generate answer: {str(e)}"

        sources = []
        seen    = set()
        for doc in retrieved_docs:
            key = (doc.metadata.get("rule_name") or
                   doc.metadata.get("table") or
                   doc.metadata.get("type"))
            if key and key not in seen:
                seen.add(key)
                sources.append({
                    "type":        doc.metadata.get("type"),
                    "rule_name":   doc.metadata.get("rule_name"),
                    "rule_number": doc.metadata.get("rule_number"),
                    "table":       doc.metadata.get("table"),
                    "snippet":     doc.page_content[:100] + "…",
                })

        print(f"✅ Answered — intent={intent}, "
              f"sources={[s['type'] for s in sources]}")

        return {
            "answer":          answer,
            "intent":          intent,
            "doc_types":       doc_types,
            "sources":         sources,
            "rewritten_query": (
                effective_question if effective_question != question else None
            ),
        }

    def is_ready(self) -> bool:
        return self.vector_store is not None


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped RAG store
# ─────────────────────────────────────────────────────────────────────────────
RAG_STORE: dict = {}

def get_or_create_rag(session_id: str) -> DQRagSystem:
    if session_id not in RAG_STORE:
        RAG_STORE[session_id] = DQRagSystem()
    return RAG_STORE[session_id]