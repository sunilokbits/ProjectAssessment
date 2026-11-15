"""Post-process a saved .pptx: fade transitions on every slide, entrance builds on shapes named ``a<N>_*``.

Groups a1, a2, ... build in order. Slides with a shape named ``a1_letter`` (the framework slide) build one
group per click; every other slide builds automatically after it appears.
"""
from __future__ import annotations

import io
import re
import zipfile

TRANSITION = '<p:transition spd="med"><p:fade/></p:transition>'
SHAPE_RE = re.compile(r'<p:(sp|pic|cxnSp|graphicFrame)>\s*<p:nv\w+>\s*<p:cNvPr id="(\d+)" name="([^"]*)"')


class _Ids:
    def __init__(self) -> None:
        self.n = 2

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _effect(ids: _Ids, spid: str, node_type: str, delay: int = 0) -> str:
    return (
        f'<p:par><p:cTn id="{ids()}" presetID="10" presetClass="entr" presetSubtype="0" fill="hold" grpId="0" nodeType="{node_type}">'
        f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
        f'<p:set><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
        f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids()}" dur="450"/>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
        f'</p:childTnLst></p:cTn></p:par>'
    )


def _timing(groups: list[list[str]], click: bool, sp_ids: set[str]) -> str:
    ids = _Ids()
    seq = []
    if click:
        for g in groups:
            inner = "".join(_effect(ids, sp, "clickEffect" if k == 0 else "withEffect") for k, sp in enumerate(g))
            a, b = ids(), ids()
            seq.append(f'<p:par><p:cTn id="{a}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
                       f'<p:par><p:cTn id="{b}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                       f'{inner}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>')
    else:
        outer = ids()
        pars = []
        for gi, g in enumerate(groups):
            inner = "".join(_effect(ids, sp, "afterEffect" if k == 0 else "withEffect") for k, sp in enumerate(g))
            pars.append(f'<p:par><p:cTn id="{ids()}" fill="hold"><p:stCondLst><p:cond delay="{gi * 350}"/></p:stCondLst>'
                        f'<p:childTnLst>{inner}</p:childTnLst></p:cTn></p:par>')
        seq.append(f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
                   f'<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>{"".join(pars)}</p:childTnLst></p:cTn></p:par>')
    blds = "".join(f'<p:bldP spid="{sp}" grpId="0" animBg="1"/>' for g in groups for sp in g if sp in sp_ids)
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            + "".join(seq) +
            '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            '</p:childTnLst></p:cTn></p:par></p:tnLst>'
            + (f'<p:bldLst>{blds}</p:bldLst>' if blds else '') + '</p:timing>')


def animate(pptx: bytes) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(pptx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", item.filename):
                xml = data.decode("utf-8")
                if "<p:timing" not in xml and "<p:transition" not in xml:
                    groups: dict[int, list[str]] = {}
                    sp_ids: set[str] = set()
                    for tag, sid, name in SHAPE_RE.findall(xml):
                        m = re.match(r"a(\d+)_", name)
                        if m:
                            groups.setdefault(int(m.group(1)), []).append(sid)
                            if tag == "sp":
                                sp_ids.add(sid)
                    ordered = [groups[k] for k in sorted(groups)]
                    extra = TRANSITION + (_timing(ordered, 'name="a1_letter"' in xml, sp_ids) if ordered else "")
                    xml = xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + extra, 1)
                    data = xml.encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()
