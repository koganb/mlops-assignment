"""Schema-rendering helper (provided complete).

Loads the schema directly from sqlite and renders quoted CREATE TABLE
text suitable for prompt context. Identifiers are always double-quoted
so reserved-word table/column names (e.g. `order`) don't break either
the PRAGMA introspection here or the SQL the model emits later.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, field_validator

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "data" / "bird"


def db_path(db_id: str) -> Path:
    return DB_DIR / f"{db_id}.sqlite"


def _q(ident: str) -> str:
    """Double-quote a SQL identifier, escaping any embedded quotes."""
    return '"' + ident.replace('"', '""') + '"' if ident else ""


@lru_cache(maxsize=32)
def render_schema(db_id: str) -> str:
    path = db_path(db_id)
    if not path.exists():
        raise FileNotFoundError(f"DB {db_id} not found at {path}. Did you run scripts/load_data.py?")

    parts: list[str] = [f"-- Database: {db_id}"]
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        for t in tables:
            parts.append(f"\nCREATE TABLE {_q(t)} (")
            col_lines: list[str] = []
            for _cid, name, ctype, notnull, _dflt, pk in conn.execute(f"PRAGMA table_info({_q(t)})"):
                line = f"  {_q(name)} {ctype}"
                if pk:
                    line += " PRIMARY KEY"
                if notnull and not pk:
                    line += " NOT NULL"
                col_lines.append(line)
            for fk in conn.execute(f"PRAGMA foreign_key_list({_q(t)})"):
                # (id, seq, ref_table, from, to, on_update, on_delete, match)
                col_lines.append(
                    f"  FOREIGN KEY ({_q(fk[3])}) REFERENCES {_q(fk[2])}({_q(fk[4])})"
                )
            parts.append(",\n".join(col_lines))
            parts.append(");")
    return "\n".join(parts)

class ColumnDescription(BaseModel):
    name: str
    column_description: Any | None = None
    data_format:  Any | None = None
    value_description: Any | None = None

    @field_validator("name", "column_description", "data_format", "value_description", mode="before")
    @classmethod
    def trim_strings(cls, value):
        return value.strip() if isinstance(value, str) else None


@lru_cache(maxsize=32)
def attach_schema_description(db_id: str) -> str:
    db_descriptions = {}
    for csv_file in DB_DIR.glob(f"dev_*/dev_databases/{db_id}/database_description/*.csv"):
        table_name = csv_file.stem
        df = pd.read_csv(csv_file, encoding='utf-8', encoding_errors='ignore')
        db_descriptions[table_name] = [
            ColumnDescription(
                name=row.original_column_name,
                column_description=row.column_description,
                data_format=row.data_format,
                value_description=row.value_description,
            ).model_dump()
            for row in df.itertuples(index=False)
        ]
    return json.dumps(db_descriptions, indent=2)


def available_dbs() -> list[str]:
    if not DB_DIR.exists():
        return []
    return sorted(p.stem for p in DB_DIR.glob("*.sqlite"))
