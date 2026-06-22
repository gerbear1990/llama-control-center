import importlib.util
from pathlib import Path

# The launcher lives in start-lcc.py, whose hyphen makes it unimportable by name,
# so load it from disk and reuse its stop_server().
_start_lcc = Path(__file__).resolve().parent / "start-lcc.py"
_spec = importlib.util.spec_from_file_location("lcc_launcher", _start_lcc)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
stop_server = _module.stop_server

if __name__ == "__main__":
    raise SystemExit(stop_server())
