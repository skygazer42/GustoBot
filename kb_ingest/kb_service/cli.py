import argparse
from contextlib import closing
import json
import logging
from typing import Optional

from kb_service.core.config import load_config
from kb_service.schemas.ingest import MySQLIngestRequest
from kb_service.services.mysql_ingest import MySQLIngestor
from kb_service.services.processor import DataProcessor
from kb_service.services.search import VectorSearcher


def process_excel(excel_path: str) -> None:
    config = load_config()
    config.excel_file_path = excel_path
    with closing(DataProcessor(config)) as processor:
        processor.process_excel()


def run_search(query: str, top_k: int, threshold: Optional[float], metric: str) -> None:
    config = load_config()
    with closing(VectorSearcher(config)) as searcher:
        results = searcher.search_similar(
            query=query, top_k=top_k, threshold=threshold, metric=metric
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


def ingest_mysql(
    connection_url: str,
    table: str,
    where: Optional[str],
    limit: Optional[int],
    mode: str,
    prompt_key: Optional[str],
    prompt_template: Optional[str],
    id_column: Optional[str],
    company_field: Optional[str],
    report_year_field: Optional[str],
) -> None:
    config = load_config()
    if mode not in {"rewrite", "flatten"}:
        raise ValueError("mode must be rewrite or flatten")
    request = MySQLIngestRequest.model_validate(
        dict(
            connection_url=connection_url,
            table=table,
            where=where,
            limit=limit,
            mode=mode,
            prompt_key=prompt_key,
            prompt_template=prompt_template,
            id_column=id_column,
            company_field=company_field,
            report_year_field=report_year_field,
            extra_metadata={},
        )
    )
    with closing(MySQLIngestor(config)) as ingestor:
        summary = ingestor.ingest(request)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge ingestion service CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("process-excel", help="Ingest an Excel file")
    ingest_parser.add_argument("path", help="Path to the Excel file")

    search_parser = subparsers.add_parser("search", help="Run an ad-hoc similarity search")
    search_parser.add_argument("query", help="Query text")
    search_parser.add_argument("--top-k", type=int, default=10)
    search_parser.add_argument("--threshold", type=float, default=None)
    search_parser.add_argument("--metric", choices=["cosine", "l2"], default="cosine")

    mysql_parser = subparsers.add_parser("ingest-mysql", help="Ingest data from a MySQL table")
    mysql_parser.add_argument("connection_url", help="SQLAlchemy style MySQL connection URL")
    mysql_parser.add_argument("table", help="Target table name")
    mysql_parser.add_argument("--where", help="Optional SQL WHERE clause")
    mysql_parser.add_argument("--limit", type=int, help="Maximum number of rows to ingest")
    mysql_parser.add_argument("--mode", choices=["rewrite", "flatten"], default="rewrite")
    mysql_parser.add_argument("--prompt-key", help="Template key to look up in prompt config")
    mysql_parser.add_argument("--prompt-template", help="Override user prompt template")
    mysql_parser.add_argument("--id-column", help="Column to use as unique ID")
    mysql_parser.add_argument("--company-field", help="Column containing company name")
    mysql_parser.add_argument("--report-year-field", help="Column containing report year")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "process-excel":
        process_excel(args.path)
    elif args.command == "search":
        run_search(args.query, top_k=args.top_k, threshold=args.threshold, metric=args.metric)
    elif args.command == "ingest-mysql":
        ingest_mysql(
            connection_url=args.connection_url,
            table=args.table,
            where=args.where,
            limit=args.limit,
            mode=args.mode,
            prompt_key=args.prompt_key,
            prompt_template=args.prompt_template,
            id_column=args.id_column,
            company_field=args.company_field,
            report_year_field=args.report_year_field,
        )


if __name__ == "__main__":
    main()
