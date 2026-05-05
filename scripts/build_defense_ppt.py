from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Pt


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "defense"
PAPER_DIR = ROOT / "docs" / "paper"
FIG_DIR = PAPER_DIR / "figures"
TABLE_DIR = PAPER_DIR / "tables"

PPTX_OUT = OUT_DIR / "chen_di_nev_fault_qa_defense.pptx"
NOTES_OUT = OUT_DIR / "speaker_notes_7min.md"
PROMPTS_OUT = OUT_DIR / "image_prompts.md"
QA_OUT = OUT_DIR / "ppt_qa_report.json"
PREVIEW_OUT = OUT_DIR / "preview_contact_sheet.png"

W = Cm(33.867)
H = Cm(19.05)

COLORS = {
    "ink": RGBColor(24, 31, 42),
    "muted": RGBColor(88, 99, 116),
    "soft": RGBColor(245, 247, 250),
    "line": RGBColor(220, 226, 233),
    "red": RGBColor(207, 42, 42),
    "teal": RGBColor(0, 126, 139),
    "green": RGBColor(42, 157, 143),
    "amber": RGBColor(232, 150, 55),
    "blue": RGBColor(54, 110, 182),
    "purple": RGBColor(112, 82, 168),
    "white": RGBColor(255, 255, 255),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    blank = prs.slide_layouts[6]

    ablation = load_ablation()
    slides = [
        build_cover,
        build_problem,
        build_contributions,
        build_architecture,
        build_rag_pipeline,
        build_model_routing,
        build_implementation,
        build_workflow,
        build_experiment_design,
        lambda p, l, m: build_retrieval_results(p, l, m, ablation),
        build_distribution_results,
        build_discussion,
        build_conclusion,
    ]
    meta: list[dict] = []
    for index, builder in enumerate(slides, start=1):
        slide = prs.slides.add_slide(blank)
        slide_meta = builder(prs, slide, index)
        meta.append(slide_meta)

    prs.save(PPTX_OUT)
    write_speaker_notes(meta)
    write_image_prompts()
    write_preview(meta)
    qa = inspect_pptx(prs, meta)
    QA_OUT.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PPTX: {PPTX_OUT}")
    print(f"Notes: {NOTES_OUT}")
    print(f"Prompts: {PROMPTS_OUT}")
    print(f"Preview: {PREVIEW_OUT}")
    print(f"QA: {QA_OUT}")


def load_ablation() -> list[dict]:
    path = TABLE_DIR / "retrieval_ablation_summary.csv"
    rows: list[dict] = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    return rows


def add_bg(slide, color=COLORS["white"]) -> None:
    bg = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, 0, 0, W, H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = color
    bg.line.fill.background()


def tx(slide, text, x, y, w, h, size=28, bold=False, color=None, align=PP_ALIGN.LEFT, font="Microsoft YaHei"):
    box = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Cm(0)
    tf.margin_right = Cm(0)
    tf.margin_top = Cm(0)
    tf.margin_bottom = Cm(0)
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color or COLORS["ink"]
    return box


def rich_line(slide, runs, x, y, w, h, size=28, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Cm(0)
    tf.margin_right = Cm(0)
    tf.margin_top = Cm(0)
    tf.margin_bottom = Cm(0)
    p = tf.paragraphs[0]
    p.alignment = align
    for item in runs:
        run = p.add_run()
        run.text = item["text"]
        run.font.name = "Microsoft YaHei"
        run.font.size = Pt(item.get("size", size))
        run.font.bold = item.get("bold", False)
        run.font.color.rgb = item.get("color", COLORS["ink"])
    return box


def title(slide, label, headline, index, subtitle=None):
    tx(slide, f"{index:02d}", 1.0, 0.72, 1.6, 0.45, 13, True, COLORS["red"])
    tx(slide, label, 2.55, 0.7, 5.5, 0.45, 12, True, COLORS["muted"])
    tx(slide, headline, 1.0, 1.35, 24.5, 1.2, 27, True, COLORS["ink"])
    line = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Cm(1.0), Cm(2.72), Cm(2.1), Cm(0.08))
    line.fill.solid()
    line.fill.fore_color.rgb = COLORS["red"]
    line.line.fill.background()
    if subtitle:
        tx(slide, subtitle, 1.0, 2.95, 23.8, 0.55, 14, False, COLORS["muted"])


def pill(slide, text, x, y, w, h, fill, color=COLORS["white"], size=16, bold=True):
    shp = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Cm(x), Cm(y), Cm(w), Cm(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = fill
    tf = shp.text_frame
    tf.clear()
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return shp


def callout(slide, text, x, y, w, h, accent=COLORS["red"], size=22):
    left = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Cm(x), Cm(y), Cm(0.12), Cm(h))
    left.fill.solid()
    left.fill.fore_color.rgb = accent
    left.line.fill.background()
    return rich_line(slide, text, x + 0.28, y, w - 0.28, h, size=size)


def arrow(slide, x1, y1, x2, y2, color=COLORS["muted"], width=2.0):
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x1), Cm(y1), Cm(x2), Cm(y2))
    conn.line.color.rgb = color
    conn.line.width = Pt(width)
    conn.line.end_arrowhead = True
    return conn


