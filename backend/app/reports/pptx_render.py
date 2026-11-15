"""Render ReportContent into an Insight-branded PowerPoint built on the corporate template."""
from __future__ import annotations

import copy
import io
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_THEME_COLOR as TC
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from .anim import animate
from .schema import SECTIONS, ReportContent

ASSETS = Path(__file__).with_name("assets")
ICON = ASSETS / "icons"
GREY = RGBColor(0x59, 0x59, 0x59)
MIST = RGBColor(0xE9, 0xDD, 0xF0)
LABEL = RGBColor(0xF4, 0xB6, 0xDE)
RULE = RGBColor(0xC9, 0xB3, 0xD3)
RAG = {"green": RGBColor(0x1E, 0x8E, 0x5A), "amber": RGBColor(0xD9, 0x8E, 0x00),
       "red": RGBColor(0xED, 0x19, 0x44), "grey": RGBColor(0xB5, 0xA9, 0xB8)}
EYEBROWS = {**SECTIONS, "battle_cards": "Battle card 1"}
SHORT = {"summary": "Summary", "opportunity": "Opportunity", "findings": "Findings", "approach": "Approach",
         "accelerators": "Accelerators", "value": "Value", "operating_model": "Op model", "roadmap": "Delivery",
         "why_us": "Why Insight", "options": "Options"}


# ----------------------------------------------------------------------------- drawing helpers
def _set_color(cf, c, tint=None):
    if isinstance(c, RGBColor):
        cf.rgb = c
    else:
        cf.theme_color = c
        if tint is not None:
            cf.brightness = tint


def box(slide, shape_type, x, y, w, h, c=None, tint=None, name=None, radius=None):
    sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    if c is not None:
        sh.fill.solid()
        _set_color(sh.fill.fore_color, c, tint)
    else:
        sh.fill.background()
    sh.line.fill.background()
    sh.shadow.inherit = False
    if radius is not None and shape_type == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    if name:
        sh.name = name
    return sh


def text(slide, x, y, w, h, runs, size=10.5, color=GREY, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, name=None, shape=None, italic=False, spacing=None):
    sh = shape or slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(runs, str):
        runs = [(runs, {})]
    p = tf.paragraphs[0]
    p.alignment = align
    for t, o in runs:
        if t == "\n":
            p = tf.add_paragraph()
            p.alignment = align
            continue
        r = p.add_run()
        r.text = t
        f = r.font
        f.size = Pt(o.get("size", size))
        f.bold = o.get("bold", bold)
        f.italic = o.get("italic", italic)
        _set_color(f.color, o.get("color", color), o.get("tint"))
        if spacing:
            r._r.get_or_add_rPr().set("spc", str(spacing))
    if name:
        sh.name = name
    return sh


def icon(slide, file, x, y, d, name=None):
    pic = slide.shapes.add_picture(str(ICON / file), Inches(x), Inches(y), Inches(d), Inches(d))
    if name:
        pic.name = name
    return pic


def numbered(slide, x, y, d, n, c=TC.ACCENT_2, size=9, name=None):
    o = box(slide, MSO_SHAPE.OVAL, x, y, d, d, c, name=name)
    text(slide, 0, 0, 0, 0, [(str(n), {})], size=size, bold=True, color=TC.BACKGROUND_1,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=o)
    return o


def label(slide, x, y, w, s, name=None, color=LABEL):
    return text(slide, x, y, w, 0.2, s.upper(), size=8, bold=True, color=color, name=name, spacing=100)


