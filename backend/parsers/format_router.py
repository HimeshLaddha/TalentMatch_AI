import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def route_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """
    Detects file format and routes to the correct parser.
    Returns a list of candidate dicts (always a list — even for
    single-candidate uploads, return [candidate]).

    Detection order:
      1. fname.endswith(".jsonl.gz") -> jsonlgz_parser
      2. fname.endswith(".json")     -> json_parser
      3. fname.endswith(".pdf") OR magic bytes b"%PDF" -> pdf_parser
      4. fname.endswith(".docx") OR magic bytes b"PK\\x03\\x04" (zip signature) -> docx_parser
      5. Otherwise: raise ValueError
    """
    logger.info("Routing file: filename=%s, size=%d bytes", filename, len(file_bytes))

    # Normalise once — handles "Resume.PDF", "data.JSON", "CV.DOCX", etc.
    fname = filename.lower().strip()

    if fname.endswith(".jsonl.gz"):
        from parsers.extractors import jsonlgz_parser
        return jsonlgz_parser(file_bytes)

    if fname.endswith(".json"):
        from parsers.extractors import json_parser
        return json_parser(file_bytes)

    if fname.endswith(".pdf") or file_bytes[:4] == b"%PDF":
        from parsers.extractors import pdf_parser
        return pdf_parser(file_bytes)

    if fname.endswith(".docx") or file_bytes[:4] == b"PK\x03\x04":
        from parsers.extractors import docx_parser
        return docx_parser(file_bytes)

    raise ValueError(
        f"Unsupported file type: {filename}. "
        f"Accepted: .pdf .docx .json .jsonl.gz"
    )