def add_picture(slide, path: Path, x, y, w, h):
    if not path.exists():
        return placeholder(slide, path.name, x, y, w, h)
    pic = slide.shapes.add_picture(str(path), Cm(x), Cm(y), width=Cm(w), height=Cm(h))
    return pic


def placeholder(slide, label, x, y, w, h):
    shp = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Cm(x), Cm(y), Cm(w), Cm(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = COLORS["soft"]
    shp.line.color.rgb = COLORS["line"]
    tx(slide, label, x + 0.4, y + h / 2 - 0.3, w - 0.8, 0.6, 16, False, COLORS["muted"], PP_ALIGN.CENTER)
    return shp


def build_cover(prs, slide, index):
    add_bg(slide, RGBColor(250, 251, 253))
    tx(slide, "毕业论文答辩", 1.1, 1.1, 5.0, 0.5, 15, True, COLORS["red"])
    rich_line(
        slide,
        [
            {"text": "面向新能源汽车故障诊断的", "size": 28, "bold": True},
            {"text": "\n多模态检索增强问答系统", "size": 38, "bold": True, "color": COLORS["red"]},
            {"text": "\n设计与实现", "size": 38, "bold": True},
        ],
        1.1,
        2.25,
        16.8,
        4.0,
        size=34,
    )
    tx(slide, "学生：陈迪   |   答辩时长：7 分钟", 1.15, 6.65, 12.0, 0.6, 17, False, COLORS["muted"])
    tx(slide, "核心主张：让维修问答从“能回答”走向“可追溯、可部署、可演示”。", 1.15, 7.52, 15.5, 0.75, 20, True, COLORS["ink"])
    # Subject-specific evidence field.
    for i, (x, y, c) in enumerate(
        [
            (20.0, 2.0, COLORS["teal"]),
            (25.5, 2.6, COLORS["amber"]),
            (23.0, 5.8, COLORS["red"]),
            (28.2, 5.0, COLORS["blue"]),
            (21.4, 7.3, COLORS["green"]),
        ]
    ):
        circ = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.OVAL, Cm(x), Cm(y), Cm(1.0), Cm(1.0))
        circ.fill.solid()
        circ.fill.fore_color.rgb = c
        circ.line.fill.background()
        tx(slide, ["PDF", "RAG", "vLLM", "BGE", "SSE"][i], x - 0.15, y + 1.16, 1.3, 0.35, 10, True, COLORS["muted"], PP_ALIGN.CENTER)
    arrow(slide, 21.0, 2.5, 25.5, 3.1, COLORS["line"], 1.4)
    arrow(slide, 26.5, 3.1, 28.2, 5.45, COLORS["line"], 1.4)
    arrow(slide, 23.5, 6.3, 28.2, 5.45, COLORS["line"], 1.4)
    arrow(slide, 21.9, 7.75, 23.5, 6.3, COLORS["line"], 1.4)
    return {"title": "封面", "time": "20s", "talk": "开场说明选题：新能源汽车维修资料多、故障链路复杂，本文目标是构建一个可追溯、可部署的多模态故障诊断问答系统。"}


