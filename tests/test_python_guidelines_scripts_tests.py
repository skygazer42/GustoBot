"""Offline regression coverage for data-conversion and command-line boundaries."""

import asyncio
import importlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
from importlib import util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

READERS = (
    "scripts.append_qa_to_alpaca",
    "scripts.recipe_to_alpaca",
    "scripts.replace_in",
)


@pytest.mark.parametrize("module_name", READERS)
@pytest.mark.parametrize("as_array", [False, True])
def test_dataset_readers_preserve_valid_records(tmp_path, module_name, as_array):
    records = [{"src": "问题", "tgt": "回答"}, {"src": "追问", "tgt": "补充"}]
    text = json.dumps(records) if as_array else "\n".join(map(json.dumps, records))
    path = tmp_path / "records.json"
    path.write_text(" \n" + text + "\n", encoding="utf-8")

    assert importlib.import_module(module_name).read_any(str(path)) == records


@pytest.mark.parametrize("module_name", READERS)
def test_dataset_readers_reject_malformed_rows(tmp_path, module_name):
    path = tmp_path / "records.jsonl"
    path.write_text('{"src": "valid", "tgt": "answer"}\n{broken}\n', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        importlib.import_module(module_name).read_any(str(path))


def test_qa_converter_requires_actual_text():
    from scripts.append_qa_to_alpaca import qa_to_alpaca

    assert qa_to_alpaca({"src": "问题", "tgt": "回答"}) == {
        "instruction": "问题",
        "input": "",
        "output": "回答",
    }
    with pytest.raises(KeyError):
        qa_to_alpaca({"tgt": "回答"})
    with pytest.raises(TypeError):
        qa_to_alpaca({"src": None, "tgt": "回答"})


def test_qa_stdin_reader_supports_jsonl(monkeypatch):
    from scripts import append_qa_to_alpaca

    monkeypatch.setattr(append_qa_to_alpaca.sys, "stdin", io.StringIO('{"src":"q","tgt":"a"}\n'))
    assert append_qa_to_alpaca.read_any("-") == [{"src": "q", "tgt": "a"}]


def test_recipe_payload_preserves_explicit_empty_fields():
    from scripts.import_recipes import _iter_payloads_from_json

    payload = next(
        _iter_payloads_from_json(
            [{"name": "菜", "category": "", "类型": "fallback", "time": "", "耗时": "10分钟"}]
        )
    )
    assert payload["record"]["category"] == ""
    assert payload["record"]["time"] == ""
    assert list(_iter_payloads_from_json({"菜": {}}, limit=0)) == []


def test_import_response_requires_server_statistics():
    from scripts.import_recipes import _post_batch

    transport = httpx.MockTransport(lambda request: httpx.Response(201, json={}))
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(ValueError, match="receipt"),
    ):
        _post_batch(client, api_base_url="http://test", recipes=[{"name": "菜"}])


def test_import_response_preserves_zero_success():
    from scripts.import_recipes import _post_batch

    transport = httpx.MockTransport(lambda request: httpx.Response(201, json=[]))
    with httpx.Client(transport=transport) as client:
        inserted, _ = _post_batch(client, api_base_url="http://test", recipes=[])
    assert inserted == 0


@pytest.mark.parametrize(
    "option,value", [("--batch-size", "0"), ("--limit", "-1"), ("--timeout", "0")]
)
def test_import_cli_rejects_invalid_bounds(option, value):
    from scripts.import_recipes import main

    with pytest.raises(SystemExit) as error:
        main(["--file", "not-read.json", option, value])
    assert error.value.code == 2


def test_launcher_cleans_backend_when_frontend_start_fails(monkeypatch):
    from scripts import start_chatbot

    events = []
    backend = SimpleNamespace(
        pid=100001,
        wait=lambda timeout: events.append("wait"),
        poll=lambda: None,
    )

    def fail_frontend_start():
        raise RuntimeError("frontend failed")

    monkeypatch.setattr(start_chatbot, "start_backend", lambda: backend)
    monkeypatch.setattr(start_chatbot, "start_frontend", fail_frontend_start)
    monkeypatch.setattr(start_chatbot.time, "sleep", lambda _seconds: None)

    def stop_tree(*args, **kwargs):
        events.append("terminate")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(start_chatbot.subprocess, "run", stop_tree)
    monkeypatch.setattr(os, "killpg", stop_tree, raising=False)

    with pytest.raises(RuntimeError, match="frontend failed"):
        start_chatbot.main()
    assert events == ["terminate", "wait"]


