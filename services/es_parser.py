"""ES (Entry Sheet) file parser — extract and structure text from uploaded files.

Supports:
- PDF  → PyMuPDF (fitz)
- DOCX → python-docx
- Images (JPG/PNG) → Gemini Vision API for OCR

After raw text extraction, uses LLM to structure the content into
self_pr, motivation, strengths, and experience fields.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Raw text extractors
# ──────────────────────────────────────────────

def _extract_pdf(file_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF (fitz).

    Switched from pdfplumber to PyMuPDF because pdfplumber hangs
    on certain OpenES resume PDFs.
    """
    import fitz
    texts = []
    pdf = fitz.open(file_path)
    for page in pdf:
        text = page.get_text()
        if text and text.strip():
            texts.append(text)
    pdf.close()
    result = '\n'.join(texts)
    logger.info(f"[es_parser] PDF extracted: {len(result)} chars from {len(texts)} pages")
    return result


def _extract_docx(file_path: str) -> str:
    """Extract text from a Word (.docx) file."""
    from docx import Document
    doc = Document(file_path)
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    result = '\n'.join(texts)
    logger.info(f"[es_parser] DOCX extracted: {len(result)} chars from {len(texts)} paragraphs")
    return result


def _extract_image(file_path: str) -> str:
    """Extract text from an image using Gemini Vision API (OCR)."""
    import base64
    import urllib.request

    api_key = os.getenv('GEMINI_API_KEY', '')
    if not api_key:
        logger.warning("[es_parser] No GEMINI_API_KEY for image OCR")
        return ''

    # Read and encode image
    with open(file_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')

    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
    mime_type = mime_map.get(ext, 'image/jpeg')

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3-flash-preview:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"text": "この画像に書かれている日本語テキストをすべて読み取ってください。構造を保ったまま文字起こししてください。"},
                {"inline_data": {"mime_type": mime_type, "data": image_data}}
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
    }).encode('utf-8')

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            candidates = data.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                if parts:
                    text = parts[0].get('text', '')
                    logger.info(f"[es_parser] Image OCR extracted: {len(text)} chars")
                    return text
    except Exception as e:
        logger.warning(f"[es_parser] Image OCR failed: {e}")

    return ''


# ──────────────────────────────────────────────
# Text extraction dispatcher
# ──────────────────────────────────────────────

def extract_text(file_path: str) -> str:
    """Extract raw text from a file based on its extension.

    Supported: .pdf, .docx, .jpg, .jpeg, .png
    Returns the raw extracted text, or empty string on failure.
    """
    ext = os.path.splitext(file_path)[1].lower()
    extractors = {
        '.pdf': _extract_pdf,
        '.docx': _extract_docx,
        '.jpg': _extract_image,
        '.jpeg': _extract_image,
        '.png': _extract_image,
    }

    extractor = extractors.get(ext)
    if not extractor:
        logger.warning(f"[es_parser] Unsupported file type: {ext}")
        return ''

    try:
        return extractor(file_path)
    except Exception as e:
        logger.exception(f"[es_parser] Extraction failed for {file_path}: {e}")
        return ''


# ──────────────────────────────────────────────
# AI structuring
# ──────────────────────────────────────────────

from ai.prompt_loader import get_prompt

_DEFAULT_STRUCTURE_PROMPT = """以下はES(エントリーシート)または履歴書から抽出されたテキストです。
これを構造化して、以下のJSON形式で返してください。

{{"self_pr": "自己PRのテキスト", "motivation": "志望動機のテキスト(あれば)", "strengths": ["強み1", "強み2"], "experience": "学歴・職歴・活動のサマリー"}}

該当する内容がない場合は空文字列または空リストにしてください。
テキスト全体から推測して埋めてください。

--- 抽出テキスト ---
{text}
"""

def _get_structure_prompt() -> str:
    return get_prompt('es_parser', _DEFAULT_STRUCTURE_PROMPT)