def build_problem(prs, slide, index):
    add_bg(slide)
    title(slide, "背景与意义", "维修诊断不是缺少资料，而是缺少可用的证据链", index)
    tx(slide, "新能源汽车故障诊断面临三类实际困难", 1.0, 3.25, 12.0, 0.7, 23, True)
    items = [
        ("资料碎片化", "PDF 手册、故障码、数据流、维修案例分散"),
        ("表达不一致", "技师描述、DTC、仪表报警图像难以直接匹配"),
        ("大模型风险", "纯 LLM 容易给出无来源、不可复核的建议"),
    ]
    for i, (head, body) in enumerate(items):
        y = 4.25 + i * 1.65
        pill(slide, str(i + 1), 1.1, y, 1.0, 0.8, [COLORS["teal"], COLORS["amber"], COLORS["red"]][i], size=18)
        rich_line(
            slide,
            [
                {"text": head, "bold": True, "size": 23, "color": COLORS["ink"]},
                {"text": f"  {body}", "size": 18, "color": COLORS["muted"]},
            ],
            2.45,
            y + 0.05,
            17.5,
            0.85,
            20,
        )
    callout(
        slide,
        [
            {"text": "本文问题：", "bold": True, "color": COLORS["red"]},
            {"text": "如何让问答系统同时具备 "},
            {"text": "准确检索、引用溯源、本地部署、多模态理解", "bold": True, "color": COLORS["red"]},
            {"text": "？"},
        ],
        21.3,
        4.0,
        10.0,
        2.3,
        size=21,
    )
    pill(slide, "问题导向", 22.0, 7.3, 3.2, 0.8, COLORS["ink"], size=16)
    pill(slide, "工程落地", 25.8, 7.3, 3.2, 0.8, COLORS["teal"], size=16)
    return {"title": "背景与意义", "time": "35s", "talk": "这一页按问题导向讲：资料多但不可直接用，纯模型会幻觉，所以系统必须围绕证据链和真实部署来设计。"}


