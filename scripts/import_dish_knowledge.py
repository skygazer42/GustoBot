"""Review licensed dish articles offline, then explicitly publish via admin APIs."""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gustobot.application.services.knowledge_ingestion import (
    DocumentIngestionRequest,
    IngestionReceipt,
)
from gustobot.application.services.ontology_admin import GraphDraft
from gustobot.application.services.recipe_library import (
    RecipeLibrary,
    get_recipe_library,
)
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeEntity,
    KnowledgeGraph,
    SourceDocument,
)
from gustobot.infrastructure.knowledge.graph_store import GraphWriteResult
from gustobot.infrastructure.knowledge.semantic_runtime import get_semantic_runtime
from gustobot.interfaces.http.admin_session import SessionStatus

DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "kb" / "dishes" / "manifest.json"
SHA256_PATTERN = r"^[a-f0-9]{64}$"


class ExcerptRange(BaseModel):
    """Unicode character range and checksum within the upstream API extract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    section: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    sha256: str = Field(pattern=SHA256_PATTERN)


class RemovedSentence(BaseModel):
    """Excluded source range and the editorial reason retained for review."""

    model_config = ConfigDict(extra="forbid", strict=True)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    reason: str


class ArticleProvenance(BaseModel):
    """Fixed upstream revision, redistribution terms and content limits."""

    model_config = ConfigDict(extra="forbid", strict=True)
    content_kind: Literal["background"]
    topic_scope: Literal[
        "dish_background",
        "shared_dish_background",
        "broader_background",
        "alternative_technique_notes",
    ]
    source_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    revision_url: str = Field(min_length=1)
    revision_id: int = Field(gt=0)
    revision_timestamp: str = Field(min_length=1)
    page_id: int = Field(gt=0)
    attribution: str = Field(min_length=1)
    contributors_url: str = Field(min_length=1)
    license: Literal["CC-BY-SA-4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by-sa/4.0/"]
    license_verification: str = Field(min_length=1)
    rightsinfo: dict[str, str]
    retrieved_at: str = Field(min_length=1)
    raw_text_sha256: str = Field(pattern=SHA256_PATTERN)
    text_sha256: str = Field(pattern=SHA256_PATTERN)
    text_chars: int = Field(gt=0)
    excerpts: list[ExcerptRange] = Field(min_length=1)
    removed_sentences: list[RemovedSentence]
    included_sections: list[str] = Field(min_length=1)
    excluded_sections: list[str] = Field(default_factory=list)
    source_subjects: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(min_length=1)
    independently_fact_checked: Literal[False]
    cooking_tested: Literal[False]
    clinical_or_nutrition_evidence: Literal[False]
    topic_linking_note: str = Field(min_length=1)


class CatalogRecipeReference(BaseModel):
    """An actual catalog recipe and the exact reviewed version of that record."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    version: str = Field(pattern=SHA256_PATTERN)
    name: str = Field(min_length=1)


class ArticleEntry(BaseModel):
    """One licensed Markdown body and its intended dish-level associations."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern=r"^(wikipedia-zh|wikibooks-zh):[1-9][0-9]*$")
    snapshot_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    topic_aliases: list[str]
    catalog_recipe_refs: list[CatalogRecipeReference]
    title: str = Field(min_length=1)
    body_path: str = Field(min_length=1)
    body_sha256: str = Field(pattern=SHA256_PATTERN)
    provenance: ArticleProvenance


class ArticleManifest(BaseModel):
    """The explicit allowlist of article files admitted by this import command."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    domain_id: str = Field(min_length=1)
    documents: list[ArticleEntry] = Field(min_length=1)


@dataclass(frozen=True)
class DishArticleImport:
    """Locally validated requests sharing an identical source body and identity."""

    entry: ArticleEntry
    document: DocumentIngestionRequest
    graph: KnowledgeGraph
    version: str
    domain_id: str
    ontology_version: str


