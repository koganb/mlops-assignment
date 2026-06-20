"""Schema-rendering helper (provided complete).

Loads the schema directly from sqlite and renders quoted CREATE TABLE
text suitable for prompt context. Identifiers are always double-quoted
so reserved-word table/column names (e.g. `order`) don't break either
the PRAGMA introspection here or the SQL the model emits later.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "data" / "bird"


def db_path(db_id: str) -> Path:
    return DB_DIR / f"{db_id}.sqlite"


def _q(ident: str) -> str:
    """Double-quote a SQL identifier, escaping any embedded quotes."""
    return '"' + ident.replace('"', '""') + '"' if ident else ""


@lru_cache(maxsize=32)
def attach_schema_description(db_id: str) -> str:
    # Build FK map: {table -> {from_col -> "ref_table(ref_col)"}}
    fk_map: dict[str, dict[str, str]] = {}
    path = db_path(db_id)
    if path.exists():
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for t in tables:
                for fk in conn.execute(f"PRAGMA foreign_key_list({_q(t)})"):
                    # (id, seq, ref_table, from, to, ...)
                    fk_map.setdefault(t, {})[fk[3]] = f"{fk[2]}({fk[4]})"

    df_list = []
    for csv_file in DB_DIR.glob(f"dev_*/dev_databases/{db_id}/database_description/*.csv"):
        table_name = csv_file.stem
        df = (
            pd.read_csv(csv_file, encoding='utf-8', encoding_errors='ignore')
            .assign(table_name=table_name)
            [['table_name', 'original_column_name', 'column_description', 'data_format', 'value_description']]
            .rename(columns={'original_column_name': 'column_name'})
        )
        df_list.append(df)

    result = pd.concat(df_list, axis=0).fillna("")

    # Append FK->PK info to column_description
    def _enrich(row: pd.Series) -> str:
        desc = row['column_description']
        fk_ref = fk_map.get(str(row['table_name']), {}).get(str(row['column_name']))
        if fk_ref:
            suffix = f"FK -> {fk_ref}"
            desc = f"{desc}; {suffix}" if desc else suffix
        return desc

    result['column_description'] = result.apply(_enrich, axis=1)
    return result.to_markdown(index=False)


def available_dbs() -> list[str]:
    if not DB_DIR.exists():
        return []
    return sorted(p.stem for p in DB_DIR.glob("*.sqlite"))