def build_contributions(prs, slide, index):
    add_bg(slide, RGBColor(252, 252, 252))
    title(slide, "研究内容", "围绕“可信诊断问答”完成四项核心工作", index)
    contributions = [
        ("多模态 RAG 框架", "文本问题、故障码、仪表图片、PDF 证据统一进入诊断链路", COLORS["teal"]),
        ("混合检索与重排序", "向量召回 + 关键词召回 + BGE reranker，提高证据命中和引用质量", COLORS["blue"]),
        ("多模型路由机制", "chat / vision_ocr / embedding / rerank / fallback 按任务独立配置", COLORS["amber"]),
        ("一键部署与演示容错", "支持单张 4090 + vLLM + Qwen-VL，保留 Demo Cache 与 fallback", COLORS["red"]),
    ]
    for i, (head, body, color) in enumerate(contributions):
        x = 1.1 + (i % 2) * 15.5
        y = 3.5 + (i // 2) * 3.2
        pill(slide, f"0{i+1}", x, y, 2.0, 0.75, color, size=15)
        tx(slide, head, x, y + 1.05, 8.5, 0.6, 24, True)
        tx(slide, body, x, y + 1.78, 12.6, 0.95, 16, False, COLORS["muted"])
    rich_line(
        slide,
        [
            {"text": "创新点不是“用了 RAG”，而是把 "},
            {"text": "检索可信性、模型路由和部署可靠性", "bold": True, "color": COLORS["red"]},
            {"text": " 放到同一个系统闭环中。"},
        ],
        1.1,
        16.6,
        29.0,
        0.7,
        20,
    )
    return {"title": "研究内容与贡献", "time": "35s", "talk": "这一页先给老师一个总览：我主要做了多模态 RAG、混合检索重排、多模型路由和部署容错四件事。"}


def build_architecture(prs, slide, index):
    add_bg(slide)
    title(slide, "系统设计与实现", "总体架构：从多源资料到可追溯诊断答案", index, "第 2 部分开始进入重点：设计后面紧跟实现。")
    layers = [
        ("输入层", ["文本问题", "故障码 DTC", "报警图片", "维修 PDF"], COLORS["teal"]),
        ("知识层", ["PDF 解析", "文本分块", "元数据保留", "pgvector 索引"], COLORS["blue"]),
        ("推理层", ["混合检索", "BGE 重排", "Qwen-VL/vLLM", "引用约束"], COLORS["amber"]),
        ("应用层", ["聊天问答", "知识库管理", "模型配置", "部署迁移"], COLORS["red"]),
    ]
    for i, (name, nodes, color) in enumerate(layers):
        y = 4.0 + i * 2.25
        pill(slide, name, 1.0, y, 3.1, 0.8, color, size=16)
        for j, node in enumerate(nodes):
            pill(slide, node, 5.0 + j * 6.2, y, 4.4, 0.8, RGBColor(244, 247, 251), COLORS["ink"], size=14, bold=True)
        if i < len(layers) - 1:
            arrow(slide, 16.0, y + 0.9, 16.0, y + 1.65, COLORS["muted"], 1.8)
    callout(
        slide,
        [
            {"text": "实现闭环：", "bold": True, "color": COLORS["red"]},
            {"text": "Next.js 前端 + FastAPI 后端 + PostgreSQL/pgvector + Redis + MinIO + Worker"},
        ],
        1.0,
        13.4,
        28.5,
        0.8,
        size=18,
    )
    return {"title": "总体架构", "time": "40s", "talk": "强调这不是只有设计图，系统已经实现了输入、知识、推理和应用四层，下面逐层展开。"}


def build_rag_pipeline(prs, slide, index):
    add_bg(slide, RGBColor(250, 252, 253))
    title(slide, "系统设计与实现", "RAG 诊断链路：让答案绑定到维修证据", index)
    steps = [
        ("1", "问题解析", "提取 DTC、系统词、症状"),
        ("2", "混合召回", "向量 + 关键词双路召回"),
        ("3", "重排序", "BGE reranker 选出强证据"),
        ("4", "上下文构造", "保留标题、页码、片段"),
        ("5", "结构化回答", "原因 / 步骤 / 安全 / 引用"),
    ]
    for i, (num, head, body) in enumerate(steps):
        x = 1.1 + i * 6.25
        pill(slide, num, x, 4.0, 1.0, 1.0, COLORS["red"], size=18)
        tx(slide, head, x - 0.45, 5.25, 3.0, 0.5, 20, True, COLORS["ink"], PP_ALIGN.CENTER)
        tx(slide, body, x - 0.8, 5.95, 3.8, 1.1, 14, False, COLORS["muted"], PP_ALIGN.CENTER)
        if i < len(steps) - 1:
            arrow(slide, x + 1.15, 4.5, x + 5.1, 4.5, COLORS["muted"], 1.7)
    rich_line(
        slide,
        [
            {"text": "关键约束：", "bold": True, "color": COLORS["red"]},
            {"text": "模型不能凭空引用；资料不足时必须提示补充检测数据。"},
        ],
        2.0,
        8.9,
        24.0,
        0.8,
        23,
    )
    # Answer template strip.
    labels = ["可能原因", "检查步骤", "安全提醒", "维修建议", "引用来源", "置信提示"]
    for i, lab in enumerate(labels):
        pill(slide, lab, 2.0 + i * 4.8, 11.2, 3.6, 0.75, RGBColor(239, 243, 248), COLORS["ink"], size=14)
    return {"title": "RAG 诊断链路", "time": "45s", "talk": "讲清楚系统如何做：先提取故障词，再混合召回，再重排，最后把证据组织进固定回答模板。"}


def build_model_routing(prs, slide, index):
    add_bg(slide)
    title(slide, "系统设计与实现", "多模型路由：不同任务调用最合适的模型", index)
    pill(slide, "Model Router", 13.0, 5.2, 6.0, 1.3, COLORS["ink"], size=21)
    routes = [
        ("chat", "vLLM / Qwen-VL", 3.0, 3.5, COLORS["teal"]),
        ("vision_ocr", "Qwen 多模态", 3.0, 8.4, COLORS["blue"]),
        ("embedding", "BAAI/bge-m3", 23.5, 3.5, COLORS["green"]),
        ("rerank", "BGE reranker", 23.5, 8.4, COLORS["amber"]),
        ("fallback_chat", "远端 API / Demo Cache", 12.1, 12.6, COLORS["red"]),
    ]
    for task, model, x, y, color in routes:
        pill(slide, task, x, y, 5.6, 0.75, color, size=15)
        tx(slide, model, x, y + 0.95, 5.8, 0.6, 17, True, COLORS["ink"], PP_ALIGN.CENTER)
        arrow(slide, 16.0, 5.85, x + 2.8, y + 0.4, color, 1.8)
    callout(
        slide,
        [
            {"text": "实现价值：", "bold": True, "color": COLORS["red"]},
            {"text": "API Key 可为空，兼容 vLLM / Ollama / llama.cpp / LM Studio；GPU 不可用时演示不中断。"},
        ],
        1.3,
        15.7,
        28.5,
        0.8,
        size=18,
    )
    return {"title": "多模型路由", "time": "45s", "talk": "重点讲模型配置的工程价值：不是把模型写死，而是把不同任务路由到不同端点，方便本地、远端和 fallback 切换。"}


def build_implementation(prs, slide, index):
    add_bg(slide, RGBColor(251, 252, 253))
    title(slide, "系统设计与实现", "实现内容：前端、后端、存储、部署均已落地", index)
    rows = [
        ("前端实现", "Next.js：聊天工作台、知识库、PDF 管理、模型设置"),
        ("后端实现", "FastAPI：鉴权、会话、检索、SSE 流式回答、模型测试"),
        ("数据实现", "PostgreSQL/pgvector：文档、分块、向量、引用、聊天记录"),
        ("文件与任务", "MinIO + Worker：文件存储、PDF 入库、异步处理"),
        ("部署实现", "Docker Compose GPU：vLLM、Qwen-VL、一键迁移与健康检查"),
    ]
    for i, (head, body) in enumerate(rows):
        y = 3.55 + i * 2.05
        pill(slide, head, 1.2, y, 4.2, 0.78, [COLORS["teal"], COLORS["blue"], COLORS["green"], COLORS["amber"], COLORS["red"]][i], size=15)
        tx(slide, body, 6.2, y + 0.05, 22.8, 0.65, 18, False, COLORS["ink"])
        if i < len(rows) - 1:
            line = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Cm(6.2), Cm(y + 1.25), Cm(22.5), Cm(0.03))
            line.fill.solid()
            line.fill.fore_color.rgb = COLORS["line"]
            line.line.fill.background()
    rich_line(
        slide,
        [
            {"text": "答辩重点：", "bold": True, "color": COLORS["red"]},
            {"text": "这里是“系统设计与实现”，不是只停留在架构图。"},
        ],
        1.2,
        16.2,
        25.0,
        0.7,
        20,
    )
    return {"title": "实现内容", "time": "45s", "talk": "按导师要求明确讲实现：每一层设计后面都对应了实际代码、数据库表、服务和部署脚本。"}


