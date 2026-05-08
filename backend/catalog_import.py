"""
AI-powered Supplier Catalog Import.

Pipeline:
1. Decode upload (PDF or image base64) -> list of base64 page images
2. For each page image -> Gemini 3 Flash extracts structured medicine entries (JSON)
3. Normalize names (Arabic-aware) -> dedupe within batch
4. For each item:
   - check `catalog_corrections` (learning) -> direct map
   - else fuzzy-match against supplier's existing products + canonical names
   - if confidence ambiguous -> ask Gemini "are these the same drug?" (switching)
5. Persist `import_items` with confidence + match_status (auto / needs_review)
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import pypdfium2 as pdfium
from PIL import Image
from rapidfuzz import fuzz, process as rfprocess

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# ---- Arabic / English normalization ----
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = _DIACRITICS.sub("", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
    s = s.replace("ة", "ه")
    # Common pharma synonyms
    s = re.sub(r"\bgms?\b", "g", s)       # gm/gms -> g
    s = re.sub(r"\bgrams?\b", "g", s)
    s = re.sub(r"\bمل\b", "ml", s)
    s = re.sub(r"\bملغم?\b", "mg", s)
    s = re.sub(r"\bملي\s*غرام\b", "mg", s)
    s = re.sub(r"\bغرام\b", "g", s)
    s = re.sub(r"\btab(let)?s?\b", "tab", s)
    s = re.sub(r"\bcap(sule)?s?\b", "cap", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def canonical_key(name: str, strength: str | None = None,
                  dosage_form: str | None = None) -> str:
    parts = [normalize_text(name)]
    if strength:
        parts.append(normalize_text(strength))
    if dosage_form:
        parts.append(normalize_text(dosage_form))
    return " ".join(p for p in parts if p)


# ---- PDF/Image decoding ----
def decode_to_page_images(file_b64: str, file_type: str) -> list[str]:
    """Return list of base64 JPEG images (one per page for PDF, one for image)."""
    raw = base64.b64decode(file_b64)
    pages: list[str] = []
    ft = (file_type or "").lower()
    if ft in ("pdf", "application/pdf"):
        pdf = pdfium.PdfDocument(raw)
        for i in range(min(len(pdf), 12)):  # safety cap: max 12 pages per upload
            page = pdf[i]
            pil_image = page.render(scale=2.0).to_pil()
            buf = io.BytesIO()
            pil_image.convert("RGB").save(buf, format="JPEG", quality=85)
            pages.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    else:
        # Image: re-encode as JPEG to ensure compatibility
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        pages.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return pages


# ---- Gemini extraction ----
EXTRACTION_PROMPT = """أنت محلل خبير لقوائم أسعار صيدلانية (price lists / catalogs).
استخرج كل دواء مذكور في الصورة وأرجع JSON ARRAY فقط (بدون أي شرح).
لكل دواء أرجع object بالحقول التالية:
{
  "name": "اسم الدواء بدون التركيز",
  "strength": "التركيز (مثل 500mg, 1g, 100ml) أو null",
  "dosage_form": "الشكل (tab, cap, syrup, injection, cream) أو null",
  "manufacturer": "الشركة الصانعة أو null",
  "price": رقم السعر بالدينار العراقي (أو 0),
  "quantity": رقم الكمية المتاحة (أو 0)
}
قواعد:
- إذا كان الجدول يحوي عمود "Available" أو "الكمية"، استخدمه لـ quantity
- إذا كان السعر بعملة أخرى، اتركه كما هو رقمياً
- لا تخمّن قيماً غير ظاهرة (استخدم null أو 0)
- أرجع JSON فقط، يبدأ بـ [ وينتهي بـ ]
"""


async def extract_items_from_image(image_b64: str) -> list[dict]:
    """Call Gemini 3 Flash on a single page image, return parsed list of items."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"catalog-{uuid.uuid4()}",
            system_message="أنت مساعد متخصص في استخراج بيانات الأدوية من قوائم الأسعار.",
        ).with_model("gemini", "gemini-3-flash-preview")

        msg = UserMessage(text=EXTRACTION_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])
        resp = await chat.send_message(msg)
        text = (resp or "").strip()
        # Strip code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Find first [ to last ]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        items = json.loads(text[start:end + 1])
        if not isinstance(items, list):
            return []
        cleaned: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = (it.get("name") or "").strip()
            if not name:
                continue
            cleaned.append({
                "name": name,
                "strength": (it.get("strength") or None) or None,
                "dosage_form": (it.get("dosage_form") or None) or None,
                "manufacturer": (it.get("manufacturer") or None) or None,
                "price": float(it.get("price") or 0) if str(it.get("price") or "").replace(".", "", 1).replace("-", "", 1).isdigit() else 0.0,
                "quantity": int(it.get("quantity") or 0) if str(it.get("quantity") or "").isdigit() else 0,
            })
        return cleaned
    except Exception:
        logger.exception("extraction failed")
        return []