def read_article(package_root: Path, entry: ArticleEntry) -> tuple[str, str]:
    """Check the allowlisted file, attribution and exact selected source text."""
    relative = Path(entry.body_path)
    if relative.is_absolute() or relative.name != entry.body_path or relative.suffix != ".md":
        raise ValueError(f"Unsafe article path: {entry.body_path}")
    path = (package_root / relative).resolve(strict=True)
    if path.parent != package_root:
        raise ValueError(f"Article path escapes package: {entry.body_path}")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != entry.body_sha256:
        raise ValueError(f"Article hash mismatch: {entry.source_id}")
    if content.startswith(b"\xef\xbb\xbf") or b"\r" in content:
        raise ValueError(f"Article must use UTF-8 without BOM and LF: {entry.source_id}")
    body = content.decode("utf-8")
    provenance = entry.provenance
    for attribution in (
        provenance.source_url,
        provenance.revision_url,
        provenance.contributors_url,
        provenance.attribution,
        provenance.license_url,
        provenance.source_title,
    ):
        if attribution not in body:
            raise ValueError(f"Missing article attribution: {entry.source_id}")
    _, heading, remainder = body.partition("## 原文选段\n\n")
    selected, boundary, _ = remainder.partition("\n\n## 使用边界")
    selected += "\n"
    if (
        not heading
        or not boundary
        or len(selected) != provenance.text_chars
        or hashlib.sha256(selected.encode("utf-8")).hexdigest() != provenance.text_sha256
    ):
        raise ValueError(f"Selected source text hash mismatch: {entry.source_id}")
    return body, selected


def build_import_plan(
    manifest_path: Path, domain: DomainDefinition, library: RecipeLibrary
) -> list[DishArticleImport]:
    """Prepare every document and Dish-only graph before any network operation."""
    manifest_path = manifest_path.resolve(strict=True)
    manifest = ArticleManifest.model_validate_json(manifest_path.read_bytes())
    if manifest.domain_id != domain.id:
        raise ValueError(f"Article domain differs from configured domain: {manifest.domain_id}")
    model = domain.semantic_model
    runtime = get_semantic_runtime(domain)
    if model is None or runtime is None or "Dish" not in domain.entity_types:
        raise ValueError("Dish article import requires the configured formal Dish ontology")
    seen = set()
    plans = []
    for entry in manifest.documents:
        if entry.source_id in seen:
            raise ValueError(f"Duplicate article source: {entry.source_id}")
        seen.add(entry.source_id)
        provenance = entry.provenance
        if (
            not entry.source_id.endswith(f":{provenance.page_id}")
            or entry.snapshot_id != f"{entry.source_id}:{provenance.revision_id}"
        ):
            raise ValueError(f"Article snapshot identity mismatch: {entry.source_id}")
        body, selected_text = read_article(manifest_path.parent, entry)
        for reference in entry.catalog_recipe_refs:
            recipe = library.get(reference.id)
            if (recipe.name, recipe.version) != (reference.name, reference.version):
                raise ValueError(f"Reviewed catalog version changed: {reference.id}")
        names = [
            entry.topic,
            *entry.topic_aliases,
            *[ref.name for ref in entry.catalog_recipe_refs],
        ]
        topic_id = model.identity_id("Dish", {"name": entry.topic})
        entity_ids = sorted({model.identity_id("Dish", {"name": name}) for name in names})
        document = DocumentIngestionRequest(
            source_id=entry.source_id,
            text=body,
            uri=provenance.revision_url,
            entity_ids=entity_ids,
            metadata={
                **provenance.model_dump(mode="json"),
                "knowledge_kind": "dish-background",
                "title": entry.title,
                "topic": entry.topic,
                "topic_aliases": entry.topic_aliases,
                "topic_entity_id": topic_id,
                "snapshot_id": entry.snapshot_id,
                "body_sha256": entry.body_sha256,
                "catalog_recipe_refs": [
                    {"id": ref.id, "version": ref.version} for ref in entry.catalog_recipe_refs
                ],
                "catalog_recipe_names": [ref.name for ref in entry.catalog_recipe_refs],
            },
        )
        graph = KnowledgeGraph(
            entities=[
                KnowledgeEntity(
                    id=topic_id,
                    type="Dish",
                    name=entry.topic,
                    aliases=[
                        alias
                        for alias in entry.topic_aliases
                        if alias != entry.topic
                        and (alias in selected_text or alias in provenance.source_title)
                    ],
                    evidence=[
                        EvidenceReference(source_id=entry.source_id, quote=provenance.source_title)
                    ],
                )
            ],
            relations=[],
            sources=[SourceDocument(id=entry.source_id, text=body, uri=provenance.revision_url)],
        )
        graph = runtime.bind_graph(graph)
        runtime.validate_input(graph)
        plans.append(
            DishArticleImport(entry, document, graph, entry.body_sha256, domain.id, domain.version)
        )
    return plans


