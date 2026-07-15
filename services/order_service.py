from __future__ import annotations

from copy import deepcopy
from typing import Iterable


def build_combo_config(items: Iterable) -> dict:
    items = list(items)
    group_totals = {}
    for item in items:
        if item.editable_flavor and item.flavor_group:
            group_totals[item.flavor_group] = group_totals.get(item.flavor_group, 0) + int(item.quantity)
    records = {}
    for item in items:
        mode = "compensated" if item.editable_flavor and item.flavor_group else ("free" if item.category == "caramelos" else "required")
        logical_key = item.flavor_group if mode == "compensated" else str(item.sku)
        records[str(item.sku)] = {
            "sku": str(item.sku), "quantity": int(item.quantity), "base_quantity": int(item.quantity),
            "category": item.category, "pack_units": int(item.pack_units), "mode": mode,
            "flavor_group": item.flavor_group if mode == "compensated" else "",
            "required_total": group_totals.get(item.flavor_group, int(item.quantity)),
            "logical_key": logical_key,
        }
    return {"items": records, "removed_product_key": None}


def add_flavor_candidates(config: dict, flavor_group: str, candidates: list[dict]) -> dict:
    result = deepcopy(config)
    members = [item for item in result["items"].values() if item.get("flavor_group") == flavor_group]
    if not members:
        return result
    template = members[0]
    for candidate in candidates:
        sku = str(candidate["sku"])
        if sku not in result["items"]:
            result["items"][sku] = {
                **template, "sku": sku, "quantity": 0, "base_quantity": 0,
            }
    return result


def active_selection(config: dict) -> dict[str, int]:
    removed = config.get("removed_product_key")
    return {
        sku: int(item["quantity"])
        for sku, item in config.get("items", {}).items()
        if item.get("logical_key") != removed and int(item["quantity"]) > 0
    }


def remove_product(config: dict, logical_key: str) -> dict:
    result = deepcopy(config)
    current = result.get("removed_product_key")
    valid = {item.get("logical_key") for item in result.get("items", {}).values()}
    if current is None and logical_key in valid:
        result["removed_product_key"] = logical_key
    return result


def restore_product(config: dict) -> dict:
    result = deepcopy(config)
    result["removed_product_key"] = None
    return result


def rebalance_flavor(config: dict, sku: str, requested: int, stocks: dict[str, int]) -> tuple[dict, bool]:
    original = deepcopy(config)
    result = deepcopy(config)
    item = result.get("items", {}).get(str(sku))
    if not item or item.get("mode") != "compensated":
        return original, False
    group = item["flavor_group"]
    members = [x for x in result["items"].values() if x.get("flavor_group") == group]
    required = int(item["required_total"])
    requested = max(0, min(int(requested), int(stocks.get(str(sku), 0)), required))
    delta = requested - int(item["quantity"])
    item["quantity"] = requested
    others = [x for x in members if x["sku"] != str(sku)]
    if delta > 0:
        for other in sorted(others, key=lambda x: int(x["quantity"]), reverse=True):
            take = min(delta, int(other["quantity"]))
            other["quantity"] -= take; delta -= take
            if delta == 0: break
    elif delta < 0:
        needed = -delta
        for other in others:
            capacity = max(0, int(stocks.get(other["sku"], 0)) - int(other["quantity"]))
            add = min(needed, capacity)
            other["quantity"] += add; needed -= add
            if needed == 0: break
        delta = -needed
    if sum(int(x["quantity"]) for x in members) != required:
        return original, False
    if any(int(x["quantity"]) > int(stocks.get(x["sku"], 0)) for x in members):
        return original, False
    return result, True


def set_free_quantity(config: dict, sku: str, quantity: int, stock: int) -> dict:
    result = deepcopy(config)
    item = result.get("items", {}).get(str(sku))
    if not item or item.get("mode") != "free":
        return result
    minimum = int(item["base_quantity"])
    item["quantity"] = max(minimum, min(int(quantity), int(stock)))
    return result


def normalize_selection(selection: dict[str, int], catalog, category: str | None = None) -> dict[str, int]:
    allowed = catalog if category is None else catalog[catalog["category"] == category]
    stocks = {str(row.sku): int(row.stock) for row in allowed.itertuples()}
    return {str(sku): max(0, min(int(qty), stocks[str(sku)])) for sku, qty in selection.items() if str(sku) in stocks and int(qty) > 0}


def set_quantity(selection: dict[str, int], sku: str, quantity: int, stock: int) -> dict[str, int]:
    result = dict(selection); quantity = max(0, min(int(quantity), int(stock)))
    if quantity: result[str(sku)] = quantity
    else: result.pop(str(sku), None)
    return result


def reconstruct_lines(selection: dict[str, int], catalog, category: str | None = None) -> list[dict]:
    selection = normalize_selection(selection, catalog, category)
    indexed = catalog.set_index("sku", drop=False); lines = []
    for sku, quantity in selection.items():
        row = indexed.loc[sku]; unit_price = float(row["price"])
        lines.append({"sku":sku,"name":str(row["name"]),"category":str(row["category"]),"quantity":quantity,"unit_price":unit_price,"stock":int(row["stock"]),"image_url":str(row.get("image_url","") or ""),"subtotal":quantity*unit_price})
    return lines


def reconstruct_combo_lines(config: dict, catalog) -> list[dict]:
    lines = reconstruct_lines(active_selection(config), catalog)
    metadata = config.get("items", {})
    for line in lines:
        item = metadata[line["sku"]]
        line.update({"mode":item["mode"],"flavor_group":item.get("flavor_group", ""),"required_total":item.get("required_total"),"logical_key":item["logical_key"]})
    return lines


def calculate_order(combo: list[dict], bags: list[dict], extras: list[dict], discount: int) -> dict:
    combo_subtotal=sum(float(x["subtotal"]) for x in combo); bags_subtotal=sum(float(x["subtotal"]) for x in bags); extras_subtotal=sum(float(x["subtotal"]) for x in extras)
    savings=combo_subtotal*max(0,int(discount))/100
    return {"combo_subtotal":combo_subtotal,"discount_percent":int(discount),"discount_amount":savings,"savings":savings,"combo_total":combo_subtotal-savings,"bags_subtotal":bags_subtotal,"extras_subtotal":extras_subtotal,"total":combo_subtotal-savings+bags_subtotal+extras_subtotal}


def append_history(history: list[dict], entry: dict, limit: int = 10) -> list[dict]:
    return (list(history)+[deepcopy(entry)])[-limit:]


def navigate(current: int, target: int, has_combo: bool = True) -> int:
    if target not in {1,2,3,4} or (target > 1 and not has_combo): return current
    return target