@pytest.mark.parametrize("installed", [True, False])
def test_frontend_uses_resolved_npm_and_vite_browser(monkeypatch, tmp_path, installed):
    from scripts import start_chatbot

    if installed:
        (tmp_path / "node_modules").mkdir()
    npm = str(tmp_path / "npm.CMD")
    monkeypatch.setattr(start_chatbot, "WEB_ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: npm)
    install = Mock(return_value=subprocess.CompletedProcess([], 0))
    spawn = Mock()
    monkeypatch.setattr(subprocess, "run", install)
    monkeypatch.setattr(subprocess, "Popen", spawn)

    assert start_chatbot.start_frontend() is spawn.return_value
    command = spawn.call_args.args[0]
    assert command[:5] == [npm, "run", "dev", "--", "--host"]
    assert "--open" in command
    assert "--port" not in command
    assert spawn.call_args.kwargs["cwd"] == tmp_path
    if installed:
        install.assert_not_called()
    else:
        install.assert_called_once_with([npm, "install"], cwd=tmp_path, check=True)


@pytest.mark.parametrize("server", ["start_backend", "start_frontend"])
@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_servers_use_isolated_process_groups(monkeypatch, tmp_path, server, platform):
    from scripts import start_chatbot

    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(start_chatbot, "WEB_ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: "npm")
    spawn = Mock()
    monkeypatch.setattr(subprocess, "Popen", spawn)
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
        patch.setattr(sys, "platform", platform)
        if server == "start_backend":
            start_chatbot.start_backend()
        else:
            start_chatbot.start_frontend()
    assert spawn.call_args.kwargs["start_new_session"] == (platform != "win32")
    assert spawn.call_args.kwargs["creationflags"] == (512 if platform == "win32" else 0)


@pytest.fixture
def launcher_processes(monkeypatch):
    from scripts import start_chatbot

    backend = Mock(spec=subprocess.Popen)
    frontend = Mock(spec=subprocess.Popen)
    for pid, process in enumerate((backend, frontend), 100001):
        process.pid = pid
        process.poll.return_value = None
    monkeypatch.setattr(start_chatbot, "start_backend", lambda: backend)
    monkeypatch.setattr(start_chatbot, "start_frontend", lambda: frontend)
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0)))
    monkeypatch.setattr(os, "killpg", Mock(), raising=False)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)

    def interrupt(_seconds):
        if backend.poll.called and frontend.poll.called:
            raise KeyboardInterrupt

    monkeypatch.setattr(start_chatbot.time, "sleep", interrupt)
    return backend, frontend


def test_launcher_reaps_both_servers_on_interrupt(launcher_processes):
    from scripts import start_chatbot

    start_chatbot.main()
    for process in launcher_processes:
        process.wait.assert_called_once_with(timeout=10)


def test_launcher_still_cleans_backend_when_frontend_cleanup_fails(launcher_processes):
    from scripts import start_chatbot

    backend, frontend = launcher_processes
    backend.poll.return_value = 7
    frontend.wait.side_effect = OSError("frontend cleanup failed")
    with pytest.raises(OSError, match="frontend cleanup failed") as error:
        start_chatbot.main()
    backend.wait.assert_called_once_with(timeout=10)
    assert isinstance(error.value.__context__, RuntimeError)
    assert "7" in str(error.value.__context__)