def authenticate_admin(client: httpx.Client, password: SecretStr | None) -> None:
    """Reuse the protected browser-session login without printing credentials."""
    response = client.get("/api/v1/admin/session")
    response.raise_for_status()
    status = SessionStatus.model_validate(response.json())
    if not status.configured or status.authenticated:
        return
    if password is None:
        raise RuntimeError("Server requires configured GUSTOBOT_ADMIN_PASSWORD")
    response = client.post("/api/v1/admin/session", json={"password": password.get_secret_value()})
    response.raise_for_status()
    if response.status_code != 204:
        raise RuntimeError("Administrator login did not return a session")


def import_article(
    client: httpx.Client, plan: DishArticleImport
) -> tuple[IngestionReceipt, GraphWriteResult]:
    """Publish text, validate its exact graph and write only accepted facts."""
    response = client.post(
        "/api/v1/knowledge/documents", json=plan.document.model_dump(mode="json")
    )
    response.raise_for_status()
    receipt = IngestionReceipt.model_validate(response.json())
    if (
        receipt.status != "ready"
        or receipt.error is not None
        or receipt.kind != "document"
        or receipt.source_id != plan.entry.source_id
        or receipt.version != plan.version
        or receipt.domain_id != plan.domain_id
        or receipt.ontology_version != plan.ontology_version
    ):
        raise RuntimeError(
            f"Incomplete document publication for {plan.entry.source_id}: "
            f"status={receipt.status}, error={receipt.error}"
        )
    graph_request = {
        "source_id": plan.entry.source_id,
        "version": plan.version,
        "graph": plan.graph.model_dump(mode="json"),
    }
    response = client.post("/api/v1/ontology/admin/validate", json=graph_request)
    response.raise_for_status()
    draft = GraphDraft.model_validate(response.json())
    if not draft.validation.valid or draft.graph != plan.graph:
        raise RuntimeError(
            f"Failed graph validation for {plan.entry.source_id}: {draft.validation.errors}"
        )
    response = client.post("/api/v1/ontology/admin/facts", json=graph_request)
    response.raise_for_status()
    written = GraphWriteResult.model_validate(response.json())
    expected = (len(plan.graph.entities), len(plan.graph.relations), len(plan.graph.sources))
    if (written.entities, written.relations, written.sources) != expected:
        raise RuntimeError(f"Incomplete graph publication for {plan.entry.source_id}")
    return receipt, written


def main(argv: list[str] | None = None) -> int:
    """Default to offline verification; --apply explicitly enables HTTP writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--apply", action="store_true", help="Publish through protected admin APIs")
    args = parser.parse_args(argv)
    try:
        plans = build_import_plan(args.manifest, get_domain_definition(), get_recipe_library())
        if not args.apply:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "documents": len(plans),
                        "topic_count": len({plan.entry.topic for plan in plans}),
                        "sources": [
                            {"source_id": plan.entry.source_id, "version": plan.version}
                            for plan in plans
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        with httpx.Client(
            base_url=args.base_url,
            timeout=httpx.Timeout(120, connect=10),
            follow_redirects=False,
        ) as client:
            authenticate_admin(client, settings.GUSTOBOT_ADMIN_PASSWORD)
            for plan in plans:
                receipt, written = import_article(client, plan)
                print(
                    json.dumps(
                        {
                            "source_id": receipt.source_id,
                            "version": receipt.version,
                            "status": receipt.status,
                            "graph": written.model_dump(),
                        }
                    ),
                    flush=True,
                )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Article import failed: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