def build_workflow(prs, slide, index):
    add_bg(slide)
    title(slide, "系统设计与实现", "应用流程：管理员建知识库，技师完成诊断问答", index)
    # UI-like surfaces, built as editable shapes rather than fake screenshots.
    surfaces = [
        ("知识库管理", ["上传维修 PDF", "解析分块", "向量索引"], 1.1, 4.0, COLORS["teal"]),
        ("模型配置", ["端点管理", "任务路由", "连通测试"], 12.2, 4.0, COLORS["amber"]),
        ("诊断聊天", ["文本/图片问题", "流式回答", "引用来源"], 23.3, 4.0, COLORS["red"]),
    ]
    for title_text, bullets, x, y, color in surfaces:
        rect = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Cm(x), Cm(y), Cm(8.6), Cm(7.2))
        rect.fill.solid()
        rect.fill.fore_color.rgb = RGBColor(248, 250, 252)
        rect.line.color.rgb = COLORS["line"]
        pill(slide, title_text, x + 0.55, y + 0.55, 3.3, 0.62, color, size=13)
        for j, b in enumerate(bullets):
            pill(slide, b, x + 0.8, y + 1.75 + j * 1.45, 6.8, 0.8, COLORS["white"], COLORS["ink"], size=14)
        tx(slide, "已实现页面", x + 0.7, y + 6.35, 3.2, 0.4, 11, True, COLORS["muted"])
    arrow(slide, 9.9, 7.5, 12.0, 7.5, COLORS["muted"], 1.8)
    arrow(slide, 20.9, 7.5, 23.0, 7.5, COLORS["muted"], 1.8)
    callout(
        slide,
        [
            {"text": "闭环：", "bold": True, "color": COLORS["red"]},
            {"text": "资料入库 -> 模型路由 -> 诊断问答 -> 引用复核 -> 演示部署。"},
        ],
        3.0,
        13.2,
        25.0,
        0.9,
        size=21,
    )
    return {"title": "应用流程", "time": "35s", "talk": "用一个业务流来串起系统：管理员上传资料和配置模型，技师在聊天界面完成诊断并查看引用。"}


