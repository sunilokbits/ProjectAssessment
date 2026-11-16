"""Assessment questionnaire as an Insight-branded Excel workbook (cover, questionnaire, dimension summary).

The questionnaire sheet can be sent to the client to fill in: answer cells have drop-downs where the
question has fixed options, and the summary sheet recalculates progress with formulas as answers are typed.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ASSETS = Path(__file__).parent / "assets"
MAGENTA, PURPLE, INK, MUTED, TINT, LINE = "C8175F", "8A1A7C", "24232D", "6B6A78", "FDEBF2", "EBEAF0"
FONT = "Calibri"
THIN = Side(style="thin", color=LINE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

DEFAULT_YES_NO = [("yes", "Yes"), ("partial", "Partial"), ("no", "No"), ("unknown", "Unknown")]
TYPE_LABEL = {"yes_no": "Yes / No", "scale": "Scale 1–5", "single_choice": "Single choice",
              "multi_choice": "Multiple choice", "text": "Free text", "number": "Number"}
ORIGIN_FILL = {"GLOBAL": "EFEFF4", "INDUSTRY": "E8F1FB", "SUB-DOMAIN": "EAF6F1", "TECHNOLOGY": "F3ECFA",
               "PROJECT": "FFF4E5", "AI-DISCOVERED": TINT}

# (header, width, key)
COLUMNS = [
    ("#", 5, "n"), ("Question ID", 26, "key"), ("Dimension", 22, "dimension"), ("Category", 13, "category"),
    ("Origin", 14, "origin"), ("Source pack", 22, "source"), ("Question", 60, "text"), ("Guidance", 36, "help"),
    ("Applies because", 30, "applies"), ("Critical", 9, "critical"), ("Evidence required", 10, "evidence_required"),
    ("Weight", 8, "weight"), ("Answer type", 14, "type"), ("Allowed answers", 30, "options"),
    ("Answer", 22, "answer"), ("Evidence / reference", 32, "evidence"), ("Notes", 30, "notes"),
    ("Answered by", 14, "answered_by"), ("Verified", 9, "verified"),
]
COL = {key: i + 1 for i, (_, _, key) in enumerate(COLUMNS)}
INPUT_COLS = ("answer", "evidence", "notes")


def _options(q: dict[str, Any]) -> list[tuple[str, str]]:
    opts = [(str(o.get("value")), str(o.get("label") or o.get("value"))) for o in q.get("options") or []]
    if q.get("answer_type") == "yes_no" and not opts:
        return DEFAULT_YES_NO
    if q.get("answer_type") == "scale" and not opts:
        return [(str(n), str(n)) for n in range(1, 6)]
    return opts


def _answer_text(q: dict[str, Any]) -> str:
    a = q.get("answer") or {}
    v = a.get("value")
    if v is None or v == "":
        return ""
    labels = dict(_options(q))
    if isinstance(v, list):
        return "; ".join(labels.get(str(x), str(x)) for x in v)
    return labels.get(str(v), str(v))


def _cell(ws, row: int, col: int, value: Any, **style):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(name=FONT, size=style.pop("size", 10), bold=style.pop("bold", False),
                  color=style.pop("color", INK), italic=style.pop("italic", False))
    if "fill" in style:
        c.fill = PatternFill("solid", fgColor=style.pop("fill"))
    c.alignment = style.pop("align", WRAP)
    if style.pop("border", False):
        c.border = BOX
    return c


def _band(ws, row: int, last_col: int, height: int = 6) -> None:
    for col in range(1, last_col + 1):
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=MAGENTA)
    ws.row_dimensions[row].height = height


def _fit_page(ws, landscape: bool = False) -> None:
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _cover(wb: Workbook, info: dict[str, Any], qs: list[dict[str, Any]]) -> None:
    ws = wb.active
    ws.title = "Cover"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 70
    logo = ASSETS / "insight_logo.png"
    if logo.exists():
        img = XLImage(str(logo))
        ratio = 34 / img.height
        img.height, img.width = 34, int(img.width * ratio)
        ws.add_image(img, "B2")
    ws.row_dimensions[2].height = 30
    _band(ws, 4, 3)
    _cell(ws, 6, 2, "Assessment questionnaire", size=22, bold=True, color=INK, align=Alignment(vertical="center"))
    _cell(ws, 7, 2, f"{info['client']} — {info['project']}", size=13, bold=True, color=MAGENTA,
          align=Alignment(vertical="center"))
    ws.row_dimensions[6].height = 32
    answered = sum(1 for q in qs if _answer_text(q))
    rows = [
        ("Client", info["client"]), ("Project", info["project"]), ("Industry", info.get("industry") or "Not classified"),
        ("Technologies", ", ".join(info.get("technologies") or []) or "–"),
        ("Project types", ", ".join(info.get("project_types") or []) or "–"),
        ("Geography", info.get("geography") or "–"),
        ("Questions", f"{len(qs)} in total · {sum(1 for q in qs if q.get('critical'))} critical · "
                      f"{answered} answered when exported"),
        ("Generated", datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")),
    ]
    r = 9
    for k, v in rows:
        _cell(ws, r, 2, k, bold=True, color=MUTED, fill="F7F7FA", border=True)
        _cell(ws, r, 3, v, border=True)
        r += 1
    r += 1
    _cell(ws, r, 2, "How to complete", size=12, bold=True, color=PURPLE)
    r += 1
    steps = [
        "Go to the Questionnaire sheet. Each row is one question tailored to this engagement.",
        "Fill in the three shaded columns: Answer, Evidence / reference and Notes. Answer cells with fixed options "
        "have a drop-down; multiple-choice answers can be separated with semicolons.",
        "Questions marked Critical drive the readiness score most; please answer these first.",
        "Where Evidence required is Yes, reference a document, section or link that supports the answer.",
        "The Summary sheet updates automatically to show progress by dimension.",
    ]
    for i, s in enumerate(steps, 1):
        _cell(ws, r, 2, f"Step {i}", bold=True, color=MAGENTA)
        _cell(ws, r, 3, s)
        ws.row_dimensions[r].height = 30
        r += 1
    r += 1
    _cell(ws, r, 2, "Question origins", size=12, bold=True, color=PURPLE)
    r += 1
    legend = {"GLOBAL": "Applies to every project", "INDUSTRY": "From the client's industry pack",
              "SUB-DOMAIN": "From the selected industry sub-domain", "TECHNOLOGY": "From the technologies in scope",
              "PROJECT": "From the project type", "AI-DISCOVERED": "Clarification raised from the client documents"}
    for k, v in legend.items():
        _cell(ws, r, 2, k, bold=True, fill=ORIGIN_FILL[k], border=True)
        _cell(ws, r, 3, v, border=True)
        r += 1
    r += 1
    _cell(ws, r, 2, "Confidential — prepared by Insight for the named client. Do not distribute further.",
          size=8, italic=True, color=MUTED, align=Alignment(vertical="top"))
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    _fit_page(ws)


def _questionnaire(wb: Workbook, qs: list[dict[str, Any]], dim_names: dict[str, str]) -> int:
    ws = wb.create_sheet("Questionnaire")
    ws.sheet_view.zoomScale = 90
    for i, (head, width, key) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
        fill = MAGENTA if key in INPUT_COLS else PURPLE
        _cell(ws, 1, i, head, bold=True, color="FFFFFF", fill=fill, border=True,
              align=Alignment(wrap_text=True, vertical="center", horizontal="center" if width < 12 else "left"))
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "H2"
    input_fill = "FFF8FB"
    validations: dict[str, DataValidation] = {}
    for n, q in enumerate(qs, 1):
        r = n + 1
        a = q.get("answer") or {}
        opts = _options(q)
        src = q.get("source") or {}
        values = {
            "n": n, "key": q["key"], "dimension": dim_names.get(q.get("dimension"), q.get("dimension") or ""),
            "category": (q.get("category") or "").replace("_", " ").title(), "origin": q.get("origin", ""),
            "source": f"{src.get('pack_name', '')} v{src.get('pack_version', '')}".strip(" v") if src else "",
            "text": q.get("text", ""), "help": q.get("help") or "",
            "applies": "; ".join(q.get("applies_because") or []),
            "critical": "Yes" if q.get("critical") else "No",
            "evidence_required": "Yes" if q.get("evidence_required") else "No",
            "weight": q.get("weight"), "type": TYPE_LABEL.get(q.get("answer_type"), q.get("answer_type") or ""),
            "options": " · ".join(lbl for _, lbl in opts), "answer": _answer_text(q),
            "evidence": a.get("evidence") or "", "notes": a.get("notes") or "",
            "answered_by": a.get("answered_by") or "", "verified": "Yes" if a.get("verified") else ("No" if a else ""),
        }
        for key, col in COL.items():
            style: dict[str, Any] = {"border": True}
            if key in INPUT_COLS:
                style["fill"] = input_fill
            if key == "origin":
                style["fill"] = ORIGIN_FILL.get(values["origin"], "FFFFFF")
                style["bold"] = True
                style["size"] = 9
            if key == "text":
                style["bold"] = bool(q.get("critical"))
            if key == "critical" and q.get("critical"):
                style.update(bold=True, color=MAGENTA)
            if key in ("key", "source", "applies", "options", "help"):
                style.update(size=9, color=MUTED)
            if key in ("n", "critical", "evidence_required", "weight", "verified"):
                style["align"] = Alignment(horizontal="center", vertical="top")
            _cell(ws, r, col, values[key], **style)
        # drop-down for questions with fixed options (single answer only; Excel lists can't multi-select)
        if q.get("answer_type") in ("yes_no", "scale", "single_choice") and opts:
            labels = [lbl.replace(",", " ") for _, lbl in opts]
            formula = '"' + ",".join(labels) + '"'
            if len(formula) <= 255:
                dv = validations.get(formula)
                if dv is None:
                    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showDropDown=False,
                                        errorStyle="warning", error="Choose one of the listed answers.",
                                        errorTitle="Answer", prompt="Pick an answer from the list.",
                                        promptTitle="Answer")
                    validations[formula] = dv
                    ws.add_data_validation(dv)
                dv.add(ws.cell(row=r, column=COL["answer"]))
    last = len(qs) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{last}"
    # open critical questions stand out until they are answered
    ans = get_column_letter(COL["answer"])
    crit = get_column_letter(COL["critical"])
    ws.conditional_formatting.add(
        f"{ans}2:{ans}{last}",
        FormulaRule(formula=[f'AND(${crit}2="Yes",LEN(${ans}2)=0)'], fill=PatternFill("solid", fgColor="FBD3E3")))
    ws.print_title_rows = "1:1"
    _fit_page(ws, landscape=True)
    return last


def _summary(wb: Workbook, qs: list[dict[str, Any]], dims: list[dict[str, Any]], last: int) -> None:
    ws = wb.create_sheet("Summary")
    ws.sheet_view.showGridLines = False
    heads = [("Dimension", 34), ("Group", 14), ("Questions", 12), ("Critical", 11), ("Answered", 12),
             ("Open", 10), ("% answered", 12), ("Critical open", 14)]
    _cell(ws, 1, 1, "Progress by dimension", size=14, bold=True, color=INK)
    _cell(ws, 2, 1, "Recalculates automatically as answers are entered on the Questionnaire sheet.",
          size=9, italic=True, color=MUTED, align=Alignment(vertical="top"))
    for i, (h, w) in enumerate(heads, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        _cell(ws, 4, i, h, bold=True, color="FFFFFF", fill=PURPLE, border=True, align=Alignment(vertical="center"))
    rng = lambda key: f"Questionnaire!${get_column_letter(COL[key])}$2:${get_column_letter(COL[key])}${last}"  # noqa: E731
    D, A, C = rng("dimension"), rng("answer"), rng("critical")
    used = {q.get("dimension") for q in qs}
    rows = [d for d in dims if d["key"] in used]
    r = 5
    for d in rows:
        name = d["name"]
        _cell(ws, r, 1, name, border=True)
        _cell(ws, r, 2, (d.get("group") or "").title(), border=True, color=MUTED)
        ws.cell(row=r, column=3, value=f'=COUNTIF({D},A{r})')
        ws.cell(row=r, column=4, value=f'=COUNTIFS({D},A{r},{C},"Yes")')
        ws.cell(row=r, column=5, value=f'=COUNTIFS({D},A{r},{A},"?*")')
        ws.cell(row=r, column=6, value=f"=C{r}-E{r}")
        ws.cell(row=r, column=7, value=f'=IF(C{r}=0,0,E{r}/C{r})')
        ws.cell(row=r, column=8, value=f'=D{r}-COUNTIFS({D},A{r},{C},"Yes",{A},"?*")')
        for col in range(3, 9):
            c = ws.cell(row=r, column=col)
            c.font, c.border = Font(name=FONT, size=10, color=INK), BOX
            c.alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=7).number_format = "0%"
        r += 1
    first, end = 5, r - 1
    _cell(ws, r, 1, "Total", bold=True, fill=TINT, border=True)
    _cell(ws, r, 2, "", fill=TINT, border=True)
    for col in (3, 4, 5, 6, 8):
        L = get_column_letter(col)
        ws.cell(row=r, column=col, value=f"=SUM({L}{first}:{L}{end})")
    ws.cell(row=r, column=7, value=f"=IF(C{r}=0,0,E{r}/C{r})")
    for col in range(3, 9):
        c = ws.cell(row=r, column=col)
        c.font, c.border = Font(name=FONT, size=10, bold=True, color=INK), BOX
        c.fill, c.alignment = PatternFill("solid", fgColor=TINT), Alignment(horizontal="center")
    ws.cell(row=r, column=7).number_format = "0%"
    ws.conditional_formatting.add(f"H{first}:H{end}", FormulaRule(formula=[f"H{first}>0"],
                                  font=Font(bold=True, color=MAGENTA)))
    ws.freeze_panes = "A5"
    _fit_page(ws)


def render_questionnaire_xlsx(info: dict[str, Any], questions: list[dict[str, Any]],
                              dimensions: list[dict[str, Any]]) -> bytes:
    """info: client, project, industry, technologies, project_types, geography."""
    dim_names = {d["key"]: d["name"] for d in dimensions}
    order = {d["key"]: i for i, d in enumerate(dimensions)}
    qs = sorted(questions, key=lambda q: (order.get(q.get("dimension"), 999), not q.get("critical")))
    wb = Workbook()
    _cover(wb, info, qs)
    last = _questionnaire(wb, qs, dim_names)
    _summary(wb, qs, dimensions, last)
    wb.properties.title = f"{info['client']} assessment questionnaire"
    wb.properties.creator = "Insight Project Assessment Studio"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
