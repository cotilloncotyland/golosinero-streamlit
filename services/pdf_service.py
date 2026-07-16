from __future__ import annotations

from datetime import datetime
from io import BytesIO
import logging
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LOGGER=logging.getLogger(__name__)


def money(value):
    return "$" + f"{value:,.0f}".replace(",", ".")


def _company_lines(company):
    labels = (("Dirección","address"),("WhatsApp","whatsapp_display"),("Web","website"),("Instagram","instagram"),("Correo","email"))
    return [f"<b>{label}:</b> {company.get(key)}" for label,key in labels if company.get(key)]


def _document_header(title, subtitle, styles, logo=None):
    content=Table([[logo or "",Paragraph(title,styles["DocumentTitle"])],["",Paragraph(subtitle,styles["Subtitle"])]],colWidths=[54*mm,116*mm])
    content.setStyle(TableStyle([
        ("SPAN",(0,0),(0,1)),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),("LINEBELOW",(0,1),(-1,1),.6,colors.HexColor("#eadff4")),
    ]))
    return [content,Spacer(1,7)]


def _company_card(company, styles):
    lines=_company_lines(company)
    if not lines:
        return []
    name=str(company.get("name") or "Cotyland")
    card=Table([[Paragraph(name,styles["ContactName"])],[Paragraph("<br/>".join(lines),styles["ContactBody"])],[Paragraph("Envíanos tu pedido por WhatsApp para confirmar disponibilidad.",styles["ContactNote"])]],colWidths=[170*mm],hAlign="LEFT")
    card.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f6f2fb")),("BOX",(0,0),(-1,-1),.6,colors.HexColor("#e2d5ef")),
        ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,0),8),("BOTTOMPADDING",(0,-1),(-1,-1),8),
    ]))
    return [Spacer(1,4),Paragraph("Información comercial",styles["Section"]),card]


def _logo(logo_path, max_width=52*mm, max_height=18*mm):
    if not logo_path:
        return None
    try:
        width, height = PILImage.open(logo_path).size
        scale = min(max_width/width, max_height/height)
        return Image(str(logo_path), width=width*scale, height=height*scale)
    except Exception:
        return None


def _product_image(url,max_width=16*mm,max_height=16*mm):
    if not str(url or "").startswith(("https://","http://")): return None
    try:
        request=Request(str(url),headers={"User-Agent":"Cotyland-PDF/1.0"})
        with urlopen(request,timeout=5) as response: content=response.read(2_500_000)
        source=PILImage.open(BytesIO(content)).convert("RGB"); source.thumbnail((180,180))
        optimized=BytesIO(); source.save(optimized,format="JPEG",quality=72,optimize=True); optimized.seek(0)
        width,height=source.size; scale=min(max_width/width,max_height/height)
        return Image(optimized,width=width*scale,height=height*scale)
    except Exception as exc:
        LOGGER.info("No se pudo incluir una imagen en el PDF: %s",exc); return None


def _table(title, lines, styles, include_images=True):
    if not lines:
        return [CondPageBreak(20*mm),Paragraph(title, styles["Section"]), Paragraph("Sin productos seleccionados", styles["Small"]), Spacer(1, 5)]
    data=([["Foto","Cant.","Producto","Precio unit.","Subtotal"]] if include_images else [["Cant.","Producto","Precio unit.","Subtotal"]])
    for line in lines:
        row=[str(line["quantity"]),Paragraph(str(line["name"]),styles["BodyText"]),money(line["unit_price"]),money(line["subtotal"])]
        if include_images: row.insert(0,_product_image(line.get("image_url")) or Paragraph("",styles["Small"]))
        data.append(row)
    widths=[18*mm,14*mm,83*mm,30*mm,34*mm] if include_images else [15*mm,100*mm,30*mm,34*mm]
    table=Table(data,colWidths=widths,repeatRows=1,splitByRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#f0e8f8")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#352642")),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("LINEBELOW",(0,0),(-1,0),.7,colors.HexColor("#d8c5e8")),
        ("LINEBELOW",(0,1),(-1,-1),.25,colors.HexColor("#eee8f2")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#fcfaff")]),("ALIGN",(-2,1),(-1,-1),"RIGHT"),
        ("FONTSIZE",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,0),6),("BOTTOMPADDING",(0,0),(-1,0),6),
        ("TOPPADDING",(0,1),(-1,-1),6),("BOTTOMPADDING",(0,1),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
    ]))
    return [CondPageBreak(28*mm),Paragraph(title,styles["Section"]),table,Spacer(1,7)]


