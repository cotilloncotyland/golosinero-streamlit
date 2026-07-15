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
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LOGGER=logging.getLogger(__name__)


def money(value):
    return "$" + f"{value:,.0f}".replace(",", ".")


def _company_lines(company):
    labels = (("WhatsApp","whatsapp_display"),("Web","website"),("Instagram","instagram"),("Dirección","address"),("Correo","email"))
    return [f"<b>{label}:</b> {company.get(key)}" for label,key in labels if company.get(key)]


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
        return [Paragraph(title, styles["Section"]), Paragraph("Sin productos seleccionados", styles["Small"]), Spacer(1, 5)]
    data=([["Foto","Cant.","Producto","Precio unit.","Subtotal"]] if include_images else [["Cant.","Producto","Precio unit.","Subtotal"]])
    for line in lines:
        row=[str(line["quantity"]),Paragraph(str(line["name"]),styles["BodyText"]),money(line["unit_price"]),money(line["subtotal"])]
        if include_images: row.insert(0,_product_image(line.get("image_url")) or Paragraph("",styles["Small"]))
        data.append(row)
    widths=[18*mm,14*mm,83*mm,30*mm,34*mm] if include_images else [15*mm,100*mm,30*mm,34*mm]
    table=Table(data,colWidths=widths,repeatRows=1,splitByRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#6d28d9")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#d8d2e5")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#faf7ff")]),
        ("FONTSIZE",(0,0),(-1,-1),8),("TOPPADDING",(0,1),(-1,-1),5),("BOTTOMPADDING",(0,1),(-1,-1),5),
    ]))
    return [Paragraph(title,styles["Section"]),table,Spacer(1,7)]


def _styles():
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Section",parent=styles["Heading2"],textColor=colors.HexColor("#6d28d9"),spaceBefore=5,spaceAfter=4))
    styles.add(ParagraphStyle(name="Small",parent=styles["BodyText"],fontSize=8,leading=10,textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="Total",parent=styles["Heading1"],fontSize=18,textColor=colors.HexColor("#ef1452"),alignment=2))
    styles.add(ParagraphStyle(name="Cash",parent=styles["BodyText"],fontSize=11,leading=14,textColor=colors.HexColor("#137a50"),spaceAfter=5))
    return styles


def _footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica",7); canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawCentredString(A4[0]/2,7*mm,"Diseñado y desarrollado por Cotyland para nuestros clientes ;)")
    canvas.restoreState()


def build_pdf(combo, bags, extras, totals, kids, profile, company=None, removed_product="", logo_path=None, now=None):
    company=company or {}; now=now or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=10*mm,bottomMargin=14*mm)
    styles=_styles(); story=[]; logo=_logo(logo_path)
    if logo: story.extend([logo,Spacer(1,4)])
    story.append(Paragraph("Presupuesto de Combo",styles["Title"]))
    story.append(Paragraph(f"{now.strftime('%d/%m/%Y %H:%M')} · {kids} invitados · Perfil {profile.capitalize()}",styles["BodyText"]))
    story.append(Spacer(1,7))
    story.extend(_table("Golosinas del combo",combo,styles)); story.extend(_table("Bolsitas",bags,styles)); story.extend(_table("Extras",extras,styles))
    summary=[["Combo generado",money(totals["subtotal_combo_original"])],["Bolsitas",money(totals["subtotal_bolsitas"])],["Extras",money(totals["subtotal_extras"])],["Subtotal general",money(totals["subtotal_general"])],["Ahorro comprando el combo",f"-{money(totals['descuento_combo'])}"]]
    if removed_product: summary.insert(1,["Producto quitado",removed_product])
    summary_table=Table(summary,colWidths=[115*mm,55*mm],hAlign="RIGHT")
    summary_table.setStyle(TableStyle([("ALIGN",(1,0),(1,-1),"RIGHT"),("LINEABOVE",(0,0),(-1,0),.5,colors.HexColor("#999999")),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9)]))
    story.extend([summary_table,Spacer(1,3),Paragraph(f"TOTAL DEL PEDIDO {money(totals['total_pedido'])}",styles["Total"]),Paragraph(f"<b>EFECTIVO O TRANSFERENCIA {money(totals['total_efectivo_transferencia'])}</b><br/><font size='8'>10% de descuento adicional pagando en efectivo o por transferencia</font>",styles["Cash"]),Spacer(1,5)])
    company_lines=_company_lines(company)
    if company_lines:
        story.extend([Paragraph("Información comercial",styles["Section"]),Paragraph("<br/>".join(company_lines),styles["BodyText"]),Spacer(1,4),Paragraph("Envíanos tu pedido por WhatsApp para confirmar disponibilidad.",styles["BodyText"])])
    doc.build(story,onFirstPage=_footer,onLaterPages=_footer); out.seek(0); return out.getvalue()


def build_comparison_pdf(entries, company=None, logo_path=None, now=None):
    company=company or {}; now=now or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=10*mm,bottomMargin=14*mm)
    styles=_styles(); story=[]; logo=_logo(logo_path)
    if logo: story.extend([logo,Spacer(1,4)])
    story.extend([Paragraph("Comparación de combos",styles["Title"]),Paragraph(now.strftime("%d/%m/%Y %H:%M"),styles["Small"]),Spacer(1,6)])
    for entry in entries[:10]:
        created=str(entry.get("created_at","")).replace("T"," ")
        story.append(Paragraph(f"Combo #{entry['number']} · {created} · {entry['profile'].capitalize()} · {entry['kids']} invitados",styles["Section"]))
        story.extend(_table("Combo generado",entry.get("combo",entry.get("lines",[])),styles,False)); story.extend(_table("Bolsitas",entry.get("bags",[]),styles,False)); story.extend(_table("Extras",entry.get("extras",[]),styles,False))
        if entry.get("removed_product"): story.append(Paragraph(f"Producto quitado: {entry['removed_product']}",styles["Small"]))
        totals=entry["totals"]
        story.append(Paragraph(f"Subtotal general {money(totals['subtotal_general'])} · Ahorro comprando el combo {money(totals['descuento_combo'])} · <b>Total del pedido {money(totals['total_pedido'])}</b> · Efectivo/transferencia {money(totals['total_efectivo_transferencia'])}",styles["BodyText"]))
        story.append(Spacer(1,8))
    company_lines=_company_lines(company)
    if company_lines: story.extend([Paragraph("Información comercial",styles["Section"]),Paragraph("<br/>".join(company_lines),styles["BodyText"])])
    doc.build(story,onFirstPage=_footer,onLaterPages=_footer); out.seek(0); return out.getvalue()