# ---- Smart matching ----
async def gemini_validate_match(text_a: str, text_b: str) -> float:
    """Ask Gemini if two pharmaceutical names refer to the same product. Returns confidence 0..1."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"match-{uuid.uuid4()}",
            system_message="أنت خبير صيدلة. قارن أسماء الأدوية وأرجع JSON فقط.",
        ).with_model("gemini", "gemini-3-flash-preview")

        prompt = (
            f'هل هذان نفس الدواء؟\nA: "{text_a}"\nB: "{text_b}"\n'
            'أرجع JSON فقط: {"same": true|false, "confidence": 0.0-1.0}'
        )
        resp = await chat.send_message(UserMessage(text=prompt))
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (resp or "").strip())
        m = re.search(r"\{[^}]+\}", text)
        if not m:
            return 0.5
        data = json.loads(m.group(0))
        same = bool(data.get("same"))
        conf = float(data.get("confidence") or 0)
        return conf if same else 1.0 - conf
    except Exception:
        return 0.5


async def smart_match(
    extracted_key: str,
    candidates: list[str],
    db_corrections: dict[str, str] | None = None,
) -> tuple[str | None, float]:
    """
    Returns (best_canonical_or_None, confidence 0..1).
    1. Check learned corrections (perfect override).
    2. RapidFuzz token_sort against candidates.
    3. If 70 < score < 90 -> Gemini re-validation (the "switching" layer).
    """
    if db_corrections and extracted_key in db_corrections:
        return db_corrections[extracted_key], 1.0
    if not candidates:
        return None, 0.0
    best = rfprocess.extractOne(extracted_key, candidates, scorer=fuzz.token_set_ratio)
    if not best:
        return None, 0.0
    match_str, score, _ = best
    conf = score / 100.0
    if conf >= 0.90:
        return match_str, conf
    if conf < 0.55:
        return None, conf  # too weak, treat as new
    # Ambiguous zone -> Gemini validation
    gemini_conf = await gemini_validate_match(extracted_key, match_str)
    if gemini_conf >= 0.7:
        return match_str, gemini_conf
    return None, max(conf, gemini_conf)


# ---- Main job processor ----
async def process_import_job(db, job_id: str) -> None:
    """Background task: read job, extract, match, persist items, update status."""
    job = await db.import_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        return
    try:
        await db.import_jobs.update_one({"id": job_id}, {"$set": {"status": "processing", "progress": 5}})

        page_images = decode_to_page_images(job["file_b64"], job["file_type"])
        await db.import_jobs.update_one({"id": job_id},
                                        {"$set": {"progress": 15, "page_count": len(page_images)}})

        # Extract from each page
        all_extracted: list[dict] = []
        for idx, img_b64 in enumerate(page_images):
            items = await extract_items_from_image(img_b64)
            all_extracted.extend(items)
            done = 15 + int(((idx + 1) / max(1, len(page_images))) * 60)
            await db.import_jobs.update_one({"id": job_id}, {"$set": {"progress": done}})

        # Dedupe within batch by canonical key
        dedup: dict[str, dict] = {}
        for it in all_extracted:
            ck = canonical_key(it["name"], it.get("strength"), it.get("dosage_form"))
            if not ck:
                continue
            if ck in dedup:
                # merge: keep cheaper price, sum quantity
                prev = dedup[ck]
                if it.get("price") and (not prev.get("price") or it["price"] < prev["price"]):
                    prev["price"] = it["price"]
                prev["quantity"] = (prev.get("quantity") or 0) + (it.get("quantity") or 0)
            else:
                dedup[ck] = {**it, "_canonical": ck}

        # Build candidate pool: this supplier's existing products + corrections
        existing = await db.supplier_products.find(
            {"supplier_id": job["supplier_id"]}, {"_id": 0, "name": 1}
        ).to_list(2000)
        candidates = list({normalize_text(p["name"]) for p in existing if p.get("name")})

        # Load supplier-specific corrections as dict
        corr_docs = await db.catalog_corrections.find(
            {"supplier_id": job["supplier_id"]}, {"_id": 0}
        ).to_list(5000)
        corrections = {c["original_key"]: c["corrected_name"] for c in corr_docs}

        items_to_insert: list[dict] = []
        review_count = 0
        for ck, it in dedup.items():
            match, conf = await smart_match(ck, candidates, corrections)
            status_ = "auto" if conf >= 0.90 else "needs_review"
            if status_ == "needs_review":
                review_count += 1
            items_to_insert.append({
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                "supplier_id": job["supplier_id"],
                "raw_text": it["name"],
                "extracted": {
                    "name": it["name"],
                    "strength": it.get("strength"),
                    "dosage_form": it.get("dosage_form"),
                    "manufacturer": it.get("manufacturer"),
                    "price": it.get("price") or 0,
                    "quantity": it.get("quantity") or 0,
                },
                "canonical_key": ck,
                "suggested_canonical_name": match,
                "match_confidence": round(conf, 3),
                "match_status": status_,
                "approved_name": match if status_ == "auto" else None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        if items_to_insert:
            await db.import_items.insert_many([dict(d) for d in items_to_insert])

        await db.import_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "review",
                "progress": 100,
                "total_items": len(items_to_insert),
                "items_to_review": review_count,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                # Drop the heavy file payload now to keep DB lean
                "file_b64": None,
            }},
        )
    except Exception as e:
        logger.exception("import job failed")
        await db.import_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": str(e)[:500],
                      "completed_at": datetime.now(timezone.utc).isoformat(),
                      "file_b64": None}},
        )