@pytest.mark.parametrize("server_index", [0, 1])
def test_launcher_reports_server_exit_and_reaps_both(launcher_processes, server_index):
    from scripts import start_chatbot

    launcher_processes[server_index].poll.return_value = 3
    with pytest.raises(RuntimeError, match="3"):
        start_chatbot.main()
    for process in launcher_processes:
        process.wait.assert_called_once_with(timeout=10)


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_launcher_stops_process_groups(launcher_processes, monkeypatch, platform):
    from scripts import start_chatbot

    backend, frontend = launcher_processes
    if platform == "linux":
        backend.wait.side_effect = [subprocess.TimeoutExpired("backend", 10), 0]
    with monkeypatch.context() as patch:
        stop_tree = Mock(return_value=subprocess.CompletedProcess([], 0))
        stop_group = Mock()
        patch.setattr(subprocess, "run", stop_tree)
        patch.setattr(os, "killpg", stop_group, raising=False)
        patch.setattr(sys, "platform", platform)
        start_chatbot.main()
        if platform == "win32":
            commands = [call.args[0] for call in stop_tree.call_args_list]
            assert commands == [
                ["taskkill", "/PID", str(frontend.pid), "/T", "/F"],
                ["taskkill", "/PID", str(backend.pid), "/T", "/F"],
            ]
        else:
            calls = [call.args for call in stop_group.call_args_list]
            assert calls == [
                (frontend.pid, signal.SIGTERM),
                (backend.pid, signal.SIGTERM),
                (backend.pid, 9),
            ]
    assert backend.wait.call_count == (2 if platform == "linux" else 1)


@pytest.mark.parametrize("stage", ["terminate", "wait"])
def test_windows_cleanup_timeout_is_visible_and_other_server_is_cleaned(
    launcher_processes, monkeypatch, stage
):
    from scripts import start_chatbot

    backend, frontend = launcher_processes
    stop_tree = Mock(return_value=subprocess.CompletedProcess([], 0))
    if stage == "terminate":
        stop_tree.side_effect = [
            subprocess.TimeoutExpired("taskkill", 10),
            subprocess.CompletedProcess([], 0),
        ]
    else:
        frontend.wait.side_effect = [subprocess.TimeoutExpired("frontend", 10), 0]
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        patch.setattr(subprocess, "run", stop_tree)
        with pytest.raises(subprocess.TimeoutExpired):
            start_chatbot.main()
    backend.wait.assert_called_once_with(timeout=10)
    assert all(call.kwargs["timeout"] == 10 for call in stop_tree.call_args_list)


def test_cli_creates_env_from_project_template(monkeypatch, tmp_path):
    from scripts import run

    template = "LLM_API_KEY=example\nDATABASE_URL=project-default\n"
    (tmp_path / ".env.example").write_text(template, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path, raising=False)

    run.create_env_example()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == template
    with pytest.raises(FileExistsError):
        run.create_env_example()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == template


@pytest.mark.parametrize("mode,option", [("dev", "--reload"), ("prod", "--workers")])
def test_backend_cli_uses_project_directory(monkeypatch, tmp_path, mode, option):
    from scripts import run

    spawn = Mock()
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(subprocess, "run", spawn)
    run.start_server(mode)
    assert spawn.call_args.kwargs["cwd"] == tmp_path
    assert spawn.call_args.kwargs["check"] is True
    command = spawn.call_args.args[0]
    assert command[:4] == [sys.executable, "-m", "uvicorn", "gustobot.main:application"]
    assert option in command


@pytest.mark.parametrize("command", ["check", "start"])
def test_cli_failed_requirements_return_failure(monkeypatch, command):
    from scripts import run

    monkeypatch.setattr(sys, "argv", ["run.py", command])
    monkeypatch.setattr(run, "check_requirements", lambda: False)
    assert run.main() == 1


def test_cli_docker_failure_is_visible(monkeypatch, tmp_path):
    from scripts import run

    (tmp_path / "docker-compose.yml").touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, "docker-compose"))
    )
    with pytest.raises(subprocess.CalledProcessError):
        run.start_docker()


@pytest.mark.parametrize("reply,status", [({"message": "回答"}, 200), ({}, 200), ({}, 503)])
def test_cli_api_diagnostic_checks_response_and_closes_client(monkeypatch, capsys, reply, status):
    from scripts import run

    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy", "version": "test-version"})
        return httpx.Response(status, json=reply)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    if status != 200:
        with pytest.raises(httpx.HTTPStatusError):
            run.test_api()
    elif not reply:
        with pytest.raises(KeyError, match="message"):
            run.test_api()
    else:
        run.test_api()
        assert "回答" in capsys.readouterr().out
    assert client.is_closed
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/health"),
        ("POST", "/api/v1/chat/"),
    ]
    assert json.loads(requests[1].content) == {
        "message": "你好",
        "session_id": None,
        "user_id": "tester",
    }


