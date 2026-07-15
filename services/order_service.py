from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable
from zoneinfo import ZoneInfo


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


def round_money(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_kids(value,minimum=1,maximum=150) -> int:
    return max(int(minimum),min(int(maximum),int(value)))


def calculate_order(combo: list[dict], bags: list[dict], extras: list[dict], discount: int, payment_discount: int = 10) -> dict:
    subtotal_combo_original=round_money(sum(Decimal(str(x["subtotal"])) for x in combo))
    subtotal_bolsitas=round_money(sum(Decimal(str(x["subtotal"])) for x in bags))
    subtotal_extras=round_money(sum(Decimal(str(x["subtotal"])) for x in extras))
    discount_percent=max(0,int(discount)); payment_discount_percent=max(0,int(payment_discount))
    descuento_combo=round_money(Decimal(subtotal_combo_original)*Decimal(discount_percent)/Decimal(100))
    subtotal_general=subtotal_combo_original+subtotal_bolsitas+subtotal_extras
    total_pedido=subtotal_general-descuento_combo
    descuento_medio_pago=round_money(Decimal(total_pedido)*Decimal(payment_discount_percent)/Decimal(100))
    total_efectivo_transferencia=total_pedido-descuento_medio_pago
    return {
        "subtotal_combo_original":subtotal_combo_original,"descuento_combo":descuento_combo,
        "subtotal_bolsitas":subtotal_bolsitas,"subtotal_extras":subtotal_extras,
        "subtotal_general":subtotal_general,"total_pedido":total_pedido,
        "descuento_medio_pago":descuento_medio_pago,"total_efectivo_transferencia":total_efectivo_transferencia,
        "discount_percent":discount_percent,"payment_discount_percent":payment_discount_percent,
        # Claves compatibles con la interfaz y PDFs anteriores.
        "combo_subtotal":subtotal_combo_original,"discount_amount":descuento_combo,"savings":descuento_combo,
        "combo_total":subtotal_combo_original-descuento_combo,"bags_subtotal":subtotal_bolsitas,
        "extras_subtotal":subtotal_extras,"total":total_pedido,
    }


def append_history(history: list[dict], entry: dict, limit: int = 10) -> list[dict]:
    return (list(history)+[deepcopy(entry)])[-limit:]


def order_snapshot(combo_id,number,kids,profile,config,bags_selection,extras_selection,totals,created_at=None) -> dict:
    created_at=created_at or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat(timespec="minutes")
    return {"id":str(combo_id),"number":int(number),"created_at":created_at,"kids":int(kids),"profile":str(profile),
            "config":deepcopy(config),"bags_selection":dict(bags_selection),"extras_selection":dict(extras_selection),"totals":dict(totals)}


def append_favorite(favorites: dict,entry: dict,limit: int = 10) -> dict:
    result={str(key):deepcopy(value) for key,value in favorites.items() if str(key)!=str(entry["id"])}
    result[str(entry["id"])]=deepcopy(entry)
    while len(result)>limit: result.pop(next(iter(result)))
    return result


def restore_snapshot(entry: dict) -> dict:
    return {"combo_id":entry["id"],"combo_number":int(entry["number"]),"kids":int(entry["kids"]),"profile":entry["profile"],
            "combo_config":deepcopy(entry["config"]),"bags_selection":dict(entry.get("bags_selection",{})),"extras_selection":dict(entry.get("extras_selection",{}))}


def format_money(value) -> str:
    return "$"+f"{round_money(value):,}".replace(",",".")


def build_whatsapp_message(combo,bags,extras,totals,kids,profile) -> str:
    sections=[f"Hola Cotyland, preparé este pedido para {int(kids)} invitados (perfil {str(profile).capitalize()}):"]
    for title,lines in (("Combo",combo),("Bolsitas",bags),("Extras",extras)):
        sections.append(f"\n{title}:")
        sections.extend(f"- {int(line['quantity'])} x {line['name']} ({format_money(line['subtotal'])})" for line in lines) if lines else sections.append("- Sin productos")
    sections.extend([f"\nTotal del pedido: {format_money(totals['total_pedido'])}",
                     f"Ahorrás {format_money(totals['descuento_combo'])} comprando el combo",
                     f"Efectivo o transferencia: {format_money(totals['total_efectivo_transferencia'])}",
                     "10% de descuento adicional pagando en efectivo o por transferencia"])
    return "\n".join(sections)


def navigate(current: int, target: int, has_combo: bool = True) -> int:
    if target not in {1,2,3,4} or (target > 1 and not has_combo): return current
    return target
