"""
Testes unitários para FileStorage.
Usa tmp_path do pytest para isolamento total.
"""
import pytest

from storage.file_storage import FileStorage, StorageError

SESSION = "test-session-123"


@pytest.fixture
def storage(tmp_path):
    return FileStorage(base_dir=str(tmp_path))


# ─── write_file ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_file_creates_file(storage, tmp_path):
    meta = await storage.write_file(SESSION, "doc.md", "# Olá")
    assert meta.filename == "doc.md"
    assert meta.session_id == SESSION
    assert meta.download_url == f"/files/{SESSION}/doc.md"
    assert (tmp_path / SESSION / "doc.md").read_text(encoding="utf-8") == "# Olá"


@pytest.mark.asyncio
async def test_write_file_overwrites_existing(storage, tmp_path):
    await storage.write_file(SESSION, "doc.md", "conteúdo 1")
    await storage.write_file(SESSION, "doc.md", "conteúdo 2")
    assert (tmp_path / SESSION / "doc.md").read_text(encoding="utf-8") == "conteúdo 2"


@pytest.mark.asyncio
async def test_write_file_rejects_invalid_extension(storage):
    with pytest.raises(StorageError, match="Extensão"):
        await storage.write_file(SESSION, "script.sh", "rm -rf /")


@pytest.mark.asyncio
async def test_write_file_rejects_exe(storage):
    with pytest.raises(StorageError, match="Extensão"):
        await storage.write_file(SESSION, "malware.exe", "data")


@pytest.mark.asyncio
async def test_write_file_rejects_py(storage):
    with pytest.raises(StorageError, match="Extensão"):
        await storage.write_file(SESSION, "hack.py", "import os")


@pytest.mark.asyncio
async def test_write_file_rejects_invalid_filename(storage):
    with pytest.raises(StorageError, match="inválido"):
        await storage.write_file(SESSION, "../../etc/passwd", "data")


@pytest.mark.asyncio
async def test_write_file_rejects_spaces_in_name(storage):
    with pytest.raises(StorageError, match="inválido"):
        await storage.write_file(SESSION, "meu arquivo.md", "data")


@pytest.mark.asyncio
async def test_write_file_rejects_oversized_content(storage):
    big = "x" * (1 * 1024 * 1024 + 1)
    with pytest.raises(StorageError, match="1 MB"):
        await storage.write_file(SESSION, "big.md", big)


@pytest.mark.asyncio
async def test_write_file_allows_json(storage):
    meta = await storage.write_file(SESSION, "data.json", '{"key": "value"}')
    assert meta.filename == "data.json"


@pytest.mark.asyncio
async def test_write_file_allows_txt(storage):
    meta = await storage.write_file(SESSION, "notes.txt", "anotação")
    assert meta.filename == "notes.txt"


# ─── append_to_file ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_to_file_creates_if_not_exists(storage, tmp_path):
    meta = await storage.append_to_file(SESSION, "log.md", "linha 1\n")
    assert (tmp_path / SESSION / "log.md").read_text() == "linha 1\n"


@pytest.mark.asyncio
async def test_append_to_file_appends_content(storage, tmp_path):
    await storage.append_to_file(SESSION, "log.md", "linha 1\n")
    await storage.append_to_file(SESSION, "log.md", "linha 2\n")
    content = (tmp_path / SESSION / "log.md").read_text()
    assert content == "linha 1\nlinha 2\n"


# ─── read_file ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_file_returns_content(storage):
    await storage.write_file(SESSION, "doc.md", "conteúdo esperado")
    result = await storage.read_file(SESSION, "doc.md")
    assert result == "conteúdo esperado"


@pytest.mark.asyncio
async def test_read_file_raises_for_missing(storage):
    with pytest.raises(StorageError, match="não encontrado"):
        await storage.read_file(SESSION, "inexistente.md")


# ─── list_files ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_files_empty_session(storage):
    files = await storage.list_files("sessao-vazia")
    assert files == []


@pytest.mark.asyncio
async def test_list_files_returns_all(storage):
    await storage.write_file(SESSION, "a.md", "a")
    await storage.write_file(SESSION, "b.txt", "b")
    await storage.write_file(SESSION, "c.json", "{}")
    files = await storage.list_files(SESSION)
    names = {f.filename for f in files}
    assert names == {"a.md", "b.txt", "c.json"}


@pytest.mark.asyncio
async def test_list_files_metadata_fields(storage):
    await storage.write_file(SESSION, "doc.md", "# Título")
    files = await storage.list_files(SESSION)
    assert len(files) == 1
    f = files[0]
    assert f.download_url == f"/files/{SESSION}/doc.md"
    assert f.size_bytes > 0
    assert f.created_at  # ISO 8601 não vazio


# ─── resolve_for_serving ─────────────────────────────────────────────────────

def test_resolve_for_serving_blocks_traversal(storage):
    with pytest.raises(StorageError, match="(fora|não encontrado)"):
        storage.resolve_for_serving("../../etc/passwd")


def test_resolve_for_serving_ok(storage, tmp_path):
    (tmp_path / SESSION).mkdir()
    (tmp_path / SESSION / "doc.md").write_text("ok")
    resolved = storage.resolve_for_serving(f"{SESSION}/doc.md")
    assert resolved.name == "doc.md"