def structure_text(raw_text: str) -> dict:
    """Use LLM to structure raw ES text into self_pr, motivation, etc.

    Returns dict with keys: self_pr, motivation, strengths, experience
    """
    from ai import call_llm, is_ai_configured, clean_json_response
    import re

    if not raw_text.strip():
        return {'self_pr': '', 'motivation': '', 'strengths': [], 'experience': ''}

    if not is_ai_configured():
        # Return raw text as self_pr if AI is not available
        return {'self_pr': raw_text, 'motivation': '', 'strengths': [], 'experience': ''}

    prompt = _get_structure_prompt().format(text=raw_text[:3000])

    try:
        raw = call_llm(prompt)
        cleaned = clean_json_response(raw)

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # Regex fallback
            self_pr_m = re.search(r'"self_pr"\s*:\s*"([^"]*)', cleaned)
            motivation_m = re.search(r'"motivation"\s*:\s*"([^"]*)', cleaned)
            experience_m = re.search(r'"experience"\s*:\s*"([^"]*)', cleaned)
            strengths_m = re.findall(r'"strengths"\s*:\s*\[([^\]]*)\]', cleaned)

            result = {
                'self_pr': self_pr_m.group(1) if self_pr_m else raw_text[:500],
                'motivation': motivation_m.group(1) if motivation_m else '',
                'experience': experience_m.group(1) if experience_m else '',
                'strengths': [],
            }
            if strengths_m:
                result['strengths'] = re.findall(r'"([^"]+)"', strengths_m[0])

        # Ensure all keys exist
        for key in ['self_pr', 'motivation', 'experience']:
            result.setdefault(key, '')
        result.setdefault('strengths', [])

        logger.info(f"[es_parser] Structured: self_pr={len(result['self_pr'])}chars, "
                     f"strengths={len(result['strengths'])}")
        return result

    except Exception as e:
        logger.warning(f"[es_parser] Structuring failed: {e}")
        return {'self_pr': raw_text[:500], 'motivation': '', 'strengths': [], 'experience': ''}


# ──────────────────────────────────────────────
# Main public API
# ──────────────────────────────────────────────

def parse_es_file(file_path: str) -> dict:
    """Parse an ES file end-to-end.

    If the file is an OpenES resume, uses coordinate-based parsing.
    Otherwise, extracts text and structures with AI.

    Args:
        file_path: Absolute path to the uploaded file.

    Returns:
        dict with parsed fields.
    """
    ext = os.path.splitext(file_path)[1].lower()

    # Check if this is a resume PDF (OpenES format)
    if ext == '.pdf':
        from services.resume_parser import is_resume_pdf
        if is_resume_pdf(file_path):
            logger.info(f"[es_parser] Detected OpenES resume, using resume_parser")
            from services.resume_parser import parse_resume
            resume_data = parse_resume(file_path)
            # Return in a format compatible with the existing ES pipeline
            raw_text = extract_text(file_path)
            return {
                'raw_text': raw_text,
                'self_pr': resume_data.get('self_pr', ''),
                'motivation': '',
                'strengths': [],
                'experience': resume_data.get('academic_work', ''),
                'is_resume': True,
                'resume_data': resume_data,
            }

    raw_text = extract_text(file_path)
    if not raw_text:
        logger.warning(f"[es_parser] No text extracted from {file_path}")
        return {
            'raw_text': '', 'self_pr': '', 'motivation': '',
            'strengths': [], 'experience': ''
        }

    structured = structure_text(raw_text)
    structured['raw_text'] = raw_text
    return structured


def save_es_to_db(file_path: str, title: str, parsed_data: dict, photo_path: str = '') -> int:
    """Save parsed ES data to the database.

    Returns the document ID.
    """
    from db.es import create_es_document

    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
    doc_id = create_es_document({
        'title': title,
        'file_path': file_path,
        'file_type': ext,
        'raw_text': parsed_data.get('raw_text', ''),
        'parsed_data': json.dumps(parsed_data, ensure_ascii=False),
        'photo_path': photo_path,
    })
    logger.info(f"[es_parser] Saved to DB: id={doc_id}, title={title}")
    return doc_id
