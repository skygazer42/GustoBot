from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ExcelIngestRequest(BaseModel):
    excel_path: str = Field(..., description="Path to the Excel file that needs processing.")
    regenerate: bool = Field(
        default=False,
        description="Force regeneration even if previous outputs exist.",
    )
    incremental: bool = Field(
        default=False,
        description="Enable incremental mode: only process changed rows based on content hash.",
    )


class MySQLIngestRequest(BaseModel):
    connection_url: str = Field(..., description="SQLAlchemy style MySQL connection URL.")
    table: str = Field(..., description="Table name to read from.")
    where: Optional[str] = Field(
        None,
        description="Optional scalar WHERE filter; literals are bound parameters. "
        "Statements, subqueries and functions with side effects are rejected.",
    )
    limit: Optional[int] = Field(None, ge=1, description="Maximum number of rows to ingest.")
    prompt_key: Optional[str] = Field(
        None, description="Optional prompt template key if not inferred from the table name."
    )
    extra_metadata: Dict[str, Any] = Field(description="Static metadata to persist.")
    mode: Literal["rewrite", "flatten"] = Field(
        default="rewrite", description="Rewrite with LLM or directly flatten the row for embedding."
    )
    prompt_template: Optional[str] = Field(
        default=None,
        description="Override user prompt template (string.Template syntax).",
    )
    id_column: Optional[str] = Field(
        default=None,
        description="Column to use as unique identifier; defaults to row index if omitted.",
    )
    company_field: Optional[str] = Field(
        default=None, description="Field containing company name (optional)."
    )
    report_year_field: Optional[str] = Field(
        default=None, description="Field containing report year (optional)."
    )
    chunk_size: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Number of records to process per batch; " "defaults to processing all rows at once."
        ),
    )
