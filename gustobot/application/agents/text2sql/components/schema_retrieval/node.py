"""Read SQL schema metadata from the explicitly configured database."""

import asyncio
from typing import Any, Callable, Coroutine

from sqlalchemy import create_engine, inspect


def create_schema_retrieval_node(
    connection_string: str,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]:
    if not connection_string.strip():
        raise ValueError("SQL connection_string must be configured")

    async def retrieve_schema(state: dict[str, Any]) -> dict[str, Any]:
        schema_context = await asyncio.to_thread(_retrieve_schema, connection_string)
        return {
            "schema_context": schema_context,
            "value_mappings": {},
            "mappings_str": "",
            "steps": ["schema_retrieval"],
        }

    return retrieve_schema


def _retrieve_schema(connection_string: str) -> dict[str, Any]:
    engine = create_engine(connection_string, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = []
            relationships = []
            for table_name in inspector.get_table_names():
                primary_keys = set(inspector.get_pk_constraint(table_name)["constrained_columns"])
                unique_columns = {
                    column
                    for constraint in inspector.get_unique_constraints(table_name)
                    for column in constraint["column_names"]
                    if len(constraint["column_names"]) == 1
                }
                foreign_keys = inspector.get_foreign_keys(table_name)
                foreign_columns = {
                    column for key in foreign_keys for column in key["constrained_columns"]
                }
                try:
                    description = inspector.get_table_comment(table_name).get("text")
                except NotImplementedError:
                    description = None
                columns = [
                    {
                        "column_name": column["name"],
                        "data_type": str(column["type"]),
                        "description": column.get("comment", ""),
                        "is_primary_key": column["name"] in primary_keys,
                        "is_foreign_key": column["name"] in foreign_columns,
                        "is_unique": column["name"] in unique_columns,
                    }
                    for column in inspector.get_columns(table_name)
                ]
                tables.append(
                    {"table_name": table_name, "description": description, "columns": columns}
                )
                for key in foreign_keys:
                    for source, target in zip(key["constrained_columns"], key["referred_columns"]):
                        relationships.append(
                            {
                                "source_table": table_name,
                                "source_column": source,
                                "target_table": key["referred_table"],
                                "target_column": target,
                                "relationship_type": "FOREIGN_KEY",
                                "description": "Database foreign key",
                            }
                        )
            return {"tables": tables, "relationships": relationships}
    finally:
        engine.dispose()
