import hashlib
from pathlib import Path

from eggy_map_api.graph import build_reference_graph
from eggy_map_api.models import FileRecord, MapSnapshot


def record(name: str, decoded):
    return FileRecord(
        relative_path=name,
        size=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        blake2b=hashlib.blake2b(b"").hexdigest(),
        mode=0o600,
        uid=1,
        gid=1,
        raw=b"",
        decoded=decoded,
    )


def test_reference_graph_includes_mapping_keys() -> None:
    unit = {
        b"unit": {
            1_000_000_007: {
                b"unit_id": 1_000_000_007,
                b"eid": 7,
                b"parent_unit_id": 0,
                b"children_unit_id": [],
            }
        }
    }
    snapshot = MapSnapshot(
        root=Path("/synthetic"),
        files={
            "unit.mm": record("unit.mm", unit),
            "uniteditor.mm": record("uniteditor.mm", {1_000_000_007: {}}),
        },
        format_fingerprint="synthetic",
    )
    graph = build_reference_graph(snapshot)
    assert any(
        ref.file == "uniteditor.mm" and "<key:" in ref.path
        for ref in graph.refs_to(1_000_000_007)
    )
