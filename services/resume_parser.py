"""OpenES resume (履歴書) PDF parser — rule-based coordinate extraction.

Uses PyMuPDF (fitz) to extract text blocks by position and map them
to structured fields based on the fixed OpenES PDF layout.
No AI needed — the format is standardized.
"""
import os
import logging
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# OpenES coordinate regions (Y ranges on 595×842 page)
# ──────────────────────────────────────────────

# Each region is defined as (y_min, y_max, x_threshold, field_name)
# x_threshold is used to distinguish left vs right columns
_FIELD_REGIONS = [
    # Header area
    (40,  55,  400, 'date',         'right'),   # 日付 (top-right)
    # Personal info
    (60,  80,  130, 'name_kana',    'value'),   # フリガナ value (x > 80)
    (78, 102,  130, 'name',         'value'),   # 氏名 value
    (103, 120,  130, 'birthday',    'value'),   # 生年月日 value
    (103, 120,  340, 'home_phone',  'right'),   # 自宅電話 (right col)
    (122, 138,  130, 'email',       'value'),   # e-mail value
    (122, 138,  340, 'phone',       'right'),   # 携帯電話 (right col)
    (138, 168,  130, 'address',     'value'),   # 現住所 value
    (168, 200,  130, 'vacation_address', 'value'),  # 休暇中連絡先
    # Education section
    (210, 310,    0, 'education',   'multi'),   # 学歴・職歴 rows
    # Qualifications & hobbies
    (330, 415,  250, 'qualifications', 'left'), # 保有資格 (left)
    (330, 415,  250, 'hobbies',     'right'),   #趣味・特技 (right)
    # Essay sections
    (415, 500,    0, 'academic_work', 'full'),  # 学業・ゼミ
    (498, 640,    0, 'self_pr',      'full'),   # 自己PR
    (640, 800,    0, 'gakuchika',    'full'),   # 学チカ
]


