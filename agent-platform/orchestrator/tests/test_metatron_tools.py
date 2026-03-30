"""
Testes unitários para as tools do Metatron.
"""
import pytest

from storage.file_storage import FileStorage
import agents.metatron.tools as metatron_tools

SESSION = "test-session-abc"


@pytest.fixture(autouse=True)
def patch_storage(tmp_path, monkeypatch):
    """Substitui o singleton file_storage por uma instância com tmp_path."""
    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(metatron_tools, "file_storage", fs)
    return fs


# ─── write_file ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_write_file_success():
    result = await metatron_tools.execute_tool(
        "write_file",
        {"filename": "nota.md", "content": "# Nota"},
        SESSION,
    )
    assert result["success"] is True
    assert result["filename"] == "nota.md"
    assert result["download_url"] == f"/files/{SESSION}/nota.md"
    assert result["file_created"] is True


@pytest.mark.asyncio
async def test_execute_write_file_invalid_ext():
    result = await metatron_tools.execute_tool(
        "write_file",
        {"filename": "hack.sh", "content": "rm -rf /"},
        SESSION,
    )
    assert "error" in result
    assert "Extensão" in result["error"]


# ─── create_report ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_create_report_generates_markdown(tmp_path, monkeypatch):
    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(metatron_tools, "file_storage", fs)

    result = await metatron_tools.execute_tool(
        "create_report",
        {
            "title": "Incidente OOMKilled",
            "sections": [
                {"heading": "Descrição", "content": "Pod reiniciou por falta de memória."},
                {"heading": "Ação Tomada", "content": "Aumentamos réplicas para 2."},
            ],
            "tags": ["k8s", "oomkilled"],
        },
        SESSION,
    )

    assert result["success"] is True
    assert result["filename"].endswith(".md")
    assert "relatorio-" in result["filename"]
    # Verifica conteúdo gerado
    content = await fs.read_file(SESSION, result["filename"])
    assert "# Incidente OOMKilled" in content
    assert "## Descrição" in content
    assert "## Ação Tomada" in content
    assert "`k8s`" in content


# ─── append_to_file ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_append_to_file():
    await metatron_tools.execute_tool(
        "write_file",
        {"filename": "log.md", "content": "linha 1\n"},
        SESSION,
    )
    result = await metatron_tools.execute_tool(
        "append_to_file",
        {"filename": "log.md", "content": "linha 2\n"},
        SESSION,
    )
    assert result["success"] is True
    assert result["file_created"] is False


# ─── list_files ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_list_files_empty():
    result = await metatron_tools.execute_tool("list_files", {}, "sessao-nova")
    assert result["total"] == 0
    assert result["files"] == []


@pytest.mark.asyncio
async def test_execute_list_files_after_writes():
    await metatron_tools.execute_tool("write_file", {"filename": "a.md", "content": "a"}, SESSION)
    await metatron_tools.execute_tool("write_file", {"filename": "b.txt", "content": "b"}, SESSION)
    result = await metatron_tools.execute_tool("list_files", {}, SESSION)
    assert result["total"] == 2
    names = {f["filename"] for f in result["files"]}
    assert names == {"a.md", "b.txt"}


# ─── read_file ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_read_file():
    await metatron_tools.execute_tool(
        "write_file", {"filename": "doc.md", "content": "conteúdo"}, SESSION
    )
    result = await metatron_tools.execute_tool("read_file", {"filename": "doc.md"}, SESSION)
    assert result["content"] == "conteúdo"
    assert result["filename"] == "doc.md"


@pytest.mark.asyncio
async def test_execute_read_file_not_found():
    result = await metatron_tools.execute_tool("read_file", {"filename": "nao-existe.md"}, SESSION)
    assert "error" in result


# ─── unknown tool ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_unknown_tool():
    result = await metatron_tools.execute_tool("ferramenta_inexistente", {}, SESSION)
    assert "error" in result
    assert "Tool desconhecida" in result["error"]
