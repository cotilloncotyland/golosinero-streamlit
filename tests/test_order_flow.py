import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from services.order_service import (
    active_selection, add_flavor_candidates, append_favorite, append_history, build_combo_config,
    build_whatsapp_message, calculate_order, navigate, normalize_kids, order_snapshot,
    rebalance_flavor, reconstruct_combo_lines, reconstruct_lines, remove_product,
    restore_product, restore_snapshot, round_money, set_free_quantity,
)


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        self.catalog=pd.DataFrame([
            {"sku":"J1","name":"Jugo naranja","price":100.0,"stock":30,"category":"jugos","pack_units":1,"image_url":""},
            {"sku":"J2","name":"Jugo manzana","price":100.0,"stock":30,"category":"jugos","pack_units":1,"image_url":""},
            {"sku":"J3","name":"Jugo multifruta","price":100.0,"stock":30,"category":"jugos","pack_units":1,"image_url":""},
            {"sku":"C1","name":"Caramelos","price":500.0,"stock":10,"category":"caramelos","pack_units":20,"image_url":""},
            {"sku":"R1","name":"Producto obligatorio","price":200.0,"stock":5,"category":"alfajor","pack_units":6,"image_url":""},
            {"sku":"B1","name":"Bolsa","price":20.0,"stock":2,"category":"bolsas","pack_units":1,"image_url":""},
            {"sku":"E1","name":"Extra","price":10.0,"stock":3,"category":"extras","pack_units":1,"image_url":""},
        ])
        items=[
            SimpleNamespace(sku="J1",quantity=14,category="jugos",pack_units=1,editable_flavor=True,flavor_group="jugos:BAGGIO JUNIOR"),
            SimpleNamespace(sku="J2",quantity=13,category="jugos",pack_units=1,editable_flavor=True,flavor_group="jugos:BAGGIO JUNIOR"),
            SimpleNamespace(sku="C1",quantity=1,category="caramelos",pack_units=20,editable_flavor=False,flavor_group=""),
            SimpleNamespace(sku="R1",quantity=5,category="alfajor",pack_units=6,editable_flavor=False,flavor_group=""),
        ]
        self.config=add_flavor_candidates(build_combo_config(items),"jugos:BAGGIO JUNIOR",[{"sku":"J3"}])

    def test_27_guests_always_keep_required_total(self):
        stocks={"J1":30,"J2":30,"J3":30}
        changed,ok=rebalance_flavor(self.config,"J1",20,stocks)
        self.assertTrue(ok)
        group=[x for x in changed["items"].values() if x.get("flavor_group")=="jugos:BAGGIO JUNIOR"]
        self.assertEqual(sum(x["quantity"] for x in group),27)
        changed,ok=rebalance_flavor(changed,"J2",3,stocks)
        self.assertTrue(ok)
        self.assertEqual(sum(x["quantity"] for x in changed["items"].values() if x.get("flavor_group")),27)

    def test_compensation_rejects_impossible_stock(self):
        changed,ok=rebalance_flavor(self.config,"J1",0,{"J1":30,"J2":13,"J3":0})
        self.assertFalse(ok)
        self.assertEqual(active_selection(changed),active_selection(self.config))

    def test_only_one_logical_product_can_be_removed_and_restored(self):
        removed=remove_product(self.config,"jugos:BAGGIO JUNIOR")
        self.assertEqual(removed["removed_product_key"],"jugos:BAGGIO JUNIOR")
        twice=remove_product(removed,"C1")
        self.assertEqual(twice["removed_product_key"],"jugos:BAGGIO JUNIOR")
        self.assertNotIn("J1",active_selection(twice)); self.assertNotIn("J2",active_selection(twice))
        restored=restore_product(twice)
        self.assertIsNone(restored["removed_product_key"])
        other=remove_product(restored,"C1")
        self.assertEqual(other["removed_product_key"],"C1")

    def test_free_quantity_keeps_base_and_caps_at_stock(self):
        increased=set_free_quantity(self.config,"C1",9,10)
        self.assertEqual(increased["items"]["C1"]["quantity"],9)
        capped=set_free_quantity(increased,"C1",99,10)
        self.assertEqual(capped["items"]["C1"]["quantity"],10)
        minimum=set_free_quantity(capped,"C1",0,10)
        self.assertEqual(minimum["items"]["C1"]["quantity"],1)

    def test_required_quantity_is_not_free(self):
        unchanged=set_free_quantity(self.config,"R1",0,5)
        self.assertEqual(unchanged["items"]["R1"]["quantity"],5)

    def test_totals_apply_discount_only_to_active_combo(self):
        config=remove_product(self.config,"C1")
        combo=reconstruct_combo_lines(config,self.catalog)
        bags=reconstruct_lines({"B1":1},self.catalog,"bolsas")
        extras=reconstruct_lines({"E1":3},self.catalog,"extras")
        totals=calculate_order(combo,bags,extras,5)
        self.assertEqual(totals["savings"],totals["combo_subtotal"]*.05)
        self.assertEqual(totals["total"],totals["combo_total"]+20+30)
        self.assertEqual(totals["subtotal_general"],totals["subtotal_combo_original"]+20+30)
        self.assertEqual(totals["total_pedido"],totals["subtotal_general"]-totals["descuento_combo"])
        self.assertEqual(totals["descuento_medio_pago"],round_money(totals["total_pedido"]*.10))
        self.assertEqual(totals["total_efectivo_transferencia"],totals["total_pedido"]-totals["descuento_medio_pago"])

    def test_money_rounding_is_half_up(self):
        self.assertEqual(round_money("10.5"),11); self.assertEqual(round_money("10.49"),10)

    def test_kids_selector_value_is_stable(self):
        self.assertEqual(normalize_kids(20),20); self.assertEqual(normalize_kids(21),21)
        self.assertEqual(normalize_kids(0),1); self.assertEqual(normalize_kids(999),150)

    def test_favorite_snapshot_preserves_distribution_and_removed_item(self):
        changed,_=rebalance_flavor(self.config,"J1",20,{"J1":30,"J2":30,"J3":30})
        changed=remove_product(changed,"R1")
        favorite=deepcopy(changed)
        self.config["items"]["J1"]["quantity"]=1
        self.assertEqual(favorite["items"]["J1"]["quantity"],20)
        self.assertEqual(favorite["removed_product_key"],"R1")

    def test_navigation_requires_combo_and_supports_four_steps(self):
        self.assertEqual(navigate(1,2,False),1)
        self.assertEqual(navigate(1,2,True),2)
        self.assertEqual(navigate(2,3,True),3)
        self.assertEqual(navigate(3,4,True),4)

    def test_history_is_limited_to_ten(self):
        history=[]
        for number in range(12): history=append_history(history,{"number":number,"config":self.config})
        self.assertEqual(len(history),10); self.assertEqual(history[0]["number"],2)

    def test_favorites_avoid_duplicates_and_keep_last_ten(self):
        favorites={}
        for number in range(12):
            entry={"id":str(number),"number":number,"config":self.config}
            favorites=append_favorite(favorites,entry)
        favorites=append_favorite(favorites,{"id":"11","number":11,"config":self.config})
        self.assertEqual(len(favorites),10); self.assertEqual(list(favorites)[0],"2"); self.assertEqual(list(favorites).count("11"),1)

    def test_snapshot_restores_combo_bags_and_extras(self):
        totals=calculate_order(reconstruct_combo_lines(self.config,self.catalog),[],[],5)
        snapshot=order_snapshot("abc",3,27,"variado",self.config,{"B1":2},{"E1":1},totals,"2026-07-14T10:30")
        restored=restore_snapshot(snapshot)
        self.assertEqual(restored["kids"],27); self.assertEqual(restored["bags_selection"],{"B1":2}); self.assertEqual(restored["extras_selection"],{"E1":1})
        restored["combo_config"]["items"]["J1"]["quantity"]=1
        self.assertNotEqual(snapshot["config"]["items"]["J1"]["quantity"],1)

    def test_whatsapp_uses_the_same_totals(self):
        combo=reconstruct_combo_lines(self.config,self.catalog); bags=reconstruct_lines({"B1":1},self.catalog,"bolsas"); extras=reconstruct_lines({"E1":1},self.catalog,"extras")
        totals=calculate_order(combo,bags,extras,5); message=build_whatsapp_message(combo,bags,extras,totals,27,"premium")
        self.assertIn(f"Total del pedido: ${totals['total_pedido']:,}".replace(",","."),message)
        self.assertIn(f"Efectivo o transferencia: ${totals['total_efectivo_transferencia']:,}".replace(",","."),message)

    def test_app_keeps_generation_and_pdfs_under_explicit_controls(self):
        source=Path("app.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("generate_combo("),1)
        self.assertIn('if st.button("GENERAR COMBO"',source)
        self.assertIn('if st.button("Preparar PDF individual"',source)
        self.assertIn('if st.button("Preparar PDF comparativo"',source)
        self.assertIn('if st.session_state.step==1:',source)
        self.assertIn('render_snapshot_detail(favorite,catalog,discount)',source)
        self.assertIn('render_snapshot_detail(entry,catalog,discount)',source)
        self.assertNotIn('"Ver este combo"',source)
        self.assertNotIn('"Quitar de favoritos"',source)
        self.assertNotIn("session_state.pdf",source)
        self.assertNotIn("session_state.catalog",source)


if __name__=="__main__": unittest.main()