def build_experiment_design(prs, slide, index):
    add_bg(slide, RGBColor(250, 251, 253))
    title(slide, "实验及讨论", "实验围绕四个问题验证：准不准、稳不稳、快不快、能不能部署", index)
    experiments = [
        ("检索消融", "No RAG / Dense / Dense+Keyword / Hybrid+Rerank", "Hit@K、MRR、nDCG@5"),
        ("证据质量", "top vector score、top rerank score、keyword coverage", "分布与相关性"),
        ("性能分析", "延迟、首 token、缓存、fallback", "交互可用性"),
        ("部署验证", "Docker Compose GPU、vLLM、Qwen-VL、本地 BGE", "演示可靠性"),
    ]
    for i, (head, setup, metric) in enumerate(experiments):
        x = 1.2 + (i % 2) * 15.4
        y = 3.7 + (i // 2) * 4.1
        pill(slide, head, x, y, 4.2, 0.8, [COLORS["teal"], COLORS["blue"], COLORS["amber"], COLORS["red"]][i], size=15)
        tx(slide, setup, x, y + 1.05, 12.3, 0.75, 16, True)
        tx(slide, metric, x, y + 1.95, 12.3, 0.6, 15, False, COLORS["muted"])
    rich_line(
        slide,
        [
            {"text": "说明：", "bold": True, "color": COLORS["red"]},
            {"text": "实验不是把系统功能截图堆上去，而是验证核心方法和工程约束是否成立。"},
        ],
        1.2,
        15.8,
        29.0,
        0.7,
        19,
    )
    return {"title": "实验设计", "time": "35s", "talk": "这一页回答老师会关心的问题：你怎么证明系统有效。实验分为检索、证据质量、性能和部署四类。"}


def build_retrieval_results(prs, slide, index, rows):
    add_bg(slide)
    title(slide, "实验及讨论", "检索消融：混合检索与重排序提升证据命中", index)
    chart_data = CategoryChartData()
    methods = [r.get("method", r.get("variant", "")) for r in rows]
    chart_data.categories = methods
    for metric, label in [("hit_at_1", "Hit@1"), ("mrr", "MRR"), ("ndcg_at_5", "nDCG@5")]:
        values = [float(r.get(metric, 0) or 0) for r in rows]
        chart_data.add_series(label, values)
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Cm(1.0),
        Cm(3.6),
        Cm(20.0),
        Cm(9.8),
        chart_data,
    ).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.value_axis.maximum_scale = 1.05
    chart.value_axis.minimum_scale = 0
    chart.category_axis.tick_labels.font.size = Pt(10)
    chart.value_axis.tick_labels.font.size = Pt(10)
    chart.chart_title.has_text_frame = True
    chart.chart_title.text_frame.text = "Retrieval Ablation"
    tx(slide, "关键结果", 22.2, 3.7, 6.0, 0.6, 22, True)
    metrics = [
        ("Hybrid+Rerank", "Hit@1 = 1.00", COLORS["red"]),
        ("Dense", "Hit@1 = 0.9688", COLORS["teal"]),
        ("No RAG", "MRR = 0", COLORS["muted"]),
    ]
    for i, (m, v, c) in enumerate(metrics):
        pill(slide, m, 22.2, 4.65 + i * 1.75, 4.6, 0.65, c, size=13)
        tx(slide, v, 27.2, 4.7 + i * 1.75, 4.5, 0.55, 17, True, COLORS["ink"])
    callout(
        slide,
        [
            {"text": "结论：", "bold": True, "color": COLORS["red"]},
            {"text": "RAG 让回答具备可引用证据；Hybrid+Rerank 在小规模维修问题集上取得最佳表现。"},
        ],
        22.2,
        11.2,
        9.7,
        1.3,
        size=17,
    )
    return {"title": "检索消融结果", "time": "45s", "talk": "重点讲柱状图：没有 RAG 就没有证据命中；Dense 已经较好，Hybrid+Rerank 进一步把 Hit@1 和 MRR 推到最好。"}


