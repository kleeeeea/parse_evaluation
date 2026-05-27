from pathlib import Path

import fitz

SCRIPT_DIR = Path(__file__).parent
SOURCE_PDF = SCRIPT_DIR / "praxis_core_pp copy 2.pdf"
OUTPUT_DIR = SCRIPT_DIR / "splited"


def split_pdf(source: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(source)
    width = len(str(doc.page_count))
    stem = source.stem
    for i in range(doc.page_count):
        single = fitz.open()
        single.insert_pdf(doc, from_page=i, to_page=i)
        out_path = output_dir / f"{stem}_p{str(i + 1).zfill(width)}.pdf"
        single.save(out_path)
        single.close()
        print(f"wrote {out_path}")
    doc.close()


if __name__ == "__main__":
    split_pdf(SOURCE_PDF, OUTPUT_DIR)
