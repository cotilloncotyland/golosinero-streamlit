from __future__ import annotations

from typing import Iterable


def minimal_selection(items: Iterable) -> dict[str, int]:
    return {str(item.sku): int(item.quantity) for item in items if int(item.quantity) > 0}


def normalize_selection(selection: dict[str, int], catalog, category: str | None = None) -> dict[str, int]:
    allowed = catalog
    if category is not None:
        allowed = allowed[allowed["category"] == category]
    stocks = {str(row.sku): int(row.stock) for row in allowed.itertuples()}
    result = {}
    for sku, quantity in selection.items():
        sku = str(sku)
        if sku not in stocks:
            continue
        quantity = max(0, min(int(quantity), stocks[sku]))
        if quantity:
            result[sku] = quantity
    return result


def set_quantity(selection: dict[str, int], sku: str, quantity: int, stock: int) -> dict[str, int]:
    result = dict(selection)
    quantity = max(0, min(int(quantity), int(stock)))
    if quantity:
        result[str(sku)] = quantity
    else:
        result.pop(str(sku), None)
    return result


def reconstruct_lines(selection: dict[str, int], catalog, category: str | None = None) -> list[dict]:
    selection = normalize_selection(selection, catalog, category)
    indexed = catalog.set_index("sku", drop=False)
    lines = []
    for sku, quantity in selection.items():
        row = indexed.loc[sku]
        unit_price = float(row["price"])
        lines.append({
            "sku": sku,
            "name": str(row["name"]),
            "category": str(row["category"]),
            "quantity": quantity,
            "unit_price": unit_price,
            "stock": int(row["stock"]),
            "image_url": str(row.get("image_url", "") or ""),
            "subtotal": quantity * unit_price,
        })
    return lines


def calculate_order(combo: list[dict], bags: list[dict], extras: list[dict], discount: int) -> dict:
    combo_subtotal = sum(float(line["subtotal"]) for line in combo)
    bags_subtotal = sum(float(line["subtotal"]) for line in bags)
    extras_subtotal = sum(float(line["subtotal"]) for line in extras)
    discount_amount = combo_subtotal * max(0, int(discount)) / 100
    return {
        "combo_subtotal": combo_subtotal,
        "discount_percent": int(discount),
        "discount_amount": discount_amount,
        "combo_total": combo_subtotal - discount_amount,
        "bags_subtotal": bags_subtotal,
        "extras_subtotal": extras_subtotal,
        "total": combo_subtotal - discount_amount + bags_subtotal + extras_subtotal,
    }


def append_history(history: list[dict], entry: dict, limit: int = 10) -> list[dict]:
    return (list(history) + [entry])[-limit:]


def navigate(current: int, target: int) -> int:
    return target if target in {1, 2, 3} else current
