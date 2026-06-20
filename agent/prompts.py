"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are yours to
design alongside their nodes - pick whatever placeholders your nodes pass in.

Filling these in is part of Phase 3.
"""

GENERATE_SQL_SYSTEM = """You are an expert SQL assistant. 
Your task is to convert English questions into SQL queries for a SQLite database.
Use the provided schema to understand the tables and columns relations.
Use the provided schema description for column metadata.
Return ONLY the SQL query, wrapped in ```sql ... ``` markdown fences.

Rules:
1. For all date/time filtering conditions, never use direct equality comparisons (=, !=) on timestamps or datetime values because they can fail due to precision differences (milliseconds, microseconds, timezone conversions, database storage precision).
   Always express date/time conditions as inclusive/exclusive ranges:
   column >= start_time AND column < end_time
2. When generating SQL, always remove duplicate result rows
3. Do not return additional columns that are not part of the question.
4. Do not change columns order in the result.
5. Limit the results number only if EXPLICITLY requested.

"""

# Available placeholders: {schema}, {schema_description}, {question}
GENERATE_SQL_USER = """Schema:
{schema_description}

Question: {question}

SQL:"""


VERIFY_SYSTEM = """You are a SQL validator.
Your task is to decide whether a given SQL query and its execution results plausibly answer a user's question.
Analyze if:
1. The SQL query correctly reflects the question's logic.
2. The execution results are not an error.
3. The results are not empty if the question implies data should exist (e.g., if asking for a specific count or name).
4. The columns returned are relevant to the question.
"""

VERIFY_USER = """Question: {question}
SQL: {sql}
Execution Result:
{execution_render}

Is this result plausible?"""


REVISE_SYSTEM = """You are an expert SQL assistant.
The previous SQL query failed or produced incorrect results. 
Your task is to revise the SQL query based on the issue reported.
"""

REVISE_USER = """Schema:
{schema_description}

Question: {question}

Previous SQL: {sql}
Execution Result: {execution_render}
Issue Reported: {issue}

Please provide a fixed SQL query.
SQL:"""
