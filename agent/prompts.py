"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are yours to
design alongside their nodes - pick whatever placeholders your nodes pass in.

Filling these in is part of Phase 3.
"""

GENERATE_SQL_SYSTEM = """You are an expert SQL engineer. Given a database schema and a natural language question, your task is to write a SQLite query that answers the question.
Your output must contain only the SQL query inside a single ```sql ... ``` code block. Do not write explanation prose.
Make sure you use exact table and column names as defined in the schema."""

# Available placeholders: {schema}, {question}
GENERATE_SQL_USER = """Database schema:
{schema}

Question: {question}

Write the SQLite query. Remember to wrap the SQL query in a ```sql ... ``` block."""


VERIFY_SYSTEM = """You are a database quality assurance assistant. Your task is to evaluate if a generated SQLite query and its execution result plausibly and correctly answer a user's question, given the database schema.

Analyze carefully:
1. Did the SQL execution result in an error? If so, verify is NOT ok.
2. Did the SQL return 0 rows? If the question implies that data should exist (e.g., asking for specific counts, names, averages, etc.), then 0 rows might be an issue.
3. Do the returned column names and types align with what the question asks? (e.g., if the question asks for coordinates, does the result have lat/lng columns or values? If it asks for names, does it return names?)
4. Is there a logic error in the query based on the schema and question? (e.g. joined wrong tables, filtered by wrong criteria).

You must respond with a JSON object ONLY, containing two keys:
- "ok": a boolean (true if the query is correct and the result is plausible; false otherwise)
- "issue": a string describing the error or issue if "ok" is false, or an empty string "" if "ok" is true.

Do not write any introductory or concluding text. Output only the raw JSON."""

VERIFY_USER = """Database Schema:
{schema}

User Question: {question}

Generated SQL:
{sql}

Execution Result:
{execution_result}

Evaluate the query and output your response as JSON."""


REVISE_SYSTEM = """You are an expert SQL debugger. You will be provided with a database schema, a user question, a previously generated SQL query that was incorrect or failed, its execution result, and the specific issue identified by the verifier.
Your task is to fix the SQL query to correctly answer the user's question.
Your output must contain only the corrected SQLite query inside a single ```sql ... ``` code block. Do not write any explanation prose."""

REVISE_USER = """Database Schema:
{schema}

User Question: {question}

Previous SQL Query:
{sql}

Execution Result:
{execution_result}

Verifier Issue Report:
{issue}

Please provide the corrected SQLite query inside a ```sql ... ``` block."""
