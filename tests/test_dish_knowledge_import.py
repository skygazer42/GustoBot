"""Licensed dish articles retain their provenance through protected publication."""

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from gustobot.application.services.recipe_library import get_recipe_library
from gustobot.config.domain import get_domain_definition
from scripts import import_dish_knowledge as importer


@pytest.fixture(scope="module")
def plans():
    return importer.build_import_plan(
        importer.DEFAULT_MANIFEST, get_domain_definition(), get_recipe_library()
    )


def package_copy(tmp_path: Path) -> tuple[Path, dict]:
    destination = tmp_path / "dishes"
    shutil.copytree(importer.DEFAULT_MANIFEST.parent, destination)
    path = destination / "manifest.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def receipt(plan, **changes):
    payload = {
        "job_id": "article-job",
        "domain_id": plan.domain_id,
        "source_id": plan.document.source_id,
        "version": plan.version,
        "ontology_version": plan.ontology_version,
        "kind": "document",
        "status": "ready",
        "details": {},
        "error": None,
    }
    return payload | changes


def test_all_eight_articles_preserve_license_snapshot_and_source_body(plans):
    assert len(plans) == 8
    assert len({plan.entry.topic for plan in plans}) == 7
    assert sum(plan.entry.provenance.text_chars for plan in plans) == 4678
    assert len({plan.document.source_id for plan in plans}) == 8
    for plan in plans:
        entry = plan.entry
        metadata = plan.document.metadata
        assert plan.document.text is not None
        assert plan.version == hashlib.sha256(plan.document.text.encode("utf-8")).hexdigest()
        assert plan.version == entry.body_sha256
        assert plan.graph.sources[0].id == plan.document.source_id
        assert plan.graph.sources[0].text == plan.document.text
        assert plan.graph.sources[0].uri == plan.document.uri == entry.provenance.revision_url
        assert entry.snapshot_id == f"{entry.source_id}:{entry.provenance.revision_id}"
        assert entry.source_id.endswith(f":{entry.provenance.page_id}")
        assert metadata["snapshot_id"] == entry.snapshot_id
        assert metadata["knowledge_kind"] == "dish-background"
        assert metadata["license"] == "CC-BY-SA-4.0"
        assert metadata["license_url"] in plan.document.text
        assert metadata["attribution"] in plan.document.text
        assert metadata["contributors_url"] in plan.document.text
        assert metadata["source_url"] in plan.document.text
        assert metadata["raw_text_sha256"] == entry.provenance.raw_text_sha256
        assert metadata["excerpts"] == [value.model_dump() for value in entry.provenance.excerpts]
        assert metadata["independently_fact_checked"] is False
        assert metadata["clinical_or_nutrition_evidence"] is False


def test_links_are_dish_identities_and_catalog_versions_are_exact(plans):
    model = get_domain_definition().semantic_model
    assert model is not None
    library = get_recipe_library()
    for plan in plans:
        entry = plan.entry
        metadata = plan.document.metadata
        assert metadata["topic_entity_id"] == model.identity_id("Dish", {"name": entry.topic})
        names = [
            entry.topic,
            *entry.topic_aliases,
            *[ref.name for ref in entry.catalog_recipe_refs],
        ]
        assert plan.document.entity_ids == sorted(
            {model.identity_id("Dish", {"name": name}) for name in names}
        )
        assert metadata["catalog_recipe_refs"] == [
            {"id": ref.id, "version": ref.version} for ref in entry.catalog_recipe_refs
        ]
        for ref in entry.catalog_recipe_refs:
            assert ref.version == library.get(ref.id).version
        if entry.topic == "番茄炒蛋":
            assert entry.catalog_recipe_refs == []
        if entry.topic == "红烧肉":
            assert entry.provenance.topic_scope == "shared_dish_background"
            assert len(entry.catalog_recipe_refs) == 2
        if entry.topic == "蛋炒饭":
            assert entry.provenance.topic_scope == "broader_background"


def test_graph_contains_only_supported_dish_concepts_and_verbatim_quotes(plans):
    for plan in plans:
        assert plan.graph.relations == []
        assert len(plan.graph.entities) == 1
        entity = plan.graph.entities[0]
        assert entity.type == "Dish"
        assert entity.name == plan.entry.topic
        assert entity.properties == {}
        for evidence in entity.evidence:
            assert evidence.source_id == plan.entry.source_id
            assert evidence.quote in plan.graph.sources[0].text