class Deck:
    def __init__(self, content: ReportContent, facts: dict[str, Any]):
        self.c, self.f = content, facts
        self.prs = Presentation(str(ASSETS / "insight_template.pptx"))
        self.layout = next(l for l in self.prs.slide_layouts if l.name == "Title Only 2")
        self.title_layout = next(l for l in self.prs.slide_layouts if l.name == "Title Slide 1")
        self.divider_layout = next(l for l in self.prs.slide_layouts if l.name == "Section Divider 1")
        self.tmpl_title, tmpl_content = self.prs.slides[0], self.prs.slides[1]
        self.slide_num_el = next(sh for sh in tmpl_content.shapes if sh.name == "Holder 6")._element
        self.offer_el = next(sh for sh in self.tmpl_title.shapes if sh.name == "Offer summary")._element
        self.slides: dict[str, Any] = {}
        self.links: list[tuple[Any, str]] = []
        self.order: list[Any] = []
        self.n = 0

    # -- slide scaffolding
    def content_slide(self, key, title, intro_text=None, internal=False):
        s = self.prs.slides.add_slide(self.layout)
        self.slides[key] = s
        self.order.append(s)
        if not internal:
            self.n += 1
        eyebrow = f"Internal · {EYEBROWS[key]}" if internal else f"{self.n:02d} · {EYEBROWS.get(key, key)}"
        for ph in s.placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text_frame.text = title
            elif ph.placeholder_format.idx == 11:
                ph.text_frame.text = eyebrow
        s.shapes._spTree.append(copy.deepcopy(self.slide_num_el))
        if internal:
            t = box(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.42, 0.14, 3.25, 0.24, TC.ACCENT_1, name="internal_tag", radius=0.5)
            text(s, 0, 0, 0, 0, [("BID TEAM ONLY · REMOVE BEFORE SUBMISSION", {})], size=7.5, bold=True,
                 color=TC.BACKGROUND_1, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=t)
        elif key != "summary" and "summary" in self.c.sections:
            self.chip(s, 8.62, 0.5, 1.05, 0.24, "↩ Summary", "summary", name="nav_summary")
        if intro_text:
            text(s, 0.33, 1.12, 9.34, 0.5, intro_text, size=11, color=GREY, name="intro")
        return s

    def chip(self, slide, x, y, w, h, lbl, target, size=7.5, name=None):
        sh = box(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, TC.ACCENT_3, 0.8, name=name or f"chip_{lbl}", radius=0.5)
        text(slide, 0, 0, 0, 0, [(lbl, {})], size=size, bold=True, color=TC.ACCENT_4,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=sh)
        self.links.append((sh, target))
        return sh

    @staticmethod
    def notes(slide, s):
        slide.notes_slide.notes_text_frame.text = s

    # -- title / closing
    def _set_runs(self, shape, texts):
        for p, t in zip(shape.text_frame.paragraphs, texts):
            if p.runs:
                p.runs[0].text = t
                for r in p.runs[1:]:
                    r._r.getparent().remove(r._r)
            else:
                p.text = t

    def title_slide(self):
        s = self.tmpl_title
        named = {sh.name: sh for sh in s.shapes}
        self._set_runs(named["Title 1"], [self.c.title])
        n = len(self.c.title)
        if n > 28:
            for r in named["Title 1"].text_frame.paragraphs[0].runs:
                r.font.size = Pt(30 if n <= 40 else 26 if n <= 52 else 22)
        self._set_runs(named["Subtitle 2"], [self.c.subtitle])
        self._set_runs(named["Offer summary"], [self.c.tagline, self.c.meta_line])
        named["Title 1"].name, named["Subtitle 2"].name, named["Offer summary"].name = "a1_title", "a1_sub", "a2_offer"
        targets = [k for k in self.c.sections if k != "battle_cards"][:6]
        if targets:
            text(s, 0.26, 4.5, 3, 0.16, "CONTENTS · CLICK TO JUMP", size=7, bold=True, color=GREY, name="a3_agenda", spacing=100)
            for i, k in enumerate(targets):
                self.chip(s, 0.26 + (i % 3) * 1.12, 4.7 + (i // 3) * 0.3, 1.06, 0.24, f"{i+1:02d}  {SHORT.get(k, k)}", k, size=7, name=f"a3_chip{i}")
        self.notes(s, f"{self.c.title}. Contents chips are clickable in slideshow mode.")

    def closing_slide(self):
        s = self.prs.slides.add_slide(self.title_layout)
        self.order.append(s)
        for ph in s.placeholders:
            idx = ph.placeholder_format.idx
            if idx == 0:
                ph.text_frame.text = self.c.closing.title
                ph.name = "a1_title"
            elif idx == 1:
                ph.text_frame.text = self.c.closing.message
                ph.name = "a2_sub"
        el = copy.deepcopy(self.offer_el)
        s.shapes._spTree.append(el)
        offer = s.shapes[-1]
        paras = offer.text_frame.paragraphs
        self._set_runs(offer, [self.c.closing.next_step])
        for p in paras[1:]:
            p._p.getparent().remove(p._p)
        offer.name = "a3_next"
        self.notes(s, "Close on the ask. Battle cards after this slide are internal.")
        return s

    # -- sections
    def s_summary(self):
        x = self.c.summary
        s = self.content_slide("summary", x.title, x.intro + " Click a block to see the detail.")
        blocks = [("THE NEED", TC.ACCENT_4, x.need, "opportunity"), ("OUR RESPONSE", TC.ACCENT_2, x.response, "approach"),
                  ("WHY INSIGHT", TC.ACCENT_5, x.why_us, "why_us"), ("THE VALUE", TC.ACCENT_6, x.value, "value")]
        for i, (lbl, col, b, tgt) in enumerate(blocks):
            bx, g = 0.33 + i * 2.37, f"a{i+1}"
            card = box(s, MSO_SHAPE.RECTANGLE, bx, 1.72, 2.25, 2.42, TC.ACCENT_3, 0.8, name=f"{g}_card")
            box(s, MSO_SHAPE.RECTANGLE, bx, 1.72, 2.25, 0.34, col, name=f"{g}_head")
            text(s, bx + 0.14, 1.72, 2.0, 0.34, lbl, size=8, bold=True, color=TC.BACKGROUND_1, anchor=MSO_ANCHOR.MIDDLE, name=f"{g}_lbl", spacing=100)
            text(s, bx + 0.14, 2.17, 1.98, 0.5, b.headline, size=12, bold=True, color=TC.TEXT_1, name=f"{g}_h")
            text(s, bx + 0.14, 2.7, 1.98, 1.0, b.text, size=9, color=GREY, name=f"{g}_d")
            if tgt in self.c.sections:
                lk = text(s, bx + 0.14, 3.8, 1.9, 0.2, [("See detail →", {})], size=8.5, bold=True, color=TC.ACCENT_2, name=f"{g}_link")
                self.links += [(card, tgt), (lk, tgt)]
        box(s, MSO_SHAPE.RECTANGLE, 0.33, 4.3, 9.34, 0.82, TC.ACCENT_4, name="a5_ask")
        label(s, 0.55, 4.4, 2, "The ask", name="a5_lbl")
        text(s, 0.55, 4.62, 8.9, 0.44, x.ask, size=10.5, bold=True, color=TC.BACKGROUND_1, name="a5_txt")
        self.notes(s, "Lead with the answer; each block is clickable. Close on the ask.")

    def s_opportunity(self):
        x = self.c.opportunity
        s = self.content_slide("opportunity", x.title, x.intro)
        icons = ["FiClock_magenta.png", "FiTarget_magenta.png", "FiLink_magenta.png"]
        for i, ch in enumerate(x.challenges[:3]):
            bx = 0.33 + i * 3.17
            icon(s, icons[i], bx, 1.78, 0.44, name=f"a{i+1}_ic")
            text(s, bx, 2.3, 2.95, 0.26, ch.title, size=13.5, bold=True, color=TC.TEXT_1, name=f"a{i+1}_h")
            text(s, bx, 2.58, 2.9, 0.7, ch.text, size=10, color=GREY, name=f"a{i+1}_d")
        if x.client_questions:
            box(s, MSO_SHAPE.RECTANGLE, 0.33, 3.38, 9.34, 1.74, TC.ACCENT_4, name="a4_panel")
            label(s, 0.55, 3.5, 5, "What the client asked  →  Insight's answer", name="a4_lbl")
            for i, qa in enumerate(x.client_questions[:3]):
                bx = 0.55 + i * 3.07
                text(s, bx, 3.8, 2.8, 0.4, qa.question, size=10.5, bold=True, color=TC.BACKGROUND_1, name=f"a5_q{i}")
                text(s, bx, 4.22, 2.8, 0.8, qa.answer, size=9.5, color=MIST, name=f"a5_a{i}")
        self.notes(s, "Frame the client's need in their words, then answer their questions directly.")

    def s_findings(self):
        x, sc = self.c.findings, self.f["scores"]
        s = self.content_slide("findings", x.title, x.intro)
        ov = sc["overall"]
        val = ov.get("domain_adjusted") if ov.get("domain_adjusted") is not None else ov.get("comparable")
        rag = (ov.get("domain_adjusted_rag") or ov.get("comparable_rag") or {"state": "grey", "label": "Not assessed"})
        box(s, MSO_SHAPE.RECTANGLE, 0.33, 1.62, 4.55, 3.5, TC.ACCENT_3, 0.85, name="a1_panel")
        label(s, 0.5, 1.74, 3, "Readiness by area", name="a1_lbl", color=TC.ACCENT_2)
        text(s, 3.0, 1.66, 1.75, 0.42, f"{val:.0f}%" if val is not None else "–", size=22, bold=True, color=TC.ACCENT_4,
             align=PP_ALIGN.RIGHT, name="a1_overall")
        text(s, 2.2, 2.08, 2.55, 0.18, f"Overall · {rag['label']}", size=7.5, color=GREY, align=PP_ALIGN.RIGHT, name="a1_rag")
        groups = sc["groups"][:7]
        for i, g in enumerate(groups):
            y = 2.36 + i * 0.38
            text(s, 0.5, y, 1.75, 0.3, g["label"].replace(" Readiness", ""), size=8.5, bold=True, color=TC.TEXT_1, anchor=MSO_ANCHOR.MIDDLE, name=f"a2_gl{i}")
            box(s, MSO_SHAPE.RECTANGLE, 2.3, y + 0.08, 1.8, 0.14, RGBColor(0xFF, 0xFF, 0xFF), name=f"a2_track{i}")
            score = g["score"]
            state = g["rag"]["state"]
            if score:
                box(s, MSO_SHAPE.RECTANGLE, 2.3, y + 0.08, max(0.04, 1.8 * score / 100), 0.14, RAG.get(state, RAG["grey"]), name=f"a2_bar{i}")
            mark = {"green": "✓", "amber": "!", "red": "✕"}.get(state, "○")
            text(s, 4.15, y, 0.65, 0.3, f"{mark} {score:.0f}%" if score is not None else "○ n/a", size=8, bold=True,
                 color=RAG.get(state, GREY) if state != "grey" else GREY, anchor=MSO_ANCHOR.MIDDLE, name=f"a2_v{i}")
        box(s, MSO_SHAPE.RECTANGLE, 5.05, 1.62, 4.62, 3.5, TC.ACCENT_4, name="a3_panel")
        label(s, 5.25, 1.74, 4, "Key findings", name="a3_lbl")
        for i, kf in enumerate(x.key_findings[:6]):
            y = 2.04 + i * 0.5
            numbered(s, 5.25, y + 0.02, 0.24, i + 1, TC.ACCENT_2, size=8, name=f"a{4+i}_n")
            text(s, 5.6, y, 3.9, 0.48, kf, size=8.5, color=TC.BACKGROUND_1, name=f"a{4+i}_t")
        self.notes(s, "Scores come straight from the assessment. Status colours are always paired with a symbol and label.")

    def s_approach(self):
        x = self.c.approach
        s = self.content_slide("approach", x.title, x.intro)
        stages = x.stages[:6] or []
        n = max(1, len(stages))
        gap = 0.11
        pw = (9.34 - gap * (n - 1)) / n
        for i, st in enumerate(stages):
            bx, core, g = 0.33 + i * (pw + gap), i == x.core_stage_index, f"a{i+1}"
            box(s, MSO_SHAPE.RECTANGLE, bx, 1.72, pw, 2.0, TC.ACCENT_4 if core else TC.ACCENT_3, None if core else 0.8, name=f"{g}_card")
            numbered(s, bx + 0.14, 1.84, 0.44, st.letter[:2], TC.ACCENT_2 if core else TC.ACCENT_4, size=15, name=f"{g}_letter" if i == 0 else f"{g}_l")
            text(s, bx + 0.14, 2.38, pw - 0.24, 0.26, st.name, size=12 if n <= 5 else 11, bold=True, color=TC.BACKGROUND_1 if core else TC.TEXT_1, name=f"{g}_h")
            text(s, bx + 0.14, 2.66, pw - 0.26, 0.74, st.text, size=9 if n <= 5 else 8, color=MIST if core else GREY, name=f"{g}_d")
            text(s, bx + 0.14, 3.42, pw - 0.26, 0.24, st.tooling, size=7.5, bold=True, color=LABEL if core else TC.ACCENT_2, name=f"{g}_t")
            if i < n - 1:
                box(s, MSO_SHAPE.RIGHT_ARROW, bx + pw + 0.01, 2.6, 0.09, 0.13, RULE)
        g = f"a{n+1}"
        box(s, MSO_SHAPE.RECTANGLE, 0.33, 3.86, 9.34, 1.26, TC.ACCENT_4, name=f"{g}_panel")
        label(s, 0.55, 3.96, 4, f"{x.framework_name} · AI automation & tooling in every stage", name=f"{g}_lbl")
        text(s, 0.55, 4.2, 3.6, 0.32, x.first_value_headline, size=16, bold=True, color=TC.BACKGROUND_1, name=f"{g}_big")
        text(s, 0.55, 4.54, 3.6, 0.5, x.first_value_text, size=9, color=MIST, name=f"{g}_txt")
        tl = x.timeline[:4]
        for i, w in enumerate(tl):
            bx = 4.55 + i * 1.27
            box(s, MSO_SHAPE.RECTANGLE, bx, 4.12, 1.17, 0.82, TC.ACCENT_3, name=f"{g}_ph{i}")
            text(s, bx + 0.1, 4.2, 1.0, 0.2, w.when, size=8, bold=True, color=LABEL, name=f"{g}_pw{i}")
            text(s, bx + 0.1, 4.42, 1.0, 0.48, w.label, size=9.5, bold=True, color=TC.BACKGROUND_1, name=f"{g}_pp{i}")
        self.notes(s, f"{x.framework_name}: click once per stage. The highlighted stage is the core of the method.")

    def s_accelerators(self):
        x = self.c.accelerators
        s = self.content_slide("accelerators", x.title, x.intro)
        discs = [TC.ACCENT_4, TC.ACCENT_5, TC.ACCENT_2, TC.ACCENT_1, TC.ACCENT_6, TC.ACCENT_3]
        icons = ["FiClipboard_white.png", "FiFileText_white.png", "FiCpu_white.png", "FiTrendingUp_white.png", "FiShield_white.png"]
        cw, ch, gx, gy = 3.0, 1.6, 0.17, 0.16
        for i, acc in enumerate(x.items[:6]):
            bx, by, g = 0.33 + (i % 3) * (cw + gx), 1.62 + (i // 3) * (ch + gy), f"a{i+1}"
            box(s, MSO_SHAPE.RECTANGLE, bx, by, cw, ch, TC.ACCENT_3, 0.8, name=f"{g}_card")
            box(s, MSO_SHAPE.OVAL, bx + 0.16, by + 0.15, 0.44, 0.44, discs[i % 6], name=f"{g}_disc")
            nm = acc.name.lower()
            is_dbx = any(w in nm for w in ("dbx", "databricks", "migrat"))
            kw = [("assess", 0), ("document", 1), ("process", 1), ("agent", 2), ("automat", 2), ("value", 3), ("roi", 3),
                  ("govern", 4), ("secur", 4), ("responsible", 4)]
            ic = next((idx for w, idx in kw if w in nm), i % len(icons))
            pic = s.shapes.add_picture(str(ASSETS / "dbx_white.png") if is_dbx else str(ICON / icons[ic]),
                                       Inches(bx + 0.26), Inches(by + 0.25), Inches(0.24), Inches(0.24))
            pic.name = f"{g}_icon"
            st = box(s, MSO_SHAPE.ROUNDED_RECTANGLE, bx + cw - 0.78, by + 0.2, 0.62, 0.22, TC.BACKGROUND_1, name=f"{g}_stage", radius=0.5)
            text(s, 0, 0, 0, 0, [(acc.stage_tags[:10], {})], size=7.5, bold=True, color=TC.ACCENT_2, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=st)
            if acc.live:
                lv = box(s, MSO_SHAPE.ROUNDED_RECTANGLE, bx + cw - 1.5, by + 0.2, 0.64, 0.22, TC.ACCENT_4, name=f"{g}_live", radius=0.5)
                text(s, 0, 0, 0, 0, [("● LIVE", {})], size=7, bold=True, color=TC.BACKGROUND_1, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=lv)
            text(s, bx + 0.16, by + 0.68, cw - 0.3, 0.24, acc.name, size=11, bold=True, color=TC.TEXT_1, name=f"{g}_h")
            text(s, bx + 0.16, by + 0.94, cw - 0.32, 0.36 if acc.url else 0.5, acc.text, size=8.5, color=GREY, name=f"{g}_d")
            if acc.url.startswith("http"):
                lk = text(s, bx + 0.16, by + 1.32, 1.8, 0.2, [("Open live demo →", {})], size=8.5, bold=True, color=TC.ACCENT_2, name=f"{g}_link")
                lk.click_action.hyperlink.address = acc.url
        text(s, 0.33, 5.0, 9.3, 0.18, x.footnote, size=7.5, italic=True, color=GREY)
        self.notes(s, "Accelerators marked LIVE can be demonstrated today.")

    def s_value(self):
        x = self.c.value
        s = self.content_slide("value", x.title, x.intro)
        cols = [TC.ACCENT_4, TC.ACCENT_2, TC.ACCENT_5, TC.ACCENT_6]
        for i, st in enumerate(x.stats[:4]):
            bx, by, g = 0.33 + (i % 2) * 2.25, 1.62 + (i // 2) * 1.68, f"a{i+1}"
            box(s, MSO_SHAPE.RECTANGLE, bx, by, 2.13, 1.56, cols[i], name=f"{g}_tile")
            text(s, bx + 0.16, by + 0.14, 1.9, 0.2, st.category.upper()[:28], size=7.5, bold=True, color=TC.BACKGROUND_1, name=f"{g}_k", spacing=100)
            text(s, bx + 0.16, by + 0.42, 1.9, 0.55, st.value, size=28, bold=True, color=TC.BACKGROUND_1, name=f"{g}_v")
            text(s, bx + 0.16, by + 1.06, 1.9, 0.4, st.label, size=10.5, color=TC.BACKGROUND_1, name=f"{g}_l")
        box(s, MSO_SHAPE.RECTANGLE, 4.95, 1.62, 4.72, 3.24, TC.ACCENT_3, 0.8, name="a5_chartbg")
        n = min(len(x.chart.categories), len(x.chart.benefit), len(x.chart.investment))
        if n >= 2:
            cd = CategoryChartData()
            cd.categories = x.chart.categories[:n]
            cd.add_series("Cumulative benefit", x.chart.benefit[:n])
            cd.add_series("Cumulative investment", x.chart.investment[:n])
            gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(5.05), Inches(1.68), Inches(4.52), Inches(2.78), cd)
            gf.name = "a5_chart"
            ch = gf.chart
            ch.has_title = True
            ch.chart_title.text_frame.text = x.chart.title
            tf = ch.chart_title.text_frame.paragraphs[0].runs[0].font
            tf.size, tf.bold = Pt(9), True
            _set_color(tf.color, TC.TEXT_1)
            ch.has_legend = True
            ch.legend.position = XL_LEGEND_POSITION.BOTTOM
            ch.legend.include_in_layout = False
            ch.legend.font.size = Pt(8)
            _set_color(ch.legend.font.color, GREY)
            for ser, col in zip(ch.plots[0].series, (TC.ACCENT_2, TC.ACCENT_4)):
                ser.smooth = False
                ser.format.line.width = Pt(2.25)
                _set_color(ser.format.line.color, col)
                ser.marker.style = XL_MARKER_STYLE.CIRCLE
                ser.marker.size = 5
                ser.marker.format.fill.solid()
                _set_color(ser.marker.format.fill.fore_color, col)
                ser.marker.format.line.fill.background()
            va, ca = ch.value_axis, ch.category_axis
            va.has_major_gridlines = True
            va.major_gridlines.format.line.color.rgb = RGBColor(0xE3, 0xD5, 0xE0)
            va.major_gridlines.format.line.width = Pt(0.5)
            va.format.line.fill.background()
            va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "#,##0", False
            for ax in (va, ca):
                ax.tick_labels.font.size = Pt(8)
                _set_color(ax.tick_labels.font.color, GREY)
            ca.format.line.color.rgb = RULE
        text(s, 5.12, 4.5, 4.4, 0.26, x.payback_note, size=10.5, bold=True, color=TC.ACCENT_2, name="a6_payback")
        text(s, 0.33, 4.95, 9.3, 0.2, x.disclaimer, size=7.5, italic=True, color=GREY)
        self.notes(s, "Figures are illustrative until the client's baseline is captured.")

    def s_operating_model(self):
        x = self.c.operating_model
        s = self.content_slide("operating_model", x.title, x.intro)
        hx, hy, hd = 2.63, 2.73, 1.22
        icons = ["FiCompass", "FiCode", "FiCpu", "FiUsers", "FiGlobe", "FiAward"]
        pos = [(0.33, 1.68), (0.33, 2.86), (0.33, 4.04), (4.08, 1.68), (4.08, 2.86), (4.08, 4.04)]
        for i, r in enumerate(x.roles[:6]):
            bx, by = pos[i]
            g, cw2, ch2 = ("a2" if i < 3 else "a3"), 1.98, 1.04
            ln = s.shapes.add_connector(1, Inches(bx + cw2 if bx < 2 else bx), Inches(by + ch2 / 2), Inches(hx + hd / 2), Inches(hy + hd / 2))
            ln.line.color.rgb = RULE
            ln.line.width = Pt(1)
            ln.name = f"{g}_ln{i}"
            box(s, MSO_SHAPE.RECTANGLE, bx, by, cw2, ch2, TC.ACCENT_3, 0.8, name=f"{g}_card{i}")
            icon(s, f"{icons[i]}_magenta.png", bx + 0.12, by + 0.12, 0.3, name=f"{g}_ic{i}")
            text(s, bx + 0.5, by + 0.08, 1.42, 0.4, r.title, size=10, bold=True, color=TC.TEXT_1, anchor=MSO_ANCHOR.MIDDLE, name=f"{g}_h{i}")
            text(s, bx + 0.12, by + 0.52, 1.78, 0.48, r.text, size=8.5, color=GREY, name=f"{g}_d{i}")
        hub = box(s, MSO_SHAPE.OVAL, hx, hy, hd, hd, TC.ACCENT_4, name="a1_hub")
        text(s, 0, 0, 0, 0, [(x.hub_label[:18], {"size": 13, "bold": True}), ("\n", {}), ("Business & process owners", {"size": 8})],
             color=TC.BACKGROUND_1, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=hub)
        box(s, MSO_SHAPE.RECTANGLE, 6.38, 1.68, 3.29, 3.4, TC.ACCENT_4, name="a4_panel")
        label(s, 6.58, 1.8, 3, x.comparison_title, name="a4_lbl")
        for i, cmp_ in enumerate(x.comparison[:4]):
            y = 2.1 + i * 0.73
            text(s, 6.58, y, 2.9, 0.18, cmp_.dimension.upper(), size=7, bold=True, color=LABEL, name=f"a5_dim{i}", spacing=60)
            text(s, 6.58, y + 0.19, 2.95, 0.2, [("✕  ", {"color": LABEL}), (cmp_.traditional, {})], size=8.5, color=MIST, name=f"a5_old{i}")
            text(s, 6.58, y + 0.4, 2.95, 0.22, [("✓  ", {"color": LABEL}), (cmp_.ours, {})], size=9, bold=True, color=TC.BACKGROUND_1, name=f"a5_new{i}")
        self.notes(s, "FDE = Forward Deployed Engineer: engineers who work inside the client's teams.")

    def s_roadmap(self):
        x = self.c.roadmap
        s = self.content_slide("roadmap", x.title, x.intro)
        weeks = max([p.end_week for p in x.phases] + [m.week for m in x.milestones] + [12])
        weeks = min(max(weeks, 4), 26)
        X0, X1 = 2.55, 9.67
        wk = (X1 - X0) / weeks
        step = 1 if weeks <= 13 else 2
        for w in range(0, weeks + 1, step):
            gx = X0 + w * wk
            text(s, gx - 0.2, 1.58, 0.4, 0.16, f"W{w}", size=7, bold=True, color=GREY, align=PP_ALIGN.CENTER)
            ln = s.shapes.add_connector(1, Inches(gx), Inches(1.78), Inches(gx), Inches(3.5))
            ln.line.color.rgb = RGBColor(0xEE, 0xE4, 0xEC)
            ln.line.width = Pt(0.5)
        cols = [TC.ACCENT_4, TC.ACCENT_2, TC.ACCENT_5, TC.ACCENT_6, TC.ACCENT_3, TC.ACCENT_1]
        phases = x.phases[:6]
        rh = min(0.32, 1.6 / max(1, len(phases)))
        for i, p in enumerate(phases):
            y = 1.86 + i * rh
            a_, b_ = max(0, p.start_week), min(weeks, max(p.end_week, p.start_week + 1))
            text(s, 0.33, y, 2.15, rh - 0.06, p.name, size=9, bold=True, color=TC.TEXT_1, anchor=MSO_ANCHOR.MIDDLE, name=f"a{i+1}_gl")
            box(s, MSO_SHAPE.RECTANGLE, X0 + a_ * wk + 0.02, y + 0.02, max(0.08, (b_ - a_) * wk - 0.04), rh - 0.12, cols[i], name=f"a{i+1}_bar")
        g = len(phases) + 1
        for i, m in enumerate(x.milestones[:4]):
            mx = X0 + min(m.week, weeks) * wk
            box(s, MSO_SHAPE.DIAMOND, mx - 0.09, 3.5, 0.18, 0.18, TC.ACCENT_2, name=f"a{g}_md{i}")
            right = mx > X1 - 0.6
            text(s, mx - 1.2 if right else max(0.33, mx - 0.6), 3.72, 1.2, 0.3, m.label, size=7, bold=True, color=TC.ACCENT_4,
                 align=PP_ALIGN.RIGHT if right else PP_ALIGN.CENTER, name=f"a{g}_ml{i}")
        label(s, 0.33, 4.1, 3, "Governance", name=f"a{g+1}_gl", color=TC.ACCENT_2)
        for i, gv in enumerate(x.governance[:3]):
            bx = 0.33 + i * 1.62
            box(s, MSO_SHAPE.RECTANGLE, bx, 4.32, 1.54, 0.82, TC.ACCENT_3, 0.8, name=f"a{g+1}_g{i}")
            text(s, bx + 0.1, 4.38, 1.36, 0.2, gv.title, size=8.5, bold=True, color=TC.TEXT_1, name=f"a{g+1}_gh{i}")
            text(s, bx + 0.1, 4.6, 1.36, 0.52, gv.text, size=7.5, color=GREY, name=f"a{g+1}_gd{i}")
        box(s, MSO_SHAPE.RECTANGLE, 5.25, 4.1, 4.42, 1.04, TC.ACCENT_4, name=f"a{g+2}_risk")
        label(s, 5.42, 4.17, 4, "Key risks  →  mitigations", name=f"a{g+2}_rl")
        for i, r in enumerate(x.risks[:4]):
            bx, by = 5.42 + (i % 2) * 2.12, 4.42 + (i // 2) * 0.34
            text(s, bx, by, 2.05, 0.32, [(r.risk, {"bold": True, "color": TC.BACKGROUND_1}), ("\n", {}), ("→ " + r.mitigation, {"color": MIST})],
                 size=7, name=f"a{g+2}_r{i}")
        self.notes(s, "Milestones are decision gates. Timeline is indicative and confirmed in the sprint.")

    def s_why_us(self):
        x = self.c.why_us
        s = self.content_slide("why_us", x.title)
        box(s, MSO_SHAPE.RECTANGLE, 0.33, 1.2, 3.05, 3.92, TC.ACCENT_4, name="a1_panel")
        label(s, 0.55, 1.36, 2.6, "Our commitment", name="a1_lbl")
        text(s, 0.55, 1.65, 2.65, 1.9, x.commitment, size=14, bold=True, color=TC.BACKGROUND_1, name="a1_stmt")
        for i, ps in enumerate(x.proof_stats[:3]):
            y = 3.62 + i * 0.47
            text(s, 0.55, y, 0.95, 0.4, ps.when, size=15, bold=True, color=LABEL, name=f"a1_v{i}")
            text(s, 1.5, y + 0.06, 1.8, 0.35, ps.label, size=9, color=MIST, name=f"a1_l{i}")
        themes = x.themes[:5]
        rh = 3.92 / max(1, len(themes))
        for i, th in enumerate(themes):
            y, g = 1.2 + i * rh, f"a{i+2}"
            box(s, MSO_SHAPE.RECTANGLE, 3.55, y, 6.12, rh - 0.08, TC.ACCENT_3, 0.8, name=f"{g}_row")
            numbered(s, 3.7, y + (rh - 0.08) / 2 - 0.18, 0.36, i + 1, TC.ACCENT_2, size=11, name=f"{g}_n")
            text(s, 4.2, y + 0.08, 5.35, 0.24, th.title, size=11, bold=True, color=TC.TEXT_1, name=f"{g}_h")
            text(s, 4.2, y + 0.34, 5.35, rh - 0.44, th.text, size=9, color=GREY, name=f"{g}_d")
        self.notes(s, "Repeat these win themes in every conversation and in the written response.")

    def s_options(self):
        x = self.c.options
        s = self.content_slide("options", x.title, x.intro)
        items = x.items[:3]
        n = max(1, len(items))
        cw = (9.34 - 0.17 * (n - 1)) / n
        for i, o in enumerate(items):
            bx, g, rec = 0.33 + i * (cw + 0.17), f"a{i+1}", o.recommended
            box(s, MSO_SHAPE.RECTANGLE, bx, 1.62, cw, 2.48, TC.ACCENT_4 if rec else TC.ACCENT_3, None if rec else 0.8, name=f"{g}_card")
            fg, sub_c, body_c = (TC.BACKGROUND_1, LABEL, MIST) if rec else (TC.TEXT_1, TC.ACCENT_2, GREY)
            text(s, bx + 0.18, 1.74, 1.4, 0.2, o.tag.upper(), size=8, bold=True, color=sub_c, name=f"{g}_tag", spacing=100)
            if rec:
                r = box(s, MSO_SHAPE.ROUNDED_RECTANGLE, bx + cw - 1.38, 1.72, 1.22, 0.24, TC.ACCENT_2, name=f"{g}_rec", radius=0.5)
                text(s, 0, 0, 0, 0, [("RECOMMENDED START", {})], size=7, bold=True, color=TC.BACKGROUND_1, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=r)
            text(s, bx + 0.18, 2.02, cw - 0.3, 0.32, o.name, size=15, bold=True, color=fg, name=f"{g}_h")
            text(s, bx + 0.18, 2.36, cw - 0.3, 0.22, o.terms, size=9, bold=True, color=sub_c, name=f"{g}_sub")
            for k, it in enumerate(o.outputs[:3]):
                text(s, bx + 0.18, 2.72 + k * 0.42, cw - 0.3, 0.4, [("✓  ", {"color": sub_c, "bold": True}), (it, {})], size=9, color=body_c, name=f"{g}_i{k}")
        label(s, 0.33, 4.25, 3, "Next steps", name="a4_lbl", color=TC.ACCENT_2)
        steps = x.next_steps[:4]
        for i, st in enumerate(steps):
            bx = 0.33 + i * 2.37
            numbered(s, bx, 4.5, 0.3, i + 1, TC.ACCENT_4, name=f"a5_n{i}")
            text(s, bx + 0.38, 4.47, 1.9, 0.18, st.when, size=8, bold=True, color=TC.ACCENT_2, name=f"a5_w{i}")
            text(s, bx + 0.38, 4.66, 1.9, 0.46, st.label, size=8.5, color=TC.TEXT_1, name=f"a5_t{i}")
        self.notes(s, "Commercial structure only - confirm fees with the deal desk before sharing.")

    def _table(self, slide, x, y, w, col_w, rows, row_h, header_h=0.3, name=None, emphasis_col=None):
        nrows, ncols = len(rows), len(rows[0])
        gf = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y), Inches(w), Inches(header_h + row_h * (nrows - 1)))
        if name:
            gf.name = name
        tbl = gf.table
        tblPr = tbl._tbl.tblPr
        for child in list(tblPr):
            if child.tag.endswith("tableStyleId"):
                tblPr.remove(child)
        for j, c in enumerate(col_w):
            tbl.columns[j].width = Inches(c)
        tbl.rows[0].height = Inches(header_h)
        for r in range(1, nrows):
            tbl.rows[r].height = Inches(row_h)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                cell = tbl.cell(r, c)
                cell.margin_left = cell.margin_right = Inches(0.07)
                cell.margin_top = cell.margin_bottom = Inches(0.04)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE if r == 0 else MSO_ANCHOR.TOP
                cell.fill.solid()
                if r == 0:
                    _set_color(cell.fill.fore_color, TC.ACCENT_4)
                elif c == emphasis_col:
                    _set_color(cell.fill.fore_color, TC.ACCENT_2, 0.85)
                elif c == 0:
                    _set_color(cell.fill.fore_color, TC.ACCENT_3, 0.7)
                else:
                    _set_color(cell.fill.fore_color, TC.ACCENT_3, 0.9)
                tcPr = cell._tc.get_or_add_tcPr()
                for k, edge in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
                    ln = tcPr.makeelement(qn(edge), {"w": "19050"})
                    sf = ln.makeelement(qn("a:solidFill"), {})
                    sf.append(sf.makeelement(qn("a:srgbClr"), {"val": "FFFFFF"}))
                    ln.append(sf)
                    tcPr.insert(k, ln)
                tf = cell.text_frame
                tf.word_wrap = True
                tf.paragraphs[0].text = ""
                rr = tf.paragraphs[0].add_run()
                rr.text = val
                rr.font.size = Pt(8.5 if r == 0 else (9 if c == 0 else 8.5))
                rr.font.bold = r == 0 or c == 0 or c == emphasis_col
                _set_color(rr.font.color, TC.BACKGROUND_1 if r == 0 else (TC.ACCENT_4 if c == emphasis_col else (TC.TEXT_1 if c == 0 else GREY)))
        return gf

    def s_battle_cards(self):
        bc = self.c.battle_cards
        d = self.prs.slides.add_slide(self.divider_layout)
        self.order.append(d)
        for ph in d.placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text_frame.text = "Bid team only: battle cards"
                ph.name = "a1_title"
        text(d, 0.29, 3.95, 6.5, 0.6, "Competitive positioning, objection handling and questions to ask the client. Internal — "
             "remove this section before any client submission.", size=12, color=GREY, name="a2_sub")
        if bc.competitors:
            s = self.content_slide("battle_cards", "How we win against each type of competitor",
                                   "Typical positioning for each competitor type — validate against what we hear from the client.", internal=True)
            rows = [["Competitor type", "Likely pitch", "Where they are strong", "Where they are exposed", "How Insight wins"]]
            rows += [[c.type, c.pitch, c.strengths, c.weaknesses, c.how_we_win] for c in bc.competitors[:5]]
            rh = min(0.8, 3.2 / max(1, len(rows) - 1))
            self._table(s, 0.33, 1.62, 9.34, [1.5, 1.8, 1.7, 2.04, 2.3], rows, rh, name="a1_table", emphasis_col=4)
            self.notes(s, "Internal. Typical positions per competitor type, not claims about named firms.")
        if bc.objections or bc.questions:
            s = self.prs.slides.add_slide(self.layout)
            self.order.append(s)
            for ph in s.placeholders:
                if ph.placeholder_format.idx == 0:
                    ph.text_frame.text = "Objections, responses and questions to ask"
                elif ph.placeholder_format.idx == 11:
                    ph.text_frame.text = "Internal · Battle card 2"
            s.shapes._spTree.append(copy.deepcopy(self.slide_num_el))
            t = box(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.42, 0.14, 3.25, 0.24, TC.ACCENT_1, name="internal_tag", radius=0.5)
            text(s, 0, 0, 0, 0, [("BID TEAM ONLY · REMOVE BEFORE SUBMISSION", {})], size=7.5, bold=True,
                 color=TC.BACKGROUND_1, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=t)
            label(s, 0.33, 1.2, 4, "Objection  →  response", name="a1_lbl", color=TC.ACCENT_2)
            for i, o in enumerate(bc.objections[:5]):
                y, g = 1.45 + i * 0.74, f"a{i+1}"
                box(s, MSO_SHAPE.RECTANGLE, 0.33, y, 5.7, 0.66, TC.ACCENT_3, 0.8, name=f"{g}_row")
                text(s, 0.48, y + 0.07, 5.45, 0.22, o.objection, size=9.5, bold=True, color=TC.ACCENT_4, name=f"{g}_o")
                text(s, 0.48, y + 0.31, 5.45, 0.32, o.response, size=8.5, color=GREY, name=f"{g}_r")
            box(s, MSO_SHAPE.RECTANGLE, 6.2, 1.2, 3.47, 3.91, TC.ACCENT_4, name="a6_panel")
            label(s, 6.4, 1.34, 3, "Questions to ask the client", name="a6_lbl")
            text(s, 6.4, 1.56, 3.1, 0.4, "Each one steers the evaluation toward our strengths.", size=8.5, color=MIST, name="a6_sub")
            for i, q in enumerate(bc.questions[:5]):
                y = 2.0 + i * 0.6
                numbered(s, 6.4, y, 0.26, i + 1, TC.ACCENT_2, size=8, name=f"a7_n{i}")
                text(s, 6.76, y - 0.02, 2.78, 0.56, q, size=8.5, color=TC.BACKGROUND_1, name=f"a7_q{i}")
            self.notes(s, "Internal. Rehearse these responses before orals.")

    # -- assemble
    def build(self) -> bytes:
        self.title_slide()
        for key in self.c.sections:
            if key != "battle_cards" and key in SECTIONS:
                getattr(self, f"s_{key}")()
        self.closing_slide()
        if "battle_cards" in self.c.sections:
            self.s_battle_cards()
        for sh, key in self.links:
            if key in self.slides:
                sh.click_action.target_slide = self.slides[key]
        # order: title, generated slides; drop the template's sample content slide
        lst = self.prs.slides._sldIdLst
        pairs = list(zip(list(lst), list(self.prs.slides)))
        el_of = {id(sl): el for el, sl in pairs}
        keep = [self.tmpl_title] + self.order
        keep_ids = {id(k) for k in keep}
        for el, sl in pairs:
            if id(sl) not in keep_ids:
                self.prs.part.drop_rel(el.rId)
                lst.remove(el)
        for k in keep:
            lst.remove(el_of[id(k)])
            lst.append(el_of[id(k)])
        self.prs.core_properties.title = self.c.title
        self.prs.core_properties.author = "Insight"
        buf = io.BytesIO()
        self.prs.save(buf)
        return animate(buf.getvalue())


def render_pptx(content: ReportContent, facts: dict[str, Any]) -> bytes:
    return Deck(content, facts).build()