def _styles():
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocumentTitle",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=20,leading=23,textColor=colors.HexColor("#211a28"),spaceAfter=2))
    styles.add(ParagraphStyle(name="Subtitle",parent=styles["BodyText"],fontSize=9,leading=12,textColor=colors.HexColor("#6d6574")))
    styles.add(ParagraphStyle(name="Section",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=12,leading=15,textColor=colors.HexColor("#6d28d9"),spaceBefore=7,spaceAfter=5))
    styles.add(ParagraphStyle(name="Small",parent=styles["BodyText"],fontSize=8,leading=10,textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="SummaryLabel",parent=styles["BodyText"],fontSize=8.5,leading=11,textColor=colors.HexColor("#625a69")))
    styles.add(ParagraphStyle(name="SummaryValue",parent=styles["BodyText"],fontName="Helvetica-Bold",fontSize=9,leading=11,textColor=colors.HexColor("#2e2733"),alignment=2))
    styles.add(ParagraphStyle(name="TotalLabel",parent=styles["BodyText"],fontName="Helvetica-Bold",fontSize=9,leading=12,textColor=colors.HexColor("#5b2850")))
    styles.add(ParagraphStyle(name="TotalValue",parent=styles["Heading1"],fontName="Helvetica-Bold",fontSize=19,leading=21,textColor=colors.HexColor("#ef1452"),alignment=2))
    styles.add(ParagraphStyle(name="CashLabel",parent=styles["BodyText"],fontName="Helvetica-Bold",fontSize=8.5,leading=11,textColor=colors.HexColor("#1b6749")))
    styles.add(ParagraphStyle(name="CashValue",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=13,leading=15,textColor=colors.HexColor("#137a50"),alignment=2))
    styles.add(ParagraphStyle(name="ContactName",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=12,leading=14,textColor=colors.HexColor("#352642")))
    styles.add(ParagraphStyle(name="ContactBody",parent=styles["BodyText"],fontSize=8.5,leading=12,textColor=colors.HexColor("#514a58")))
    styles.add(ParagraphStyle(name="ContactNote",parent=styles["BodyText"],fontSize=8,leading=10,textColor=colors.HexColor("#756c7d")))
    return styles