def test_plan_is_deterministic(plans):
    repeated = importer.build_import_plan(
        importer.DEFAULT_MANIFEST, get_domain_definition(), get_recipe_library()
    )
    assert plans == repeated


@pytest.mark.parametrize("body_path", ["../outside.md", "C:/outside.md", "/outside.md"])
def test_rejects_paths_outside_article_package(tmp_path, body_path):
    path, payload = package_copy(tmp_path)
    payload["documents"][0]["body_path"] = body_path
    write_manifest(path, payload)
    with pytest.raises(ValueError, match="path"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_rejects_modified_body(tmp_path):
    path, payload = package_copy(tmp_path)
    body = path.parent / payload["documents"][0]["body_path"]
    body.write_bytes(body.read_bytes() + b"changed\n")
    with pytest.raises(ValueError, match="hash"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_rejects_article_symlink_outside_package(tmp_path):
    path, payload = package_copy(tmp_path)
    body = path.parent / payload["documents"][0]["body_path"]
    outside = tmp_path / "outside.md"
    outside.write_bytes(body.read_bytes())
    body.unlink()
    try:
        body.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"Filesystem cannot create symbolic links: {error}")
    with pytest.raises(ValueError, match="path escapes"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_rejects_omitted_attribution_even_when_hash_updated(tmp_path):
    path, payload = package_copy(tmp_path)
    entry = payload["documents"][0]
    body = path.parent / entry["body_path"]
    changed = body.read_text(encoding="utf-8").replace(entry["provenance"]["attribution"], "")
    body.write_bytes(changed.encode("utf-8"))
    entry["body_sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
    write_manifest(path, payload)
    with pytest.raises(ValueError, match="attribution"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_rejects_repinning_catalog_without_review(tmp_path):
    path, payload = package_copy(tmp_path)
    entry = next(value for value in payload["documents"] if value["catalog_recipe_refs"])
    entry["catalog_recipe_refs"][0]["version"] = "0" * 64
    write_manifest(path, payload)
    with pytest.raises(ValueError, match="catalog version"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_rejects_duplicate_source_ids(tmp_path):
    path, payload = package_copy(tmp_path)
    payload["documents"].append(payload["documents"][0])
    write_manifest(path, payload)
    with pytest.raises(ValueError, match="Duplicate"):
        importer.build_import_plan(path, get_domain_definition(), get_recipe_library())


def test_publishes_document_then_validates_then_writes_graph(plans):
    plan = plans[0]
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json=receipt(plan))
        if request.url.path.endswith("/validate"):
            return httpx.Response(
                200, json={"graph": payload["graph"], "validation": {"valid": True, "errors": []}}
            )
        return httpx.Response(200, json={"entities": 1, "relations": 0, "sources": 1})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client:
        document, graph = importer.import_article(client, plan)
    assert document.status == "ready"
    assert graph.entities == 1
    assert [path for path, _ in requests] == [
        "/api/v1/knowledge/documents",
        "/api/v1/ontology/admin/validate",
        "/api/v1/ontology/admin/facts",
    ]
    assert requests[0][1] == plan.document.model_dump(mode="json")
    assert requests[1][1] == requests[2][1]
    assert requests[1][1]["version"] == plan.version


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "failed", "error": "index unavailable"},
        {"status": "pending"},
        {"version": "wrong"},
        {"source_id": "other"},
        {"kind": "recipe"},
        {"domain_id": "other"},
        {"ontology_version": "other"},
        {"error": "still failed"},
    ],
)
def test_does_not_publish_graph_for_unready_or_mismatched_document(plans, changes):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=receipt(plans[0], **changes))

    with (
        httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client,
        pytest.raises(RuntimeError, match="document publication"),
    ):
        importer.import_article(client, plans[0])
    assert calls == ["/api/v1/knowledge/documents"]


@pytest.mark.parametrize("invalid_graph", [False, True])
def test_failed_validation_or_changed_source_stops_fact_write(plans, invalid_graph):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json=receipt(plans[0]))
        graph = plans[0].graph.model_dump(mode="json")
        if invalid_graph:
            graph["sources"][0]["text"] = "a different source body"
        return httpx.Response(
            200,
            json={
                "graph": graph,
                "validation": {"valid": invalid_graph, "errors": [] if invalid_graph else ["bad"]},
            },
        )

    with (
        httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client,
        pytest.raises(RuntimeError, match="graph validation"),
    ):
        importer.import_article(client, plans[0])
    assert len(calls) == 2


