import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from io import BytesIO

from PIL import Image as PILImage
from pypdf import PdfReader

from services.order_service import calculate_order
from services.pdf_service import _logo, build_comparison_pdf, build_pdf


class PdfServiceTests(unittest.TestCase):
    def setUp(self):
        self.lines=[{"sku":"A","name":"Producto","quantity":2,"unit_price":100.0,"subtotal":200.0,"image_url":"https://example.invalid/product.jpg"}]
        self.totals=calculate_order(self.lines,self.lines,self.lines,5)
        self.company={"name":"Cotyland","address":"Paraná 6552, Villa Adelina","whatsapp_number":"5491125244522","whatsapp_display":"11 2524-4522","website":"www.cotilloncotyland.ar","instagram":"@cotilloncotyland","email":"ventas@example.com"}
        self.logo_path=Path("assets/cotyland_logo.png")

    def test_logo_preserves_aspect_ratio(self):
        source_width,source_height=PILImage.open(self.logo_path).size
        logo=_logo(self.logo_path)
        self.assertAlmostEqual(logo.drawWidth/logo.drawHeight,source_width/source_height,places=3)

    def test_final_pdf_contains_all_sections_and_company_data(self):
        with patch("services.pdf_service._product_image",return_value=_logo(self.logo_path,12,12)) as image_mock:
            pdf=build_pdf(self.lines,self.lines,self.lines,self.totals,27,"premium",self.company,"Grupo jugos",self.logo_path,datetime(2026,7,14,10,30,tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")))
        self.assertTrue(pdf.startswith(b"%PDF")); self.assertGreater(len(pdf),2000)
        self.assertEqual(image_mock.call_count,3)
        text="\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        for value in ("TOTAL DEL PEDIDO","EFECTIVO O TRANSFERENCIA","Correo","ventas@example.com"): self.assertIn(value,text)

    def test_comparison_pdf_is_generated_on_demand(self):
        entry={"number":1,"created_at":"2026-07-14T10:30","profile":"variado","kids":27,"combo":self.lines,"bags":self.lines,"extras":self.lines,"removed_product":"","totals":self.totals}
        with patch("services.pdf_service._product_image") as image_mock: pdf=build_comparison_pdf([entry]*12,self.company,self.logo_path)
        self.assertTrue(pdf.startswith(b"%PDF")); self.assertGreater(len(pdf),1500)
        image_mock.assert_not_called()
        text="\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertEqual(text.count("Combo #"),10); self.assertIn("Información comercial",text)

    def test_company_example_contains_real_configurable_values(self):
        text=Path(".streamlit/secrets.toml.example").read_text(encoding="utf-8")
        for value in ("Paraná 6552, Villa Adelina","5491125244522","11 2524-4522","www.cotilloncotyland.ar","@cotilloncotyland","email"):
            self.assertIn(value,text)


if __name__=="__main__": unittest.main()
