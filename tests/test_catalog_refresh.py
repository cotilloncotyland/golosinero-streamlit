import unittest

import pandas as pd

from services.catalog import LastValidStore, build_reduced_catalog, metadata_version, needs_refresh, optional_products, recover_source


class CatalogRefreshTests(unittest.TestCase):
    def setUp(self):
        self.products = pd.DataFrame([
            {"sku": "A", "name": "Bolsa", "price": 100.0, "stock": 2},
            {"sku": "B", "name": "Extra", "price": 50.0, "stock": 0},
            {"sku": "NO", "name": "Sin regla", "price": 1.0, "stock": 9},
        ])
        self.rules = pd.DataFrame([
            {"sku": "A", "category": "bolsas", "pack_units": 1},
            {"sku": "B", "category": "extras", "pack_units": 1},
        ])

    def test_metadata_version_precedence_and_stability(self):
        metadata = {"modifiedTime": "v1", "md5Checksum": "hash", "size": "10"}
        self.assertEqual(metadata_version(metadata), "modifiedTime:v1")
        self.assertEqual(metadata_version(metadata), metadata_version(dict(metadata)))
        changed = dict(metadata, modifiedTime="v2")
        self.assertNotEqual(metadata_version(metadata), metadata_version(changed))
        cached = ("parsed-data", metadata_version(metadata))
        self.assertFalse(needs_refresh(cached, metadata_version(metadata)))
        self.assertTrue(needs_refresh(cached, metadata_version(changed)))
        public_metadata = {"Last-Modified": "Mon, 13 Jul 2026 22:00:16 GMT", "Content-Length": "10"}
        self.assertEqual(metadata_version(public_metadata), "Last-Modified:Mon, 13 Jul 2026 22:00:16 GMT")

    def test_last_valid_store_keeps_sources_isolated(self):
        store = LastValidStore()
        store.set("stock", ("stock-v1", "v1"))
        store.set("rules", ("rules-v1", "v1"))
        store.set("images", ("images-v1", "v1"))
        store.set("rules", ("rules-v2", "v2"))
        self.assertEqual(store.get("stock"), ("stock-v1", "v1"))
        self.assertEqual(store.get("rules"), ("rules-v2", "v2"))
        self.assertEqual(store.get("images"), ("images-v1", "v1"))

    def test_last_valid_is_used_before_fallback(self):
        store = LastValidStore()
        fallback_calls = []
        store.set("rules", ("cached-rules", "v1"))
        value, version, source = recover_source(store, "rules", lambda: fallback_calls.append(1))
        self.assertEqual((value, version, source), ("cached-rules", "v1", "última caché válida"))
        self.assertEqual(fallback_calls, [])
        value, version, source = recover_source(store, "stock", lambda: "local-stock")
        self.assertEqual((value, version, source), ("local-stock", "fallback", "fallback local"))

    def test_reduced_catalog_crosses_sku_and_keeps_zero_stock(self):
        catalog = build_reduced_catalog(self.products, self.rules, {"A": "https://image/A"})
        self.assertEqual(set(catalog.sku), {"A", "B"})
        self.assertEqual(catalog.loc[catalog.sku == "A", "image_url"].iloc[0], "https://image/A")
        self.assertEqual(int(catalog.loc[catalog.sku == "B", "stock"].iloc[0]), 0)

    def test_optional_products_excludes_zero_stock(self):
        catalog = build_reduced_catalog(self.products, self.rules, {})
        self.assertEqual(list(optional_products(catalog, "bolsas").sku), ["A"])
        self.assertTrue(optional_products(catalog, "extras").empty)


if __name__ == "__main__":
    unittest.main()