@pytest.mark.parametrize("failed_phase", ["documents", "validate", "facts"])
def test_http_failures_stay_visible_and_stop_pipeline(plans, failed_phase):
    phases = []

    def handle(request):
        phase = request.url.path.rsplit("/", 1)[1]
        phases.append(phase)
        if phase == failed_phase:
            return httpx.Response(503, json={"detail": "offline"})
        if phase == "documents":
            return httpx.Response(200, json=receipt(plans[0]))
        return httpx.Response(
            200,
            json={
                "graph": plans[0].graph.model_dump(mode="json"),
                "validation": {"valid": True, "errors": []},
            },
        )

    with (
        httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(handle),
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        importer.import_article(client, plans[0])
    assert phases == ["documents", "validate", "facts"][: phases.index(failed_phase) + 1]


def test_incomplete_fact_write_is_not_reported_as_success(plans):
    def handle(request):
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json=receipt(plans[0]))
        if request.url.path.endswith("/validate"):
            return httpx.Response(
                200,
                json={
                    "graph": plans[0].graph.model_dump(mode="json"),
                    "validation": {"valid": True, "errors": []},
                },
            )
        return httpx.Response(200, json={"entities": 0, "relations": 0, "sources": 0})

    with (
        httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client,
        pytest.raises(RuntimeError, match="Incomplete graph publication"),
    ):
        importer.import_article(client, plans[0])


def test_authentication_uses_only_login_body_and_keeps_cookie():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"authenticated": False, "configured": True})
        assert json.loads(request.content) == {"password": "test-admin-password"}
        return httpx.Response(204, headers={"set-cookie": "gustobot_admin=session; Path=/"})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client:
        importer.authenticate_admin(client, SecretStr("test-admin-password"))
        assert client.cookies["gustobot_admin"] == "session"
    assert len(requests) == 2
    assert all("test-admin-password" not in str(request.url) for request in requests)
    assert all("test-admin-password" not in str(request.headers) for request in requests)


def test_required_admin_password_missing_is_visible():
    with (
        httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"authenticated": False, "configured": True})
            ),
        ) as client,
        pytest.raises(RuntimeError, match="GUSTOBOT_ADMIN_PASSWORD"),
    ):
        importer.authenticate_admin(client, None)


@pytest.mark.parametrize(
    "session",
    [{"authenticated": False, "configured": False}, {"authenticated": True, "configured": True}],
)
def test_unnecessary_login_does_not_send_password(session):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=session)

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as client:
        importer.authenticate_admin(client, SecretStr("unused-test-secret"))
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].content == b""


def test_default_cli_is_offline_dry_run(monkeypatch, capsys):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("dry-run must not create an HTTP client")

    monkeypatch.setattr(importer.httpx, "Client", unexpected_client)
    assert importer.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["documents"] == 8
    assert output["topic_count"] == 7


def test_explicit_apply_publishes_all_articles_with_session_cookie(plans, monkeypatch, capsys):
    by_source = {plan.entry.source_id: plan for plan in plans}
    published = []
    client_class = httpx.Client

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"authenticated": False, "configured": True})
        payload = json.loads(request.content)
        if request.url.path.endswith("/session"):
            assert payload == {"password": "test-cli-admin-secret"}
            return httpx.Response(204, headers={"set-cookie": "gustobot_admin=cli-session; Path=/"})
        assert request.headers["cookie"] == "gustobot_admin=cli-session"
        if request.url.path.endswith("/documents"):
            plan = by_source[payload["source_id"]]
            assert payload == plan.document.model_dump(mode="json")
            return httpx.Response(200, json=receipt(plan))
        if request.url.path.endswith("/validate"):
            return httpx.Response(
                200, json={"graph": payload["graph"], "validation": {"valid": True, "errors": []}}
            )
        published.append(payload["source_id"])
        return httpx.Response(200, json={"entities": 1, "relations": 0, "sources": 1})

    def create_client(**kwargs):
        return client_class(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(importer.httpx, "Client", create_client)
    monkeypatch.setattr(
        importer.settings, "GUSTOBOT_ADMIN_PASSWORD", SecretStr("test-cli-admin-secret")
    )
    assert importer.main(["--apply", "--base-url", "http://test"]) == 0
    captured = capsys.readouterr()
    assert "test-cli-admin-secret" not in captured.out + captured.err
    output = [json.loads(line) for line in captured.out.splitlines()]
    assert published == list(by_source)
    assert [value["source_id"] for value in output] == published
    assert all(value["status"] == "ready" for value in output)
