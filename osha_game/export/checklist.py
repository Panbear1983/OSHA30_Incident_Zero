"""Word / PDF export of Inspect checklists (Phase 3 fills this in).
Contract: main(argv) -> int for the CLI; export_module(con, module_id, out_dir, pdf=True) ->
list[Path] for the screen."""
from pathlib import Path


def export_module(con, module_id: int, out_dir: Path, pdf: bool = True) -> list[Path]:
    raise NotImplementedError("Phase 3")


def main(argv: list[str]) -> int:
    print("Checklist export isn't wired yet.")
    return 0
