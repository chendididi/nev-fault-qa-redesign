from io import BytesIO, StringIO
import csv
import re
from pypdf import PdfReader
from docx import Document as DocxDocument
from openpyxl import load_workbook
from app.models.provider import OpenAICompatibleProvider


SYSTEM_KEYWORDS = {
    "BMS": ["BMS", "电池管理", "高压电池", "动力电池", "SOC", "绝缘"],
    "OBC": ["OBC", "车载充电机", "慢充"],
    "DC/DC": ["DC/DC", "DCDC", "低压供电", "12V", "蓄电池"],
    "VCU": ["VCU", "整车控制器", "READY", "唤醒"],
    "CAN": ["CAN", "通讯", "离线", "总线"],
    "HVIL": ["HVIL", "高压互锁", "互锁"],
    "MCU": ["MCU", "电机控制器", "驱动电机", "限扭"],
    "热管理": ["热管理", "水泵", "冷却", "过温"],
    "快充": ["快充", "直流充电", "充电枪", "充电桩"],
}


async def extract_text(filename: str, content_type: str, data: bytes, ocr_provider: OpenAICompatibleProvider | None = None) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        page_texts = [page.extract_text() or "" for page in reader.pages]
        if ocr_provider and any(not page_text.strip() for page_text in page_texts):
            page_texts = await _ocr_empty_pdf_pages(filename, data, page_texts, ocr_provider)
        return "\n".join(f"--- 第 {index + 1} 页 ---\n{page_text}" for index, page_text in enumerate(page_texts))
    if lower.endswith(".docx"):
        doc = DocxDocument(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if lower.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(BytesIO(data), data_only=True, read_only=True)
        rows = []
        for sheet in wb.worksheets:
            rows.append(f"工作表: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = [str(value) for value in row if value is not None]
                if values:
                    rows.append(" | ".join(values))
        return "\n".join(rows)
    if lower.endswith(".csv"):
        text = data.decode("utf-8", errors="ignore")
        rows = csv.reader(StringIO(text))
        return "\n".join(" | ".join(row) for row in rows)
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")) or content_type.startswith("image/"):
        if not ocr_provider:
            raise RuntimeError("图片 OCR 需要可用的 gpt-5.5 视觉接口")
        return (await ocr_provider.ocr_image(data, content_type or "image/png", context=filename)).strip()
    return data.decode("utf-8", errors="ignore")


async def _ocr_empty_pdf_pages(
    filename: str,
    data: bytes,
    page_texts: list[str],
    ocr_provider: OpenAICompatibleProvider,
) -> list[str]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF 图片页 OCR 需要安装 PyMuPDF") from exc

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        result = list(page_texts)
        for index, page_text in enumerate(page_texts):
            if page_text.strip():
                continue
            page = doc.load_page(index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_bytes = pixmap.tobytes("png")
            result[index] = await ocr_provider.ocr_image(
                image_bytes,
                "image/png",
                context=f"{filename} 第 {index + 1} 页",
            )
        return result
    finally:
        doc.close()


def chunk_text(text: str, *, size: int = 900, overlap: int = 120) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def extract_repair_metadata(content: str) -> dict:
    dtcs = sorted(set(re.findall(r"\b[PCBU][0-9A-F]{4}\b", content.upper())))
    systems = [system for system, keywords in SYSTEM_KEYWORDS.items() if any(keyword.lower() in content.lower() for keyword in keywords)]
    metadata: dict[str, object] = {"keywords": sorted(set(dtcs + systems))}
    page = _extract_first_int(content, [r"第\s*(\d+)\s*页", r"页码\s*[:：]\s*(\d+)"])
    if page is not None:
        metadata["page"] = page
    heading = _extract_heading(content)
    if heading:
        metadata["heading"] = heading
    if dtcs:
        metadata["dtc"] = dtcs
    if systems:
        metadata["system"] = systems
    vehicle_model = _extract_vehicle_model(content)
    if vehicle_model:
        metadata["vehicle_model"] = vehicle_model
    return metadata


def _extract_first_int(content: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_heading(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip(" #-—")
        if not stripped:
            continue
        if re.search(r"(第\s*\d+\s*[章节页]|章节\s*\d+|故障码|系统[:：]|维修案例)", stripped):
            return stripped[:120]
    return None


def _extract_vehicle_model(content: str) -> str | None:
    match = re.search(r"(?:车型|适用车型)\s*[:：]\s*([A-Za-z0-9\-_一-龥]+)", content)
    if match:
        return match.group(1)[:60]
    return None