def build_distribution_results(prs, slide, index):
    add_bg(slide)
    title(slide, "实验及讨论", "分布分析：检索证据、延迟和知识向量空间可解释", index)
    add_picture(slide, FIG_DIR / "fig_experiment_dashboard.png", 1.0, 3.55, 14.9, 10.3)
    add_picture(slide, FIG_DIR / "fig_score_pairplot.png", 17.2, 3.55, 13.4, 10.3)
    rich_line(
        slide,
        [
            {"text": "观察：", "bold": True, "color": COLORS["red"]},
            {"text": "知识分块在向量空间中形成子系统结构；证据分数与覆盖率可用于解释回答可信度。"},
        ],
        1.0,
        14.65,
        29.0,
        0.8,
        18,
    )
    return {"title": "分布与可解释性", "time": "45s", "talk": "这一页不用逐点解释所有散点，强调图的作用：系统不是黑箱生成，而是可以观察知识分布、证据分数和延迟关系。"}


def build_discussion(prs, slide, index):
    add_bg(slide, RGBColor(251, 252, 253))
    title(slide, "实验及讨论", "讨论：效果、成本与演示可靠性的权衡", index)
    cols = [
        ("效果", ["检索命中率高", "回答带来源引用", "图片问题可接入 Qwen-VL"], COLORS["teal"]),
        ("延迟", ["SSE 先出首 token", "视觉描述可缓存", "重排在 CPU 上较慢"], COLORS["amber"]),
        ("成本", ["单张 4090 可演示", "远端 API 可兜底", "大模型越大成本越高"], COLORS["blue"]),
        ("风险", ["知识库规模仍有限", "真实维修样本需扩充", "需更多端到端人工评测"], COLORS["red"]),
    ]
    for i, (head, bullets, color) in enumerate(cols):
        x = 1.0 + i * 7.9
        pill(slide, head, x, 3.95, 3.6, 0.8, color, size=16)
        for j, b in enumerate(bullets):
            tx(slide, f"• {b}", x, 5.05 + j * 1.05, 6.4, 0.55, 16, False, COLORS["ink"])
    callout(
        slide,
        [
            {"text": "答辩表述：", "bold": True, "color": COLORS["red"]},
            {"text": "本文不是追求最大模型，而是在真实资源约束下取得可用、可信、可演示的系统效果。"},
        ],
        2.0,
        13.1,
        27.0,
        1.1,
        size=21,
    )
    return {"title": "实验讨论", "time": "40s", "talk": "讨论不要只说好处，也要说成本和限制：单 4090 可部署，但大模型、真实样本和人工评测仍是未来改进方向。"}


def build_conclusion(prs, slide, index):
    add_bg(slide)
    title(slide, "结论", "完成了一个面向真实部署的多模态维修诊断问答系统", index)
    conclusions = [
        ("系统完成度", "实现了前端、后端、知识库、模型路由、部署脚本的完整闭环"),
        ("方法有效性", "混合检索 + 重排序提升维修证据命中，回答具备引用溯源"),
        ("工程价值", "支持 vLLM/Qwen-VL、本地 BGE、fallback 与 Demo Cache，便于答辩演示和迁移"),
    ]
    for i, (head, body) in enumerate(conclusions):
        y = 4.0 + i * 2.45
        pill(slide, head, 1.3, y, 4.0, 0.8, [COLORS["teal"], COLORS["red"], COLORS["amber"]][i], size=15)
        tx(slide, body, 6.0, y + 0.05, 22.5, 0.7, 20, True if i == 0 else False, COLORS["ink"])
    rich_line(
        slide,
        [
            {"text": "最终结论：", "bold": True, "color": COLORS["red"], "size": 27},
            {"text": "系统把新能源汽车维修问答从通用生成推进到 "},
            {"text": "可追溯、可配置、可迁移", "bold": True, "color": COLORS["red"]},
            {"text": " 的工程应用。"},
        ],
        2.0,
        12.5,
        27.8,
        1.2,
        23,
    )
    tx(slide, "谢谢各位老师，请批评指正", 1.4, 16.3, 29.0, 0.8, 24, True, COLORS["muted"], PP_ALIGN.CENTER)
    return {"title": "结论", "time": "35s", "talk": "最后收束到三点：系统完成、方法有效、工程可部署。然后自然进入老师提问。"}


def write_speaker_notes(meta: list[dict]) -> None:
    lines = [
        "# 7 分钟毕业答辩讲稿",
        "",
        "建议总节奏：背景与意义约 1 分钟，系统设计与实现约 3.5 分钟，实验及讨论约 2 分钟，结论约 30 秒。",
        "",
    ]
    for i, item in enumerate(meta, start=1):
        lines.append(f"## {i}. {item['title']}（{item['time']}）")
        lines.append("")
        lines.append(item["talk"])
        lines.append("")
    NOTES_OUT.write_text("\n".join(lines), encoding="utf-8")


