"""
backend/pdf_renderer.py
Brightuity — Decision Evidence Package PDF Renderer.

Pure deterministic renderer: reads an already-assembled, already-sealed
evidence package dict and produces a formatted PDF.

Zero network calls. Zero decision authority. Zero PII expansion.
Prints ONE warning line if Montserrat fonts are absent from
backend/assets/fonts/; falls back to Helvetica.

Public API:
    render_evidence_package(package: dict) -> bytes
    write_evidence_package_pdf(package: dict, path: str) -> str

Page order (Brightuity Evidence Package Spec §3):
    1. Cover / Authorization Summary
    2. Executive Briefing
    3. Agent Evidence (one block per agent_evidence entry)
    4. Governance Gate Record
    5. Decision Lineage — chain of custody
    6. Cryptographic Seal (ECDSA SECP256K1)
    7. Human Authorization (signed record or blank pending placeholder)
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable


# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4            # 595.27 × 841.89 pt
MARGIN_L = MARGIN_R = 0.85 * inch
MARGIN_T = 1.10 * inch
MARGIN_B = 0.85 * inch
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R   # ≈ 472.9 pt


# ── Brand colour palette ──────────────────────────────────────────────────────

NAVY       = colors.HexColor("#0A1A2F")
GOLD       = colors.HexColor("#E8A93D")
PASS_GREEN = colors.HexColor("#1B7F4B")
FAIL_RED   = colors.HexColor("#B3261E")
DARK_AMBER = colors.HexColor("#7A5C00")   # background for PENDING block
LIGHT_GRAY = colors.HexColor("#F4F4F6")
MID_GRAY   = colors.HexColor("#888888")
DARK_GRAY  = colors.HexColor("#333333")


# ── Font selection — Montserrat if present, otherwise Helvetica ───────────────

_BASE: str = "Helvetica"
_BOLD: str = "Helvetica-Bold"
_MONO: str = "Courier"

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"


def _init_fonts() -> None:
    """
    Attempt to register Montserrat from backend/assets/fonts/.
    Falls back to Helvetica and prints ONE warning line when fonts are absent.
    Never raises; never downloads anything.
    """
    global _BASE, _BOLD
    reg  = _FONT_DIR / "Montserrat-Regular.ttf"
    bold = _FONT_DIR / "Montserrat-Bold.ttf"
    if reg.exists() and bold.exists():
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont("Montserrat",      str(reg)))
            pdfmetrics.registerFont(TTFont("Montserrat-Bold", str(bold)))
            _BASE = "Montserrat"
            _BOLD = "Montserrat-Bold"
        except Exception as exc:
            print(f"WARNING [pdf_renderer]: font registration failed ({exc}) — using Helvetica.")
    else:
        print(
            f"WARNING [pdf_renderer]: Montserrat TTFs not found in {_FONT_DIR} "
            "— using Helvetica fallback."
        )


_init_fonts()


# ── XML/HTML escaping for dynamic content in Paragraph markup ─────────────────

def _esc(value: Any) -> str:
    """
    Return a safe string for embedding in ReportLab Paragraph XML markup.
    None → em-dash.  Special chars (&, <, >) are escaped.
    """
    if value is None:
        return "—"
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ── Paragraph style factory ───────────────────────────────────────────────────

_Styles = dict[str, ParagraphStyle]


def _ps(name: str, **kw: Any) -> ParagraphStyle:
    return ParagraphStyle(name=name, **kw)


def _build_styles() -> _Styles:
    """
    Build and return all paragraph styles used by the renderer.
    Each call creates fresh instances; names are prefixed "evp_" to avoid
    collisions with any other stylesheet registered in the same process.
    """
    return {
        # ── Running text
        "body": _ps(
            "evp_body", fontName=_BASE, fontSize=10, leading=14,
            textColor=DARK_GRAY,
        ),
        "body_small": _ps(
            "evp_body_small", fontName=_BASE, fontSize=9, leading=12,
            textColor=DARK_GRAY,
        ),
        "body_indent": _ps(
            "evp_body_indent", fontName=_BASE, fontSize=9, leading=13,
            textColor=DARK_GRAY, leftIndent=14,
        ),
        "bullet": _ps(
            "evp_bullet", fontName=_BASE, fontSize=9, leading=13,
            textColor=DARK_GRAY, leftIndent=18, firstLineIndent=-10,
        ),
        # ── Labels and headings
        "label": _ps(
            "evp_label", fontName=_BOLD, fontSize=9, leading=12,
            textColor=NAVY,
        ),
        "section_title": _ps(
            "evp_section_title", fontName=_BOLD, fontSize=13, leading=18,
            textColor=colors.white,
        ),
        "sub_header": _ps(
            "evp_sub_header", fontName=_BOLD, fontSize=11, leading=15,
            textColor=NAVY,
        ),
        "headline": _ps(
            "evp_headline", fontName=_BOLD, fontSize=12, leading=17,
            textColor=NAVY,
        ),
        # ── Cover page specific
        "cover_institution": _ps(
            "evp_cover_institution", fontName=_BOLD, fontSize=16, leading=22,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        "cover_division": _ps(
            "evp_cover_division", fontName=_BASE, fontSize=11, leading=16,
            textColor=GOLD, alignment=TA_CENTER,
        ),
        "cover_classification": _ps(
            "evp_cover_cls", fontName=_BOLD, fontSize=11, leading=16,
            textColor=NAVY, alignment=TA_CENTER,
        ),
        "cover_meta": _ps(
            "evp_cover_meta", fontName=_MONO, fontSize=9, leading=13,
            textColor=MID_GRAY, alignment=TA_CENTER,
        ),
        # ── Decision status block
        "decision_text": _ps(
            "evp_decision_text", fontName=_BOLD, fontSize=22, leading=28,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        "decision_sub": _ps(
            "evp_decision_sub", fontName=_BASE, fontSize=10, leading=14,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        # ── Agent cards
        "agent_name": _ps(
            "evp_agent_name", fontName=_BOLD, fontSize=12, leading=16,
            textColor=NAVY,
        ),
        "agent_role": _ps(
            "evp_agent_role", fontName=_BASE, fontSize=10, leading=14,
            textColor=MID_GRAY,
        ),
        # ── Generic white-on-colour badge text
        "badge_white": _ps(
            "evp_badge_white", fontName=_BOLD, fontSize=10, leading=14,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        # ── Monospace (cryptographic fields)
        "mono": _ps(
            "evp_mono", fontName=_MONO, fontSize=8, leading=11,
            textColor=DARK_GRAY,
        ),
        # ── Lineage table
        "table_header": _ps(
            "evp_table_header", fontName=_BOLD, fontSize=9, leading=12,
            textColor=colors.white,
        ),
        "table_cell": _ps(
            "evp_table_cell", fontName=_BASE, fontSize=8, leading=11,
            textColor=DARK_GRAY,
        ),
        # ── Human auth
        "pending_header": _ps(
            "evp_pending_header", fontName=_BOLD, fontSize=14, leading=19,
            textColor=NAVY, alignment=TA_CENTER,
        ),
        "sig_label": _ps(
            "evp_sig_label", fontName=_BASE, fontSize=9, leading=13,
            textColor=MID_GRAY,
        ),
    }


# ── Page template ─────────────────────────────────────────────────────────────

def _make_doc(
    buf: io.BytesIO,
    pkg_id: str,
    classification: str,
) -> BaseDocTemplate:
    """
    Build a BaseDocTemplate with a footer drawn on every page.
    Footer: package_id + classification on the left, page number on the right.
    """
    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(0.4)
        y_line = MARGIN_B - 10
        canvas.line(MARGIN_L, y_line, PAGE_W - MARGIN_R, y_line)
        canvas.setFont(_BASE, 7)
        canvas.setFillColor(MID_GRAY)
        y_text = MARGIN_B - 22
        canvas.drawString(
            MARGIN_L, y_text,
            f"{pkg_id}  │  {classification}",
        )
        canvas.drawRightString(
            PAGE_W - MARGIN_R, y_text,
            f"Page {doc.page}",
        )
        canvas.restoreState()

    frame = Frame(
        MARGIN_L, MARGIN_B, CONTENT_W,
        PAGE_H - MARGIN_T - MARGIN_B,
        id="normal",
        leftPadding=0, rightPadding=0,
        topPadding=0,  bottomPadding=0,
    )
    template = PageTemplate(id="main", frames=[frame], onPage=_on_page)
    return BaseDocTemplate(
        buf,
        pagesize=A4,
        pageTemplates=[template],
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title=f"Decision Evidence Package — {pkg_id}",
        author="Brightuity Intelligence Platform",
    )


# ── Reusable flowable helpers ─────────────────────────────────────────────────

def _section_header(text: str, st: _Styles) -> list:
    """Full-width navy banner with bold white title text."""
    tbl = Table(
        [[Paragraph(f"<b>{_esc(text)}</b>", st["section_title"])]],
        colWidths=[CONTENT_W],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    return [Spacer(1, 6), tbl, Spacer(1, 8)]


def _kv_table(
    pairs: list[tuple[str, Any]],
    st: _Styles,
    col_ratio: float = 0.30,
) -> Table:
    """
    Two-column key-value table with alternating light-gray rows.
    Keys are bold navy; values are normal dark-gray text that wraps.
    """
    w_key = CONTENT_W * col_ratio
    w_val = CONTENT_W * (1.0 - col_ratio)
    rows = [
        [
            Paragraph(_esc(k), st["label"]),
            Paragraph(_esc(v), st["body"]),
        ]
        for k, v in pairs
    ]
    style_cmds: list = [
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.3, LIGHT_GRAY),
    ]
    for i in range(0, len(rows), 2):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))
    tbl = Table(rows, colWidths=[w_key, w_val])
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _colored_badge(label: str, bg: Any, st: _Styles) -> Table:
    """Single-cell colored badge with white bold text, used for verdict and status."""
    tbl = Table(
        [[Paragraph(f"<b>{_esc(label)}</b>", st["badge_white"])]],
        colWidths=[1.15 * inch],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), bg),
        ("ALIGN",         (0, 0), (0, 0), "CENTER"),
        ("VALIGN",        (0, 0), (0, 0), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (0, 0), 5),
        ("BOTTOMPADDING", (0, 0), (0, 0), 5),
        ("LEFTPADDING",   (0, 0), (0, 0), 8),
        ("RIGHTPADDING",  (0, 0), (0, 0), 8),
    ]))
    return tbl


def _verdict_badge(verdict: str, st: _Styles) -> Table:
    v = (verdict or "").lower()
    if v == "pass":
        bg = PASS_GREEN
    elif v in ("fail", "halt"):
        bg = FAIL_RED
    else:
        bg = colors.HexColor("#666666")
    return _colored_badge((verdict or "UNKNOWN").upper(), bg, st)


def _bullet_list(items: list, st: _Styles) -> list:
    """Render a list of strings as bullet paragraphs. Returns empty-note on empty list."""
    if not items:
        return [Paragraph("<i>None.</i>", st["body_small"])]
    return [Paragraph(f"• {_esc(item)}", st["bullet"]) for item in items]


def _mono_block(text: str | None, st: _Styles) -> Paragraph:
    """
    Monospace paragraph for hashes, signatures, and public keys.
    Splits at 64-character boundaries so long hex strings wrap cleanly.
    """
    if not text:
        return Paragraph("—", st["mono"])
    chunk = 64
    lines = [text[i : i + chunk] for i in range(0, len(text), chunk)]
    xml = "<br/>".join(_esc(line) for line in lines)
    return Paragraph(xml, st["mono"])


def _full_width_banner(lines: list[tuple[str, ParagraphStyle]], bg: Any) -> Table:
    """Full-width table used for institution header, classification, decision blocks."""
    rows = [[Paragraph(text, style)] for text, style in lines]
    tbl = Table(rows, colWidths=[CONTENT_W])
    style_cmds: list = [
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
    ]
    for i, _ in enumerate(rows):
        tp = 18 if i == 0 else 4
        bp = 18 if i == len(rows) - 1 else 4
        style_cmds += [
            ("TOPPADDING",    (0, i), (0, i), tp),
            ("BOTTOMPADDING", (0, i), (0, i), bp),
        ]
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── Section 1: Cover / Authorization Summary ──────────────────────────────────

def _section_cover(pkg: dict, st: _Styles) -> list:
    meta    = pkg.get("package_metadata") or {}
    summary = pkg.get("case_summary")     or {}
    expl    = pkg.get("explainability")   or {}
    human   = pkg.get("human_authorization")

    # Metadata
    institution    = meta.get("institution", "Meridian Digital Bank")
    classification = meta.get("classification", "Confidential — Internal Decision Record")
    package_id     = meta.get("package_id",   "EVP-UNKNOWN")
    generated_at   = meta.get("generated_at", "")
    schema_version = meta.get("schema_version", "")

    # Split institution into name + division if separator present
    parts     = institution.split(" — ", 1)
    inst_name = parts[0].strip()
    division  = parts[1].strip() if len(parts) > 1 else "Digital Assets &amp; Tokenization Division"
    # Sanitise the division string for XML (re-escape after manual split)
    division_xml = division.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Case summary fields
    request_id   = summary.get("request_id",  "")
    asset_type   = summary.get("asset_type")  or "—"
    asset_detail = summary.get("asset_detail") or "—"
    raw_value    = summary.get("asset_value_eur")
    asset_value  = f"€{raw_value:,.2f}" if isinstance(raw_value, (int, float)) else "—"
    jurisdiction   = summary.get("jurisdiction")    or "—"
    pipeline_status = summary.get("pipeline_status", "")
    final_decision  = summary.get("final_decision")
    headline        = expl.get("headline", "")

    # Decision state
    if human and final_decision:
        decision_label = final_decision.upper()
        decision_sub   = "Signed authorization on record"
        decision_bg    = PASS_GREEN if final_decision.lower() == "approved" else FAIL_RED
    elif pipeline_status in ("halted_kyc", "blocked_gate"):
        decision_label = "BLOCKED"
        decision_sub   = f"Pipeline status: {pipeline_status.replace('_', ' ').title()}"
        decision_bg    = FAIL_RED
    else:
        decision_label = "PENDING AUTHORIZATION"
        decision_sub   = "Awaiting Head of Digital Assets signature"
        decision_bg    = DARK_AMBER

    elements: list = []

    # Institution header band
    elements.append(_full_width_banner([
        (_esc(inst_name), st["cover_institution"]),
        (division_xml,    st["cover_division"]),
    ], NAVY))
    elements.append(Spacer(1, 4))

    # Classification banner
    elements.append(_full_width_banner([
        (_esc(classification), st["cover_classification"]),
    ], GOLD))
    elements.append(Spacer(1, 16))

    # Package identity
    elements.append(Paragraph(_esc(package_id), st["cover_meta"]))
    elements.append(Paragraph(
        f"Generated: {_esc(generated_at)} | Schema: {_esc(schema_version)}",
        st["cover_meta"],
    ))
    elements.append(Spacer(1, 16))

    # Case summary
    elements += _section_header("Case Summary", st)
    elements.append(_kv_table([
        ("Request ID",        request_id),
        ("Asset Type",        asset_type),
        ("Asset Detail",      asset_detail),
        ("Asset Value (EUR)", asset_value),
        ("Jurisdiction",      jurisdiction),
        ("Pipeline Status",   pipeline_status.replace("_", " ").title() if pipeline_status else "—"),
    ], st))
    elements.append(Spacer(1, 10))

    # AI briefing headline (if present)
    if headline:
        elements.append(Paragraph("<b>AI System Briefing:</b>", st["label"]))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph(_esc(headline), st["headline"]))
        elements.append(Spacer(1, 14))

    # DECISION block
    dec_tbl = Table(
        [
            [Paragraph(f"<b>{_esc(decision_label)}</b>", st["decision_text"])],
            [Paragraph(_esc(decision_sub), st["decision_sub"])],
        ],
        colWidths=[CONTENT_W],
    )
    dec_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), decision_bg),
        ("TOPPADDING",    (0, 0), (0, 0),   20),
        ("BOTTOMPADDING", (0, 0), (0, 0),   6),
        ("TOPPADDING",    (0, 1), (0, 1),   0),
        ("BOTTOMPADDING", (0, 1), (0, 1),   18),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
    ]))
    elements.append(dec_tbl)
    elements.append(PageBreak())
    return elements


# ── Section 2: Executive Briefing ─────────────────────────────────────────────

def _section_executive_briefing(pkg: dict, st: _Styles) -> list:
    expl = pkg.get("explainability") or {}
    headline        = expl.get("headline",        "")
    decisive_factor = expl.get("decisive_factor", "")
    per_agent       = expl.get("per_agent_summary") or []
    recommendation  = expl.get("recommendation",  "")

    elements: list = []
    elements += _section_header("Executive Briefing", st)

    elements.append(_kv_table([
        ("Outcome Headline",  headline or "—"),
        ("Decisive Factor",   decisive_factor or "—"),
    ], st))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>Per-Agent Summary:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements += _bullet_list(per_agent, st)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>Recommendation for Head of Digital Assets:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(_esc(recommendation) or "—", st["body"]))
    elements.append(PageBreak())
    return elements


# ── Section 3: Agent Evidence ─────────────────────────────────────────────────

def _render_evidence_fields(evidence: dict, st: _Styles) -> list:
    """
    Render the evidence dict for one agent defensively.
    Handles any key set: lists → bullet list, dicts → indented k/v, scalars → k/v row.
    """
    if not evidence:
        return [Paragraph("<i>No additional evidence fields.</i>", st["body_small"])]

    items: list = []
    for key, val in evidence.items():
        if val is None:
            continue
        label = key.replace("_", " ").title()
        if isinstance(val, list):
            items.append(Paragraph(f"<b>{_esc(label)}:</b>", st["label"]))
            items += _bullet_list(val, st)
            items.append(Spacer(1, 4))
        elif isinstance(val, dict):
            items.append(Paragraph(f"<b>{_esc(label)}:</b>", st["label"]))
            for dk, dv in val.items():
                if dv is not None:
                    items.append(Paragraph(
                        f" {_esc(dk.replace('_', ' '))}:  {_esc(dv)}",
                        st["body_indent"],
                    ))
            items.append(Spacer(1, 4))
        else:
            items.append(_kv_table([(label, val)], st, col_ratio=0.35))
            items.append(Spacer(1, 2))

    return items or [Paragraph("<i>No evidence values present.</i>", st["body_small"])]


def _section_agent_evidence(pkg: dict, st: _Styles) -> list:
    agent_evidence = pkg.get("agent_evidence") or []

    elements: list = []
    elements += _section_header("Agent Evidence", st)

    if not agent_evidence:
        elements.append(Paragraph(
            "<i>No agent evidence records in this package.</i>", st["body"],
        ))
        elements.append(PageBreak())
        return elements

    for entry in agent_evidence:
        if not isinstance(entry, dict):
            continue

        agent_name   = entry.get("agent_name",   "unknown")
        role         = entry.get("role",         "")
        verdict      = entry.get("verdict",      "")
        summary      = entry.get("summary",      "")
        model_used   = entry.get("model_used",   "—")
        was_fallback = bool(entry.get("was_fallback", False))
        latency_ms   = entry.get("latency_ms")
        evidence     = entry.get("evidence") or {}

        display_name = agent_name.replace("_", " ").title()
        badge        = _verdict_badge(verdict, st)
        name_para    = Paragraph(f"<b>{_esc(display_name)}</b>", st["agent_name"])

        name_badge_row = Table(
            [[name_para, badge]],
            colWidths=[CONTENT_W * 0.74, CONTENT_W * 0.26],
        )
        name_badge_row.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("ALIGN",         (0, 1), (0, 1),   "RIGHT"),
        ]))

        fallback_note = " (fallback model)" if was_fallback else ""
        lat_str = f"{latency_ms:,} ms" if isinstance(latency_ms, int) else "—"

        block: list = [
            Spacer(1, 8),
            name_badge_row,
            Paragraph(_esc(role), st["agent_role"]),
            Spacer(1, 4),
            HRFlowable(width=CONTENT_W, thickness=0.5, color=GOLD),
            Spacer(1, 6),
            Paragraph(_esc(summary), st["body"]),
            Spacer(1, 6),
            _kv_table([
                ("Model",   f"{model_used}{fallback_note}"),
                ("Latency", lat_str),
            ], st, col_ratio=0.20),
        ]

        if evidence:
            block.append(Spacer(1, 8))
            block.append(Paragraph("<b>Detailed Evidence:</b>", st["label"]))
            block.append(Spacer(1, 4))
            block.extend(_render_evidence_fields(evidence, st))

        block.append(Spacer(1, 10))
        block.append(HRFlowable(width=CONTENT_W, thickness=0.3, color=LIGHT_GRAY))

        elements.append(KeepTogether(block))

    elements.append(PageBreak())
    return elements


# ── Section 4: Governance Gate Record ─────────────────────────────────────────

def _section_governance_gate(pkg: dict, st: _Styles) -> list:
    gate = pkg.get("governance_gate") or {}
    gate_outcome   = gate.get("gate_outcome",   "unknown")
    gate_reason    = gate.get("gate_reason",    "")
    mandatory      = gate.get("mandatory_gates") or []
    advisory_notes = gate.get("advisory_notes")  or []

    v = (gate_outcome or "").lower()
    if v == "pass":
        badge_bg = PASS_GREEN
    elif v in ("halt", "blocked"):
        badge_bg = FAIL_RED
    else:
        badge_bg = colors.HexColor("#666666")

    elements: list = []
    elements += _section_header("Governance Gate Record", st)
    elements.append(_colored_badge(
        f"Gate Outcome: {gate_outcome.upper()}", badge_bg, st,
    ))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("<b>Gate Reason:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(_esc(gate_reason) or "—", st["body"]))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("<b>Mandatory Gates:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements += _bullet_list(
        [g.replace("_", " ").title() for g in mandatory], st,
    )

    if advisory_notes:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>Advisory Notes:</b>", st["sub_header"]))
        elements.append(Spacer(1, 4))
        elements += _bullet_list(advisory_notes, st)

    elements.append(PageBreak())
    return elements


# ── Section 5: Decision Lineage ───────────────────────────────────────────────

def _section_decision_lineage(pkg: dict, st: _Styles) -> list:
    lineage = pkg.get("decision_lineage") or []

    elements: list = []
    elements += _section_header("Decision Lineage — Chain of Custody", st)

    if not lineage:
        elements.append(Paragraph("<i>No lineage records in this package.</i>", st["body"]))
        elements.append(PageBreak())
        return elements

    # Column widths that sum to CONTENT_W
    raw_widths = [0.40, 1.60, 1.30, 1.75, 0.65, 0.75]
    total_raw  = sum(raw_widths)
    col_widths = [w * CONTENT_W / total_raw for w in raw_widths]

    def _th(text: str) -> Paragraph:
        return Paragraph(f"<b>{text}</b>", st["table_header"])

    def _tc(value: Any) -> Paragraph:
        return Paragraph(_esc(value), st["table_cell"])

    header_row = [
        _th("Step"), _th("Event"), _th("Agent"),
        _th("Model"), _th("Fallback?"), _th("Latency"),
    ]
    rows: list = [header_row]

    for entry in lineage:
        if not isinstance(entry, dict):
            continue
        step    = entry.get("step")
        event   = (entry.get("event") or "").replace("_", " ")
        agent   = (entry.get("agent") or "—").replace("_", " ")
        model   = entry.get("model_used") or "—"
        fb_raw  = entry.get("was_fallback")
        fallback = "Yes" if fb_raw is True else ("—" if fb_raw is None else "No")
        lat     = entry.get("latency_ms")
        lat_str = f"{lat:,}" if isinstance(lat, int) else "—"
        rows.append([_tc(step), _tc(event), _tc(agent), _tc(model), _tc(fallback), _tc(lat_str)])

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds: list = [
        ("BACKGROUND",    (0, 0), (-1, 0),  NAVY),
        ("FONTNAME",      (0, 0), (-1, 0),  _BOLD),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
    ]
    for i in range(2, len(rows), 2):  # alternate from row 2 (skip header)
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))
    tbl.setStyle(TableStyle(style_cmds))

    elements.append(tbl)
    elements.append(PageBreak())
    return elements


# ── Section 6: Cryptographic Seal ─────────────────────────────────────────────

def _section_crypto_seal(pkg: dict, st: _Styles) -> list:
    seal = pkg.get("consensus_seal") or {}
    status         = seal.get("status",         "unknown")
    canonical_hash = seal.get("canonical_hash")
    signature      = seal.get("signature")
    public_key     = seal.get("public_key")
    curve          = seal.get("curve")
    sealed_at      = seal.get("sealed_at")
    gates_cleared  = seal.get("gates_cleared")  or []
    failed_gate    = seal.get("failed_gate")

    is_sealed = (status == "sealed")
    badge_bg  = PASS_GREEN if is_sealed else FAIL_RED
    status_label = "SEALED" if is_sealed else "BLOCKED"

    elements: list = []
    elements += _section_header("Cryptographic Seal — ECDSA SECP256K1", st)
    elements.append(_colored_badge(f"Seal Status: {status_label}", badge_bg, st))
    elements.append(Spacer(1, 10))

    if is_sealed:
        elements.append(_kv_table([
            ("Algorithm",      "ECDSA — SHA-256 — RFC 6979 deterministic k"),
            ("Curve",          curve or "—"),
            ("Sealed At",      sealed_at or "—"),
            ("Gates Cleared",  ", ".join(g.replace("_", " ").title() for g in gates_cleared) if gates_cleared else "—"),
        ], st))
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("<b>Canonical Hash (SHA-256):</b>", st["label"]))
        elements.append(Spacer(1, 3))
        elements.append(_mono_block(canonical_hash, st))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph("<b>ECDSA Signature (DER hex):</b>", st["label"]))
        elements.append(Spacer(1, 3))
        elements.append(_mono_block(signature, st))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph("<b>Public Key (compressed hex):</b>", st["label"]))
        elements.append(Spacer(1, 3))
        elements.append(_mono_block(public_key, st))
        elements.append(Spacer(1, 14))

        # Integrity notice
        notice_tbl = Table(
            [[Paragraph(
                "Any alteration to this package breaks this signature. "
                "This is the sealed record as produced at decision time. "
                "The ECDSA signing key is ephemeral per container instance; "
                "this document preserves the seal, not a live verification oracle.",
                st["body_small"],
            )]],
            colWidths=[CONTENT_W],
        )
        notice_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GRAY),
            ("BOX",           (0, 0), (-1, -1), 0.5, GOLD),
            ("TOPPADDING",    (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ]))
        elements.append(notice_tbl)

    else:
        elements.append(Paragraph(
            "Analysis gate not cleared — package not sealed.", st["body"],
        ))
        if failed_gate:
            elements.append(Spacer(1, 6))
            elements.append(_kv_table([
                ("Failed Gate", failed_gate.replace("_", " ").title()),
            ], st))
        reason = seal.get("reason")
        if reason:
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(f"Reason: {_esc(reason)}", st["body"]))

    elements.append(PageBreak())
    return elements


# ── Section 7: Human Authorization ────────────────────────────────────────────

def _section_human_auth(pkg: dict, st: _Styles) -> list:
    human = pkg.get("human_authorization")

    elements: list = []
    elements += _section_header(
        "Human Authorization — Head of Digital Assets", st,
    )

    if not human:
        # ── Pending state: blank placeholder form ─────────────────────────────
        pending_tbl = Table(
            [[Paragraph("PENDING AUTHORIZATION", st["pending_header"])]],
            colWidths=[CONTENT_W],
        )
        pending_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GRAY),
            ("BOX",           (0, 0), (-1, -1), 1.0, NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 22),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 22),
            ("LEFTPADDING",   (0, 0), (-1, -1), 16),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
        ]))
        elements.append(pending_tbl)
        elements.append(Spacer(1, 16))
        elements.append(Paragraph(
            "This evidence package is complete and sealed. "
            "The Head of Digital Assets must review and sign to authorize the decision.",
            st["body"],
        ))
        elements.append(Spacer(1, 32))

        def _blank_field(field_label: str) -> list:
            elems = [Paragraph(field_label, st["sig_label"])]
            line_tbl = Table(
                [[Paragraph("", st["body"])]],
                colWidths=[CONTENT_W],
                rowHeights=[24],
            )
            line_tbl.setStyle(TableStyle([
                ("LINEBELOW",     (0, 0), (-1, -1), 0.8, NAVY),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            elems.append(line_tbl)
            elems.append(Spacer(1, 14))
            return elems

        for field in (
            "Decision (Approved / Rejected):",
            "Reason / Rationale:",
            "Name:",
            "Role / Title:",
            "Date (YYYY-MM-DD):",
        ):
            elements.extend(_blank_field(field))

        elements.append(Spacer(1, 24))
        elements.append(HRFlowable(width=CONTENT_W, thickness=0.6, color=NAVY))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(
            "Signature: _____________________________________________",
            st["sig_label"],
        ))
        return elements

    # ── Signed state ──────────────────────────────────────────────────────────
    # Read all keys defensively — human_authorization is an untyped dict
    decision         = human.get("decision")        or human.get("verdict")         or "—"
    rationale        = (
        human.get("rationale")
        or human.get("reason")
        or human.get("decision_reason")
        or "—"
    )
    annotations      = human.get("annotations")
    signatory_name   = human.get("signatory_name")  or human.get("decision_by")     or "—"
    signatory_role   = human.get("signatory_role")  or human.get("role")            or "—"
    signed_at        = human.get("signed_at")       or human.get("authorized_at")   or "—"
    auth_hash        = human.get("authorization_hash")      or human.get("esignature_hash") or "—"
    auth_sig         = human.get("authorization_signature") or human.get("signature")       or "—"

    dec_lower = (decision or "").lower()
    dec_bg    = PASS_GREEN if dec_lower == "approved" else FAIL_RED

    dec_block = Table(
        [[Paragraph(f"<b>DECISION: {_esc(decision.upper())}</b>", st["decision_text"])]],
        colWidths=[CONTENT_W],
    )
    dec_block.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), dec_bg),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
    ]))
    elements.append(dec_block)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph("<b>Rationale:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(_esc(rationale), st["body"]))
    elements.append(Spacer(1, 10))

    if annotations:
        elements.append(Paragraph("<b>Annotations:</b>", st["sub_header"]))
        elements.append(Spacer(1, 4))
        if isinstance(annotations, list):
            elements += _bullet_list(annotations, st)
        else:
            elements.append(Paragraph(_esc(annotations), st["body"]))
        elements.append(Spacer(1, 10))

    elements.append(Paragraph("<b>Signatory:</b>", st["sub_header"]))
    elements.append(Spacer(1, 4))
    elements.append(_kv_table([
        ("Name",        signatory_name),
        ("Role",        signatory_role),
        ("Signed At",   signed_at),
    ], st))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>Authorization Seal:</b>", st["sub_header"]))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("<b>Hash:</b>", st["label"]))
    elements.append(_mono_block(auth_hash, st))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("<b>Signature:</b>", st["label"]))
    elements.append(_mono_block(auth_sig, st))

    return elements


# ── Public API ────────────────────────────────────────────────────────────────

def render_evidence_package(package: dict) -> bytes:
    """
    Render a Brightuity Decision Evidence Package dict as a PDF.

    Defensive against missing keys, None seals, absent agent_evidence,
    and missing human_authorization at every level.

    Args:
        package: Dict produced by EvidencePackage.model_dump() or any
                 compatible structure with the same top-level keys.

    Returns:
        Raw PDF bytes.
    """
    buf  = io.BytesIO()
    meta = package.get("package_metadata") or {}
    pkg_id         = meta.get("package_id",      "EVP-UNKNOWN")
    classification = meta.get("classification",  "Confidential — Internal Decision Record")

    doc = _make_doc(buf, pkg_id, classification)
    st  = _build_styles()

    story: list = []
    story += _section_cover(package, st)
    story += _section_executive_briefing(package, st)
    story += _section_agent_evidence(package, st)
    story += _section_governance_gate(package, st)
    story += _section_decision_lineage(package, st)
    story += _section_crypto_seal(package, st)
    story += _section_human_auth(package, st)

    doc.build(story)
    return buf.getvalue()


def write_evidence_package_pdf(package: dict, path: str) -> str:
    """
    Render and write a Decision Evidence Package PDF to disk.

    Creates parent directories if absent.

    Args:
        package: Evidence package dict.
        path:    Output path (absolute or relative; must include filename).

    Returns:
        Resolved absolute path of the written PDF file.
    """
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_evidence_package(package))
    return str(out)
