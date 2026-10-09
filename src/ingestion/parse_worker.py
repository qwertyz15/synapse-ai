"""Parses one uploaded file in its own process and prints the pages as JSON (see parse_untrusted)."""

import json
import sys
from pathlib import Path


def main() -> None:
    path, file_type, memory_bytes = sys.argv[1], sys.argv[2], int(sys.argv[3])
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ImportError, ValueError, OSError):
        pass

    from ingestion.models import SourceDocument
    from ingestion.parsers import parse

    try:
        pages = parse(SourceDocument(path, Path(path), file_type, ""))
    except MemoryError:
        json.dump({"error": "Needs too much memory to read"}, sys.stdout)
        return
    except Exception as e:
        json.dump({"error": str(e) or type(e).__name__}, sys.stdout)
        return
    json.dump({"pages": [[p.text, p.page] for p in pages]}, sys.stdout)


if __name__ == "__main__":
    main()