def write_image_prompts() -> None:
    content = """# 可选 image2 / AI 配图提示词

本版 PPT 已优先使用项目真实实验图和 PPT 原生图形。如果后续想替换为更具视觉冲击力的图片，可使用以下提示词。

## 封面背景图

中文科研答辩风格，新能源汽车维修诊断场景，抽象的车辆高压系统、维修手册、知识图谱节点和大模型推理流连接在一起。白色或浅灰背景，留出左侧大面积空白用于标题，克制红色与青绿色点缀，专业、清晰、适合本科毕业答辩 PPT，16:9，高分辨率，不要出现真实品牌 Logo，不要生成文字。

## 系统架构图

绘制一张清晰的中文系统架构图，主题为“面向新能源汽车故障诊断的多模态检索增强问答系统”。包含输入层、知识层、推理层、应用层和部署层。输入包括文本问题、故障码、报警图片、PDF；知识层包括 PDF 解析、分块、元数据、pgvector；推理层包括混合检索、BGE 重排、Qwen-VL/vLLM、引用约束；应用层包括聊天、知识库管理、模型配置；部署层包括 Docker Compose、单张 RTX 4090、fallback API、Demo Cache。白底，学术论文矢量风格，中文标签。

## 案例分析图

中文论文风格案例图，左侧为维修技师问题“车辆无法快充，仪表提示充电系统故障”，中间为系统检索到的 3 条证据片段，右侧为结构化诊断答案：可能原因、检查步骤、安全提醒、引用来源。白底，清晰流程箭头，适合答辩 PPT。
"""
    PROMPTS_OUT.write_text(content, encoding="utf-8")


def write_preview(meta: list[dict]) -> None:
    width, height = 1800, 1260
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = load_font(28)
    small = load_font(18)
    title_font = load_font(42)
    draw.text((50, 38), "PPT Contact Sheet", font=title_font, fill=(24, 31, 42))
    cols = 4
    thumb_w, thumb_h = 390, 235
    gap_x, gap_y = 35, 68
    start_x, start_y = 50, 125
    for i, item in enumerate(meta):
        col, row = i % cols, i // cols
        x = start_x + col * (thumb_w + gap_x)
        y = start_y + row * (thumb_h + gap_y)
        draw.rounded_rectangle((x, y, x + thumb_w, y + thumb_h), radius=12, outline=(218, 225, 233), width=3, fill=(248, 250, 252))
        draw.rectangle((x, y, x + 10, y + thumb_h), fill=(207, 42, 42))
        draw.text((x + 24, y + 18), f"{i+1:02d}", font=small, fill=(207, 42, 42))
        draw.text((x + 24, y + 56), item["title"], font=font, fill=(24, 31, 42))
        wrapped = wrap_text(item["talk"], 22)[:3]
        for j, line in enumerate(wrapped):
            draw.text((x + 24, y + 106 + j * 28), line, font=small, fill=(88, 99, 116))
    canvas.save(PREVIEW_OUT)


def wrap_text(text: str, max_chars: int) -> list[str]:
    lines = []
    current = ""
    for ch in text:
        current += ch
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines


def load_font(size: int):
    for path in [
        "/mnt/c/Windows/Fonts/msyh.ttc",
        "/mnt/c/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def inspect_pptx(prs: Presentation, meta: list[dict]) -> dict:
    issues = []
    slide_w = prs.slide_width
    slide_h = prs.slide_height
    for i, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.left < 0 or shape.top < 0 or shape.left + shape.width > slide_w or shape.top + shape.height > slide_h:
                issues.append({"slide": i, "shape": getattr(shape, "name", ""), "issue": "out_of_bounds"})
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if "Lorem" in text or "placeholder" in text.lower():
                    issues.append({"slide": i, "shape": getattr(shape, "name", ""), "issue": "placeholder_text"})
    return {
        "pptx": str(PPTX_OUT),
        "slides": len(prs.slides),
        "issues": issues,
        "status": "passed" if not issues else "has_issues",
        "note": "Checked slide bounds and placeholder text through python-pptx. Contact sheet is a script-level preview, not a PowerPoint re-render.",
    }


if __name__ == "__main__":
    main()
