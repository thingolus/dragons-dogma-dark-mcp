"""Direct PE inventory baseline, without MCP imports or server startup."""

import hashlib
import json
import sys
from pathlib import Path

import pefile


def main():
    raw = Path(sys.argv[1]).read_bytes()
    with pefile.PE(data=raw, fast_load=True) as pe:
        print(
            json.dumps(
                {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                    "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
                    "architecture": "x86" if pe.FILE_HEADER.Machine == 0x14C else "other",
                }
            )
        )


if __name__ == "__main__":
    main()