def parse_resume(file_path: str) -> dict:
    """Parse an OpenES resume PDF using coordinate-based rules.

    Args:
        file_path: Path to the resume PDF file.

    Returns:
        dict with all extracted fields including photo_path.
    """
    logger.info(f"[resume_parser] Parsing: {file_path}")

    pdf = fitz.open(file_path)
    if len(pdf) == 0:
        logger.warning("[resume_parser] Empty PDF")
        return {}

    page = pdf[0]
    pw, ph = page.rect.width, page.rect.height
    logger.info(f"[resume_parser] Page size: {pw:.0f}x{ph:.0f}")

    # ── Extract all text spans with positions ──
    page_dict = page.get_text("dict")
    spans = []
    for block in page_dict["blocks"]:
        if block["type"] != 0:  # skip image blocks
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    bbox = span["bbox"]  # (x0, y0, x1, y1)
                    spans.append({
                        "x0": bbox[0], "y0": bbox[1],
                        "x1": bbox[2], "y1": bbox[3],
                        "text": text,
                    })

    # ── Map spans to fields by Y coordinate ──
    result = {
        "name": "", "name_kana": "", "birthday": "",
        "phone": "", "home_phone": "", "email": "",
        "postcode": "", "address": "", "vacation_address": "",
        "education": [], "qualifications": "", "hobbies": "",
        "academic_work": "", "self_pr": "", "gakuchika": "",
        "date": "", "photo_path": "",
    }

    # Sort spans by Y then X
    spans.sort(key=lambda s: (s["y0"], s["x0"]))

    # Label headers to skip
    _LABEL_TEXTS = {
        'フリガナ', '氏名', 'e-mail', '現住所', '休暇中の', '連絡先',
        '携帯電話', '自宅電話', '生年月日', '年月', '学歴・職歴',
        '保有資格・スキル', '趣味・特技', '自己PR',
        '学業、ゼミ、研究室などで取り組んだ内容',
        '学生時代に最も打ち込んだこと',
    }

    # ── Personal info (top section, y < 200) ──
    for sp in spans:
        y = sp["y0"]
        x = sp["x0"]
        t = sp["text"]

        # Skip label texts
        if t in _LABEL_TEXTS:
            continue

        # Date (top-right)
        if 40 <= y <= 56 and x > 400:
            result["date"] = _append(result["date"], t)
        # Name kana
        elif 62 <= y <= 80 and x > 80 and x < 340:
            result["name_kana"] = _append(result["name_kana"], t)
        # Name
        elif 78 <= y <= 102 and x > 80 and x < 340:
            result["name"] = _append(result["name"], t)
        # Birthday
        elif 103 <= y <= 120 and x > 80 and x < 340:
            result["birthday"] = _append(result["birthday"], t)
        # Home phone
        elif 100 <= y <= 120 and x >= 340:
            result["home_phone"] = _append(result["home_phone"], t)
        # Email
        elif 122 <= y <= 140 and x > 80 and x < 340:
            result["email"] = _append(result["email"], t)
        # Phone
        elif 122 <= y <= 140 and x >= 340:
            result["phone"] = _append(result["phone"], t)
        # Address (current)
        elif 138 <= y <= 170 and x > 80:
            addr = t
            # Extract postcode
            if '〒' in addr or addr.strip().startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                import re
                pc = re.search(r'(\d{3}[-‐]?\d{4})', addr)
                if pc:
                    result["postcode"] = pc.group(1)
            result["address"] = _append(result["address"], addr)
        # Vacation address
        elif 170 <= y <= 200 and x > 80:
            addr = t
            if not result["postcode"]:
                import re
                pc = re.search(r'(\d{3}[-‐]?\d{4})', addr)
                if pc:
                    result["postcode"] = pc.group(1)
            result["vacation_address"] = _append(result["vacation_address"], addr)

    # ── Education (y ≈ 210-310) ──
    edu_spans = [s for s in spans if 210 <= s["y0"] <= 310 and s["text"] not in _LABEL_TEXTS]
    edu_rows = {}
    for sp in edu_spans:
        # Round Y to nearest 5px to group rows
        row_y = round(sp["y0"] / 10) * 10
        if row_y not in edu_rows:
            edu_rows[row_y] = {"period": "", "school": ""}
        if sp["x0"] < 140:
            edu_rows[row_y]["period"] = _append(edu_rows[row_y]["period"], sp["text"])
        else:
            edu_rows[row_y]["school"] = _append(edu_rows[row_y]["school"], sp["text"])

    result["education"] = [v for v in edu_rows.values() if v["period"] or v["school"]]

    # ── Qualifications / Hobbies (y ≈ 330-415) ──
    for sp in spans:
        y, x, t = sp["y0"], sp["x0"], sp["text"]
        if t in _LABEL_TEXTS:
            continue
        if 330 <= y <= 415:
            if x < 250:
                result["qualifications"] = _append(result["qualifications"], t)
            else:
                result["hobbies"] = _append(result["hobbies"], t)

    # ── Essay sections ──
    for sp in spans:
        y, t = sp["y0"], sp["text"]
        if t in _LABEL_TEXTS:
            continue
        if 415 <= y <= 498:
            result["academic_work"] = _append(result["academic_work"], t)
        elif 498 <= y <= 640:
            result["self_pr"] = _append(result["self_pr"], t)
        elif 640 <= y <= 800:
            result["gakuchika"] = _append(result["gakuchika"], t)

    # ── Extract portrait photo ──
    photo_path = _extract_photo(pdf, page, file_path)
    if photo_path:
        result["photo_path"] = photo_path

    pdf.close()

    # Clean up fields
    for key in ("address", "vacation_address"):
        if result[key]:
            result[key] = result[key].strip()
            # Remove leading 〒 + postcode from address text
            import re
            result[key] = re.sub(r'^〒\s*\d{3}[-‐]?\d{4}\s*', '', result[key]).strip()

    logger.info(f"[resume_parser] Parsed: name={result['name']}, "
                f"email={result['email']}, edu={len(result['education'])} entries, "
                f"photo={'yes' if result['photo_path'] else 'no'}")
    return result


def _append(existing: str, new: str) -> str:
    """Append text with space separator."""
    if not existing:
        return new
    return existing + " " + new


def _extract_photo(pdf, page, file_path: str) -> str:
    """Extract the portrait photo from the resume.

    Identifies the portrait by looking for an image where height > width
    (standard ID photo aspect ratio).
    """
    from config import Config

    images = page.get_images(full=True)
    for img in images:
        xref = img[0]
        try:
            img_data = pdf.extract_image(xref)
            w, h = img_data["width"], img_data["height"]
            ext = img_data["ext"]

            # Portrait photo: taller than wide, reasonable size
            if h > w and h >= 200:
                photo_dir = os.path.join(Config.BASE_DIR, 'data', 'uploads', 'photos')
                os.makedirs(photo_dir, exist_ok=True)

                basename = os.path.splitext(os.path.basename(file_path))[0]
                photo_filename = f"resume_photo_{basename}.{ext}"
                photo_path = os.path.join(photo_dir, photo_filename)

                with open(photo_path, 'wb') as f:
                    f.write(img_data["image"])

                logger.info(f"[resume_parser] Photo extracted: {w}x{h} → {photo_path}")
                return photo_path
        except Exception as e:
            logger.debug(f"[resume_parser] Image extraction error: {e}")

    return ""


def is_resume_pdf(file_path: str) -> bool:
    """Quick check if a PDF is likely an OpenES resume.

    Looks for characteristic labels in the first page text.
    """
    try:
        pdf = fitz.open(file_path)
        if len(pdf) == 0:
            return False
        text = pdf[0].get_text()
        pdf.close()

        resume_markers = ['フリガナ', '氏名', '学歴・職歴', '自己PR', '生年月日']
        matches = sum(1 for m in resume_markers if m in text)
        return matches >= 3
    except Exception:
        return False
