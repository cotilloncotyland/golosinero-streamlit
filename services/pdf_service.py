from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from PIL import Image as PILImage
import requests


def money(v): return "$"+f"{v:,.0f}".replace(",",".")

def fetch_image(url):
    if not url: return None
    try:
        r=requests.get(url.replace("sz=w220","sz=w600"),timeout=10); r.raise_for_status()
        bio=BytesIO(r.content); PILImage.open(bio).verify(); bio.seek(0); return bio
    except Exception: return None


def _section(story, title, lines, styles):
    if not lines:
        return
    story.append(Paragraph(title, styles["Heading2"]))
    data=[["Cant.","Producto","SKU","Unitario","Subtotal"]]
    for line in lines:
        data.append([
            str(line["quantity"]), Paragraph(line["name"],styles["BodyText"]), line["sku"],
            money(line["unit_price"]), money(line["subtotal"]),
        ])
    table=Table(data,colWidths=[14*mm,85*mm,28*mm,28*mm,28*mm],repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#6d28d9")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#d8d2e5")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#faf7ff")]),("FONTSIZE",(0,0),(-1,-1),8)]))
    story.extend([table,Spacer(1,8)])


def build_pdf(combo, bags, extras, totals, kids, profile, logo_path=None):
    out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=12*mm,bottomMargin=14*mm)
    styles=getSampleStyleSheet(); story=[]
    if logo_path:
        try: story.append(Image(str(logo_path),width=42*mm,height=18*mm)); story.append(Spacer(1,4))
        except Exception: pass
    story.append(Paragraph("Combo de golosinas Cotyland",styles["Title"]))
    story.append(Paragraph(f"{kids} invitados · Perfil {profile.capitalize()}",styles["Heading2"]))
    _section(story,"Combo de golosinas",combo,styles)
    _section(story,"Bolsitas",bags,styles)
    _section(story,"Extras",extras,styles)
    story.append(Paragraph(f"Subtotal combo: {money(totals['combo_subtotal'])}",styles["BodyText"]))
    story.append(Paragraph(f"Descuento combo ({totals['discount_percent']}%): -{money(totals['discount_amount'])}",styles["BodyText"]))
    story.append(Paragraph(f"Subtotal bolsas: {money(totals['bags_subtotal'])}",styles["BodyText"]))
    story.append(Paragraph(f"Subtotal extras: {money(totals['extras_subtotal'])}",styles["BodyText"]))
    story.append(Paragraph(f"<b>Total final: {money(totals['total'])}</b>",styles["Heading2"]))
    story.append(Paragraph("Presupuesto sujeto a disponibilidad y actualización de stock. Para confirmar el pedido, descargá este PDF y envialo por WhatsApp a Cotyland.",styles["BodyText"]))
    doc.build(story); out.seek(0); return out.getvalue()