def test_csv_writer_includes_cuisine_files(tmp_path):
    from scripts.recipe_kg_to_csv import RecipeRecord, _build_graph_assets, _write_csv

    recipe = RecipeRecord(
        name="九转大肠",
        cook_time=None,
        flavors=[],
        methods=[],
        dish_types=[],
        instructions=None,
        steps=[],
        main_ingredients=[],
        aux_ingredients=[],
        cuisine_styles=["鲁菜"],
    )
    assets = _build_graph_assets([recipe], [])
    _write_csv(tmp_path, assets)
    assert assets["nodes_cuisine"] == [{"id": "cuisine_1", "name": "鲁菜"}]
    assert "鲁菜" in (tmp_path / "cuisine_nodes.csv").read_text(encoding="utf-8")
    assert "cuisine_1" in (tmp_path / "rel_belongs_cuisine.csv").read_text(encoding="utf-8")


def test_chat_diagnostic_fetches_history_with_open_client(monkeypatch):
    spec = util.spec_from_file_location(
        "chat_diagnostic", Path(__file__).with_name("test_chat_api.py")
    )
    assert spec is not None
    assert spec.loader is not None
    test_chat_api = util.module_from_spec(spec)
    spec.loader.exec_module(test_chat_api)

    requests = []

    def respond(request):
        requests.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "session_id": "offline",
                    "route": "expected",
                    "message": "fixture answer",
                    "message_id": "fixture-message",
                    "route_logic": "fixture",
                    "sources": [],
                    "metadata": {},
                },
            )
        return httpx.Response(200, json=[])

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        test_chat_api.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(
        test_chat_api,
        "TEST_CASES",
        [{"name": "offline", "message": "hello", "expected_route": "expected"}],
    )
    monkeypatch.setattr(test_chat_api.asyncio, "sleep", AsyncMock())
    asyncio.run(test_chat_api.test_chat_api())
    assert requests == ["POST", "GET"]


@pytest.mark.parametrize("module_name", READERS)
def test_dataset_cli_runs_from_another_directory(tmp_path, module_name):
    script = Path(__file__).resolve().parents[1] / (module_name.replace(".", "/") + ".py")
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert b"usage:" in result.stdout


def test_recipe_converter_preserves_explicit_empty_ingredients(monkeypatch, tmp_path):
    from scripts import recipe_to_alpaca

    source = tmp_path / "recipes.json"
    output = tmp_path / "alpaca.jsonl"
    source.write_text(
        json.dumps([{"name": "菜", "recipeIngredient": [], "ingredients": ["旧食材"]}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv", ["recipe_to_alpaca", "--in", str(source), "--out", str(output)]
    )
    recipe_to_alpaca.main()
    assert json.loads(output.read_text(encoding="utf-8"))["output"] == ""


def test_csv_encoder_requires_declared_columns_and_preserves_zero():
    from scripts.recipe_kg_to_csv import _encode_row

    assert _encode_row(["order:int", "instruction"], {"order": 0, "instruction": None}) == {
        "order:int": 0,
        "instruction": "",
    }
    with pytest.raises(KeyError, match="id"):
        _encode_row(["id:ID(Dish)", "name"], {"name": "菜"})


def test_csv_writer_requires_all_graph_asset_groups(tmp_path):
    from scripts.recipe_kg_to_csv import _write_csv

    with pytest.raises(KeyError, match="nodes_dish"):
        _write_csv(tmp_path, {})


@pytest.mark.parametrize(
    "description,expected", [(0, "0"), (False, "False"), (None, ""), ("", ""), ("原文", "原文")]
)
def test_alpaca_description_preserves_zero_false_and_absence(
    monkeypatch, tmp_path, description, expected
):
    from scripts import recipe_to_alpaca

    source = tmp_path / "recipes.json"
    target = tmp_path / "alpaca.jsonl"
    source.write_text(
        json.dumps(
            [{"name": "示例菜谱", "description": description, "recipeIngredient": ["盐 0g"]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv", ["recipe_to_alpaca", "--in", str(source), "--out", str(target)]
    )
    recipe_to_alpaca.main()
    assert json.loads(target.read_text(encoding="utf-8"))["input"] == expected
