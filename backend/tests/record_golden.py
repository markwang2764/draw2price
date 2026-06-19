"""Record golden snapshots for regression tests."""

from pathlib import Path
import json


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "fixtures" / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "README.json").write_text(json.dumps({"status": "placeholder"}, ensure_ascii=False, indent=2), encoding="utf-8")
