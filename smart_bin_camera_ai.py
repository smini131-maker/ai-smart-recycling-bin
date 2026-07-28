from __future__ import annotations

"""Primary camera AI module.

The source is stored in deterministic text parts so GitHub's connected upload
path can publish the complete Raspberry Pi implementation without altering its
contents. The parts are concatenated byte-for-byte and executed as this module.
"""

from pathlib import Path

_PARTS_DIR = Path(__file__).resolve().parent / "source_parts"
_PARTS = tuple(
    sorted(_PARTS_DIR.glob("smart_bin_camera_ai.part*.txt"))
)

if len(_PARTS) != 5:
    raise RuntimeError(
        "Primary camera AI source parts are incomplete: "
        f"expected 5, found {len(_PARTS)}"
    )

_SOURCE = "".join(
    part.read_text(encoding="utf-8")
    for part in _PARTS
)

exec(
    compile(
        _SOURCE,
        str(Path(__file__).with_name("smart_bin_camera_ai_source.py")),
        "exec",
    ),
    globals(),
    globals(),
)
