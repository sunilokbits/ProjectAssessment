"""Render the Insight-branded analysis document (Word) from ReportContent + assessment facts."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .schema import ReportContent

ASSETS = Path(__file__).with_name("assets")
MAGENTA = RGBColor(0xD3, 0x0E, 0x8C)
PURPLE = RGBColor(0x58, 0x28, 0x73)
INK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x59, 0x59, 0x59)
RAG_HEX = {"green": "1E8E5A", "amber": "D98E00", "red": "ED1944", "grey": "8C8C8C"}
RAG_MARK = {"green": "✓", "amber": "!", "red": "✕", "grey": "○"}


def _shade(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _styles(doc: Document) -> None:
    st = doc.styles
    normal = st["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.font.color.rgb = INK
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    normal.paragraph_format.space_after = Pt(6)
    for name, size, color in (("Title", 28, INK), ("Heading 1", 16, PURPLE), ("Heading 2", 12, MAGENTA), ("Heading 3", 10.5, INK)):
        s = st[name]
        s.font.name = "Arial"
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = color
        fonts = s.element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("w:asciiTheme", "w:hAnsiTheme"):
            fonts.attrib.pop(qn(attr), None)
        fonts.set(qn("w:ascii"), "Arial")
        fonts.set(qn("w:hAnsi"), "Arial")
        s.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        s.paragraph_format.space_after = Pt(6)


def _table(doc: Document, header: list[str], rows: list[list[str]], widths: list[float], rag_col: int | None = None,
           rag_states: list[str] | None = None) -> None:
    t = doc.add_table(rows=1, cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = doc.styles["Table Grid"]
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(9), RGBColor(0xFF, 0xFF, 0xFF)
        _shade(c, "582873")
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(9)
            if rag_col is not None and i == rag_col and rag_states:
                run.bold = True
                run.font.color.rgb = RGBColor.from_string(RAG_HEX.get(rag_states[ri], "8C8C8C"))
            if ri % 2 == 0:
                _shade(cells[i], "F7E3F1")
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Inches(w)
    doc.add_paragraph()


def _bullets(doc: Document, items: list[str]) -> None:
    for it in items:
        doc.add_paragraph(it, style="List Bullet")


def _footer(section, text_: str) -> None:
    p = section.footer.paragraphs[0]
    p.text = ""
    r = p.add_run(text_)
    r.italic, r.font.size, r.font.color.rgb = True, Pt(7.5), GREY
    p2 = section.footer.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p2.add_run()
    for tag, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), tag)
            run._r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = txt
            run._r.append(it)
    run.font.size = Pt(8)


def render_docx(content: ReportContent, f: dict[str, Any]) -> bytes:
    c, an = content, content.analysis
    doc = Document()
    _styles(doc)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(0.9)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    sec.different_first_page_header_footer = True
    _footer(sec, "Insight Proprietary & Confidential. Do Not Copy or Distribute.")
    hp = sec.header.paragraphs[0]
    hp.add_run().add_picture(str(ASSETS / "insight_logo.png"), width=Inches(0.9))
    hp.add_run(f"     {f['client']} · Analysis document").font.size = Pt(8)

    # ---- cover
    doc.add_picture(str(ASSETS / "insight_logo.png"), width=Inches(1.8))
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run("ANALYSIS DOCUMENT")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(10), MAGENTA
    doc.add_paragraph(c.title, style="Title")
    p = doc.add_paragraph()
    r = p.add_run(c.subtitle)
    r.font.size, r.font.color.rgb = Pt(14), GREY
    doc.add_paragraph()
    meta = [("Client", f["client"]), ("Engagement", f["project"]), ("Industry", f["industry"] + (f" — {', '.join(f['sub_domains'])}" if f["sub_domains"] else "")),
            ("Geography", f["geography"] or "—"), ("Stage", f["stage"].title()), ("Prepared by", "Insight"), ("Date", f"{date.today():%d %B %Y}")]
    t = doc.add_table(rows=0, cols=2)
    for k, v in meta:
        cells = t.add_row().cells
        cells[0].text, cells[1].text = "", ""
        a = cells[0].paragraphs[0].add_run(k)
        a.bold, a.font.size, a.font.color.rgb = True, Pt(9), PURPLE
        cells[1].paragraphs[0].add_run(v).font.size = Pt(9)
        cells[0].width, cells[1].width = Inches(1.4), Inches(4.8)
    doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run("Generated by Insight Project Assessment Studio. Figures marked illustrative are not commitments; regulatory "
                  "applicability must be confirmed by an authorised reviewer.")
    r.italic, r.font.size, r.font.color.rgb = True, Pt(8), GREY
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- 1 executive summary
    doc.add_heading("1. Executive summary", level=1)
    doc.add_paragraph(an.executive_narrative)
    for b in (c.summary.need, c.summary.response, c.summary.why_us, c.summary.value):
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{b.headline}: ")
        r.bold, r.font.color.rgb = True, PURPLE
        p.add_run(b.text)
    p = doc.add_paragraph()
    r = p.add_run("The ask: ")
    r.bold, r.font.color.rgb = True, MAGENTA
    p.add_run(c.summary.ask)

    # ---- 2 context
    doc.add_heading("2. Client context and classification", level=1)
    doc.add_paragraph(an.context_narrative)
    rows = [["Industry", f["industry"]], ["Sub-domains", ", ".join(f["sub_domains"]) or "—"],
            ["Technologies", ", ".join(f["technologies"]) or "—"], ["Project types", ", ".join(f["project_types"]) or "—"],
            ["Geography / regions", ", ".join(x for x in [f["geography"], ", ".join(f["regions"])] if x) or "—"],
            ["Data classifications", ", ".join(f["data_classes"]) or "—"],
            ["Client documents", ", ".join(d["filename"] for d in f["documents"]) or "—"]]
    _table(doc, ["Dimension", "Value"], rows, [1.8, 4.9])
    if c.opportunity.challenges:
        doc.add_heading("Challenges", level=2)
        _bullets(doc, [f"{x.title} — {x.text}" for x in c.opportunity.challenges])

    # ---- 3 readiness
    sc = f["scores"]
    doc.add_heading("3. Readiness assessment", level=1)
    doc.add_paragraph(an.readiness_commentary)
    states = [g["rag"]["state"] for g in sc["groups"]]
    _table(doc, ["Readiness area", "Score", "Status"],
           [[g["label"], f"{g['score']:.0f}%" if g["score"] is not None else "n/a", f"{RAG_MARK.get(g['rag']['state'], '○')} {g['rag']['label']}"] for g in sc["groups"]],
           [3.2, 1.0, 2.5], rag_col=2, rag_states=states)
    ov = sc["overall"]
    doc.add_paragraph(f"Overall comparable readiness: {ov['comparable']:.0f}% · domain-adjusted: {ov['domain_adjusted']:.0f}%."
                      if ov.get("comparable") is not None and ov.get("domain_adjusted") is not None else
                      "Overall readiness is not yet scored — answer the critical questions to produce comparable scores.")
    if sc["critical_gaps"]:
        doc.add_heading("Critical gaps", level=2)
        _bullets(doc, [g["text"] for g in sc["critical_gaps"][:15]])
    if c.findings.key_findings:
        doc.add_heading("Key findings", level=2)
        _bullets(doc, c.findings.key_findings)

    # ---- 4 risks
    doc.add_heading("4. Risks", level=1)
    doc.add_paragraph(an.risk_commentary)
    rk = f["risks"][:12]
    if rk:
        rag_of = {"high": "red", "medium": "amber", "low": "green"}
        _table(doc, ["Risk", "Rating", "L × I", "Mitigation"],
               [[r["title"], f"{RAG_MARK[rag_of.get(r['rating'], 'grey')]} {r['rating'].title()}", f"{r['likelihood']}×{r['impact']}", r["mitigation"] or "—"] for r in rk],
               [2.2, 0.9, 0.6, 3.0], rag_col=1, rag_states=[rag_of.get(r["rating"], "grey") for r in rk])

    # ---- 5 compliance
    doc.add_heading("5. Compliance considerations", level=1)
    doc.add_paragraph(an.compliance_commentary)
    if f["compliance"]:
        _table(doc, ["Regulation", "Status", "Source"], [[x["full_name"], x["status"] or "—", x["origin"].title()] for x in f["compliance"]], [3.9, 1.6, 1.2])

    # ---- 6 approach & value
    doc.add_heading(f"6. Recommended approach — {c.approach.framework_name}", level=1)
    doc.add_paragraph(c.approach.intro.replace(" Click to build each stage.", ""))
    _table(doc, ["Stage", "What happens", "Tooling"], [[f"{s.letter} · {s.name}", s.text, s.tooling] for s in c.approach.stages], [1.4, 3.7, 1.6])
    if c.accelerators.items:
        doc.add_heading("Accelerators", level=2)
        _bullets(doc, [f"{a.name}{' (live)' if a.live else ''} — {a.text}" for a in c.accelerators.items])
    doc.add_heading("Business value", level=2)
    doc.add_paragraph(c.value.intro)
    _table(doc, ["Area", "Target", "Measure"], [[s.category.title(), s.value, s.label] for s in c.value.stats], [2.2, 1.4, 3.1])
    p = doc.add_paragraph()
    r = p.add_run(c.value.disclaimer)
    r.italic, r.font.size, r.font.color.rgb = True, Pt(8), GREY
    if f["kpis"]:
        doc.add_heading("KPIs to baseline", level=2)
        _bullets(doc, [f"{k['name']} ({k['unit']}, {k['direction'].replace('_', ' ')})" if k["unit"] else k["name"] for k in f["kpis"][:10]])
    if f["architecture"]:
        doc.add_heading("Architecture patterns", level=2)
        _bullets(doc, [f"{a['name']} — {a['description']}" for a in f["architecture"]])

    # ---- 7 delivery
    doc.add_heading("7. Delivery plan and operating model", level=1)
    doc.add_paragraph(c.roadmap.intro)
    _table(doc, ["Phase", "Weeks"], [[p_.name, f"W{p_.start_week}–W{p_.end_week}"] for p_ in c.roadmap.phases], [4.9, 1.8])
    if c.roadmap.milestones:
        _bullets(doc, [f"Week {m.week}: {m.label}" for m in c.roadmap.milestones])
    doc.add_heading("Operating model", level=2)
    doc.add_paragraph(c.operating_model.intro)
    _table(doc, ["Role", "Responsibility"], [[r.title, r.text] for r in c.operating_model.roles], [2.2, 4.5])
    doc.add_heading("Governance", level=2)
    _bullets(doc, [f"{g.title} — {g.text}" for g in c.roadmap.governance])

    # ---- 8 recommendations & next steps
    doc.add_heading("8. Recommendations and next steps", level=1)
    _bullets(doc, an.recommendations)
    doc.add_paragraph(an.next_steps_narrative)
    _table(doc, ["When", "Action"], [[s.when, s.label] for s in c.options.next_steps], [1.4, 5.3])
    if f["assumptions"] or f["dependencies"]:
        doc.add_heading("Assumptions and dependencies", level=2)
        _bullets(doc, f["assumptions"][:8] + f["dependencies"][:8])

    # ---- appendix
    doc.add_heading("Appendix — method", level=1)
    m = sc.get("method", {})
    _bullets(doc, [f"{k.replace('_', ' ').title()}: {v}" for k, v in m.items()])
    doc.add_paragraph(f"Assessment coverage: {f['summary']['questions_total']} questions "
                      f"({', '.join(f'{k} {v}' for k, v in f['summary']['questions_by_origin'].items() if v)}), "
                      f"{f['summary']['duplicates_removed']} duplicates merged across domain packs.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
