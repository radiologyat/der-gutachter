

def test_unblock_bundle_removes_only_zone_streams_of_program_files(tmp_path, monkeypatch):
    from gutachten import config, desktop

    for n in ("a.dll", "b.pyd", "DerGutachter.exe", "notes.txt"):
        (tmp_path / n).write_bytes(b"x")
    removed = []
    monkeypatch.setattr(desktop.os, "name", "nt")
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(desktop.os, "remove", lambda p: removed.append(p))
    assert desktop.unblock_bundle(tmp_path) == 3
    assert all(p.endswith(":Zone.Identifier") for p in removed)
    assert not any("notes.txt" in p for p in removed)


def test_unblock_bundle_is_noop_outside_frozen_windows(tmp_path):
    from gutachten import desktop

    (tmp_path / "a.dll").write_bytes(b"x")
    assert desktop.unblock_bundle(tmp_path) == 0


def test_save_download_writes_file_with_server_filename(tmp_path, monkeypatch):
    import httpx

    from gutachten import desktop

    class Resp:
        content = b"PK-docx"
        headers = {"content-disposition":
                   "attachment; filename*=utf-8''Gutachten-final-20261116.docx"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "get", lambda url, timeout: Resp())
    out = desktop.save_download("http://127.0.0.1:1", "/api/cases/x/export.docx", None,
                                target_dir=tmp_path)
    assert out.endswith("Gutachten-final-20261116.docx")
    assert (tmp_path / "Gutachten-final-20261116.docx").read_bytes() == b"PK-docx"
    import pytest

    with pytest.raises(ValueError):
        desktop.save_download("http://127.0.0.1:1", "http://evil/x", None, target_dir=tmp_path)


def test_reap_orphans_only_touches_our_model_server(monkeypatch):
    import psutil

    from gutachten import config
    from gutachten.llm import server as srv

    killed = []

    class P:
        def __init__(self, pid, name, cmd):
            self.pid, self.info = pid, {"name": name, "cmdline": cmd}

        def terminate(self):
            killed.append(self.pid)

        def wait(self, t):
            return 0

    ours = ["llama-server", "--model", str(config.MODELS_DIR / "gguf" / "m.gguf"),
            "--port", str(config.LLAMA_PORT)]
    procs = [P(1, "llama-server", ours),
             P(2, "llama-server", ["llama-server", "--model", "/elsewhere/m.gguf",
                                   "--port", str(config.LLAMA_PORT)]),   # someone else's
             P(3, "python", ["python", "x.py"]),
             P(4, "llama-server", ours)]                                  # our own child
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: procs)
    assert srv.reap_orphans(keep_pid=4) == 1 and killed == [1]


def test_idle_tracking():
    from gutachten.llm.server import LlamaServer

    s = LlamaServer()
    s.last_used -= 100
    assert s.idle_seconds() >= 100 and not s.owns_running()
    s.touch()
    assert s.idle_seconds() < 5
