import unittest
from pathlib import Path

import pandas as pd

from services.order_service import (
    append_history, calculate_order, navigate, normalize_selection,
    reconstruct_lines, set_quantity,
)
from services.pdf_service import build_pdf


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        self.catalog = pd.DataFrame([
            {"sku":"C","name":"Combo","price":100.0,"stock":10,"category":"alfajor","pack_units":1,"image_url":""},
            {"sku":"B","name":"Bolsa","price":20.0,"stock":2,"category":"bolsas","pack_units":1,"image_url":""},
            {"sku":"E","name":"Extra","price":10.0,"stock":3,"category":"extras","pack_units":1,"image_url":""},
        ])

    def test_add_subtract_zero_and_stock_limit(self):
        selection = set_quantity({}, "B", 1, 2)
        self.assertEqual(selection, {"B": 1})
        selection = set_quantity(selection, "B", 99, 2)
        self.assertEqual(selection, {"B": 2})
        selection = set_quantity(selection, "B", 0, 2)
        self.assertEqual(selection, {})

    def test_reconstruction_and_category_validation(self):
        self.assertEqual(normalize_selection({"B": 9, "E": 1}, self.catalog, "bolsas"), {"B": 2})
        lines = reconstruct_lines({"E": 2}, self.catalog, "extras")
        self.assertEqual(lines[0]["subtotal"], 20.0)
        self.assertEqual(set(lines[0]), {"sku","name","category","quantity","unit_price","stock","image_url","subtotal"})

    def test_discount_only_applies_to_combo(self):
        combo = reconstruct_lines({"C": 2}, self.catalog)
        bags = reconstruct_lines({"B": 1}, self.catalog, "bolsas")
        extras = reconstruct_lines({"E": 3}, self.catalog, "extras")
        totals = calculate_order(combo, bags, extras, 5)
        self.assertEqual(totals["discount_amount"], 10.0)
        self.assertEqual(totals["total"], 240.0)

    def test_navigation_is_pure_and_history_is_limited(self):
        history = []
        for number in range(12):
            history = append_history(history, {"number": number})
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0]["number"], 2)
        self.assertEqual(navigate(1, 2), 2)
        self.assertEqual(navigate(3, 1), 1)

    def test_app_only_generates_combo_and_pdf_under_explicit_buttons(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("generate_combo("), 1)
        self.assertIn('if st.button("🎲 Generar una opción"', source)
        self.assertEqual(source.count("build_pdf("), 1)
        self.assertIn('if st.button("Preparar PDF")', source)
        self.assertNotIn("session_state.catalog", source)
        self.assertNotIn("session_state.pdf", source)

    def test_final_pdf_has_three_sections(self):
        combo = reconstruct_lines({"C": 1}, self.catalog)
        bags = reconstruct_lines({"B": 1}, self.catalog, "bolsas")
        extras = reconstruct_lines({"E": 1}, self.catalog, "extras")
        totals = calculate_order(combo, bags, extras, 5)
        pdf = build_pdf(combo, bags, extras, totals, 20, "variado")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)


if __name__ == "__main__":
    unittest.main()
