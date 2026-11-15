"""CLI entrypoint for the knowledge ingestion project."""

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    from kb_service.cli import main as run_cli

    run_cli()


if __name__ == "__main__":
    main()
