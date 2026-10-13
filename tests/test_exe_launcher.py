import importlib.util
import socket
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sgpt_exe", Path(__file__).parent.parent / "packaging" / "sgpt_exe.py")
sgpt_exe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sgpt_exe)


def test_data_folder_is_in_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert sgpt_exe.data_folder() == tmp_path / "SGPT"  # no Documents folder
    (tmp_path / "Documents").mkdir()
    assert sgpt_exe.data_folder() == tmp_path / "Documents" / "SGPT"
    assert (tmp_path / "Documents" / "SGPT").is_dir()


def test_free_port_skips_a_busy_port():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert sgpt_exe.free_port(port, tries=5) != port