def _summary_card(totals, styles, removed_product=""):
    rows=[
        [Paragraph("Combo generado",styles["SummaryLabel"]),Paragraph(money(totals["subtotal_combo_original"]),styles["SummaryValue"])],
        [Paragraph("Bolsitas",styles["SummaryLabel"]),Paragraph(money(totals["subtotal_bolsitas"]),styles["SummaryValue"])],
        [Paragraph("Extras",styles["SummaryLabel"]),Paragraph(money(totals["subtotal_extras"]),styles["SummaryValue"])],
    ]
    if removed_product:
        rows.insert(1,[Paragraph("Producto quitado",styles["SummaryLabel"]),Paragraph(str(removed_product),styles["SummaryValue"])])
    rows.extend([
        [Paragraph("Subtotal general",styles["SummaryLabel"]),Paragraph(money(totals["subtotal_general"]),styles["SummaryValue"])],
        [Paragraph("Ahorro comprando el combo",styles["SummaryLabel"]),Paragraph(f"-{money(totals['descuento_combo'])}",styles["SummaryValue"])],
        [Paragraph("TOTAL DEL PEDIDO",styles["TotalLabel"]),Paragraph(money(totals["total_pedido"]),styles["TotalValue"])],
        [Paragraph("EFECTIVO O TRANSFERENCIA<br/><font size='7'>10% de descuento adicional</font>",styles["CashLabel"]),Paragraph(money(totals["total_efectivo_transferencia"]),styles["CashValue"])],
    ])
    total_row=len(rows)-2; cash_row=len(rows)-1
    card=Table(rows,colWidths=[110*mm,60*mm],hAlign="RIGHT")
    card.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fff6fb")),("BOX",(0,0),(-1,-1),.7,colors.HexColor("#efd6e3")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("LINEABOVE",(0,total_row),(-1,total_row),.7,colors.HexColor("#e7bfd2")),
        ("TOPPADDING",(0,total_row),(-1,total_row),8),("BOTTOMPADDING",(0,total_row),(-1,total_row),7),
        ("BACKGROUND",(0,cash_row),(-1,cash_row),colors.HexColor("#effaf5")),("LINEABOVE",(0,cash_row),(-1,cash_row),.5,colors.HexColor("#c7e9d9")),
        ("TOPPADDING",(0,cash_row),(-1,cash_row),7),("BOTTOMPADDING",(0,cash_row),(-1,cash_row),7),
    ]))
    return card


def _footer(canvas, doc):
    canvas.saveState(); canvas.setStrokeColor(colors.HexColor("#e7dfeb")); canvas.setLineWidth(.4); canvas.line(14*mm,10*mm,A4[0]-14*mm,10*mm)
    canvas.setFont("Helvetica",7); canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(14*mm,6.5*mm,"Diseñado y desarrollado por Cotyland para nuestros clientes ;)")
    canvas.drawRightString(A4[0]-14*mm,6.5*mm,f"Página {doc.page}")
    canvas.restoreState()


def build_pdf(combo, bags, extras, totals, kids, profile, company=None, removed_product="", logo_path=None, now=None):
    company=company or {}; now=now or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=10*mm,bottomMargin=14*mm)
    styles=_styles(); story=[]; logo=_logo(logo_path)
    story.extend(_document_header("Presupuesto de Combo",f"{now.strftime('%d/%m/%Y %H:%M')} · {kids} invitados · Perfil {profile.capitalize()}",styles,logo))
    story.extend(_table("Golosinas del combo",combo,styles)); story.extend(_table("Bolsitas",bags,styles)); story.extend(_table("Extras",extras,styles))
    story.extend([Paragraph("Resumen del pedido",styles["Section"]),_summary_card(totals,styles,removed_product)])
    story.extend(_company_card(company,styles))
    doc.build(story,onFirstPage=_footer,onLaterPages=_footer); out.seek(0); return out.getvalue()


def build_comparison_pdf(entries, company=None, logo_path=None, now=None):
    company=company or {}; now=now or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=10*mm,bottomMargin=14*mm)
    styles=_styles(); story=[]; logo=_logo(logo_path)
    story.extend(_document_header("Comparación de combos",f"Presupuestos guardados · {now.strftime('%d/%m/%Y %H:%M')}",styles,logo))
    for entry in entries[:10]:
        created=str(entry.get("created_at","")).replace("T"," ")
        story.append(Paragraph(f"Combo #{entry['number']} · {created} · {entry['profile'].capitalize()} · {entry['kids']} invitados",styles["Section"]))
        story.extend(_table("Combo generado",entry.get("combo",entry.get("lines",[])),styles,False)); story.extend(_table("Bolsitas",entry.get("bags",[]),styles,False)); story.extend(_table("Extras",entry.get("extras",[]),styles,False))
        totals=entry["totals"]
        story.extend([_summary_card(totals,styles,entry.get("removed_product","")),Spacer(1,8)])
    story.extend(_company_card(company,styles))
    doc.build(story,onFirstPage=_footer,onLaterPages=_footer); out.seek(0); return out.getvalue()
