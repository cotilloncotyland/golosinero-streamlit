from __future__ import annotations

from pathlib import Path
import io
import json
import time
import uuid

import streamlit as st

from engine.generator import generate_combo
from services.catalog import (
    LastValidStore, api_download, api_export_xlsx, api_metadata, build_reduced_catalog,
    drive_service, load_json_bytes, load_rules_xlsx, metadata_version, needs_refresh, optional_products,
    parse_csv_bytes, public_drive_download, public_drive_metadata,
    public_google_sheet_export, public_sheet_metadata, recover_source,
)
from services.freshness import freshness_status
from services.order_service import (
    append_history, calculate_order, minimal_selection, navigate, normalize_selection,
    reconstruct_lines, set_quantity,
)
from services.pdf_service import build_pdf, money

ROOT = Path(__file__).parent
st.set_page_config(page_title="Armá tu combo | Cotyland", page_icon="🎉", layout="wide")


@st.cache_resource
def get_drive_service():
    info = st.secrets.get("google_service_account", {})
    return drive_service(info) if info and info.get("client_email") else None


@st.cache_resource
def get_last_valid_store():
    return LastValidStore()


@st.cache_data(ttl=900, max_entries=6, show_spinner=False)
def get_source_metadata(file_id, source_type):
    started = time.perf_counter()
    service = get_drive_service()
    if service:
        metadata = api_metadata(service, file_id)
    elif source_type == "rules":
        metadata = public_sheet_metadata(file_id)
    else:
        metadata = public_drive_metadata(file_id)
    return metadata, time.perf_counter() - started


@st.cache_data(max_entries=4, show_spinner="Actualizando stock y precios...")
def load_stock_version(file_id, version):
    started = time.perf_counter()
    service = get_drive_service()
    content = api_download(service, file_id) if service else public_drive_download(file_id)
    return parse_csv_bytes(content), time.perf_counter() - started


@st.cache_data(max_entries=4, show_spinner="Actualizando reglas...")
def load_rules_version(file_id, version):
    started = time.perf_counter()
    service = get_drive_service()
    content = api_export_xlsx(service, file_id) if service else public_google_sheet_export(file_id)
    rules = load_rules_xlsx(io.BytesIO(content))
    if rules.empty:
        raise ValueError("La planilla no contiene reglas activas")
    return rules, time.perf_counter() - started


@st.cache_data(max_entries=4, show_spinner=False)
def load_images_version(file_id, version):
    started = time.perf_counter()
    service = get_drive_service()
    content = api_download(service, file_id) if service else public_drive_download(file_id)
    data = load_json_bytes(content)
    return (data.get("images", {}), data.get("logoUrl", "")), time.perf_counter() - started


@st.cache_data(max_entries=6, show_spinner=False)
def reduced_catalog(products, rules, images, stock_version, rules_version, images_version):
    started = time.perf_counter()
    return build_reduced_catalog(products, rules, images), time.perf_counter() - started


def resolve_source(key, file_id, source_type, loader, fallback_loader):
    store = get_last_valid_store()
    try:
        metadata, metadata_seconds = get_source_metadata(file_id, source_type)
        version = metadata_version(metadata)
        cached = store.get(key)
        if not needs_refresh(cached, version):
            return cached[0], version, "Google Drive", None, {"metadata": metadata_seconds, "download": 0.0}
        value, download_seconds = loader(file_id, version)
        store.set(key, (value, version))
        store.set(f"{key}_metadata", metadata)
        return value, version, "Google Drive", None, {"metadata": metadata_seconds, "download": download_seconds}
    except Exception as exc:
        value, version, source = recover_source(store, key, fallback_loader)
        return value, version, source, str(exc), {}


def init_state():
    defaults = {
        "step": 1, "kids": 20, "profile": "variado", "combo_id": None,
        "combo_selection": {}, "bags_selection": {}, "extras_selection": {},
        "history": [], "favorites": set(), "combo_number": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def source_status(label, source, count, error):
    message = f"{label}: {source} · {count:,}".replace(",", ".")
    if error:
        st.warning(f"{message}. Detalle: {error}")
    else:
        st.success(message)


def render_optional(category, title, catalog, selection_key):
    st.subheader(title)
    products = optional_products(catalog, category)
    selection = normalize_selection(st.session_state[selection_key], catalog, category)
    if products.empty:
        st.info(f"No hay productos disponibles en {title}.")
    for row in products.itertuples():
        with st.container(border=True):
            image_col, data_col = st.columns([1, 4])
            with image_col:
                if row.image_url:
                    st.image(row.image_url, width=110)
            with data_col:
                st.markdown(f"**{row.name}**")
                st.caption(f"SKU {row.sku} · {money(row.price)} c/u · Stock {row.stock}")
                quantity = st.number_input(
                    "Cantidad", 0, int(row.stock), int(selection.get(row.sku, 0)), 1,
                    key=f"{selection_key}_{row.sku}",
                )
                selection = set_quantity(selection, row.sku, quantity, row.stock)
                st.write(f"Subtotal: **{money(quantity * row.price)}**")
    st.session_state[selection_key] = selection


def render_price_summary(totals):
    st.markdown(
        f"Subtotal combo: **{money(totals['combo_subtotal'])}**  \n"
        f"Descuento ({totals['discount_percent']}%): **-{money(totals['discount_amount'])}**  \n"
        f"Bolsitas: **{money(totals['bags_subtotal'])}**  \n"
        f"Extras: **{money(totals['extras_subtotal'])}**  \n"
        f"### Total final: {money(totals['total'])}"
    )


init_state()
drive_cfg = st.secrets.get("drive", {})
stock_id = drive_cfg.get("stock_file_id", "1D4gde-bbWlPw910hxaVQidpfIULShhS8")
rules_id = drive_cfg.get("rules_file_id", "10kmGyYwpE4f-ujUgAigwDrQ7uS5DQHs_jQYxcFDNDQc")
images_id = drive_cfg.get("images_index_file_id", "1fqSlwCqGvyB2W9W0b-3zZrvxp-KjHI4i")

products, stock_version, stock_source, stock_error, stock_timings = resolve_source(
    "stock", stock_id, "stock", load_stock_version,
    lambda: parse_csv_bytes((ROOT / "data/GOLOSINERO_fallback.csv").read_bytes()),
)
rules, rules_version, rules_source, rules_error, rules_timings = resolve_source(
    "rules", rules_id, "rules", load_rules_version,
    lambda: load_rules_xlsx(ROOT / "data/reglas_combos.xlsx"),
)
(images, logo_url), images_version, images_source, images_error, images_timings = resolve_source(
    "images", images_id, "images", load_images_version,
    lambda: (lambda data: (data.get("images", {}), data.get("logoUrl", "")))(
        json.loads((ROOT / "data/imagenes_index_fallback.json").read_text(encoding="utf-8"))
    ),
)
catalog, catalog_seconds = reduced_catalog(products, rules, images, stock_version, rules_version, images_version)
allowed_products = catalog[["sku", "name", "price", "stock"]]
allowed_rules = rules[rules["sku"].isin(set(catalog["sku"]))]
allowed_images = dict(zip(catalog["sku"], catalog["image_url"]))

discount = int(st.secrets.get("app", {}).get("discount_percent", 5))
fresh_cfg = dict(st.secrets.get("freshness", {})) or {"timezone":"America/Argentina/Buenos_Aires","max_age_minutes_open":120,"max_age_hours_closed":72,"open_weekdays":[0,1,2,3,4,5],"open_ranges":["09:00-13:00","14:30-19:30"]}
stock_metadata = get_last_valid_store().get("stock_metadata") or {}
fresh = freshness_status(stock_metadata.get("modifiedTime"), fresh_cfg) if stock_metadata else {"ok": True, "message": "Catálogo disponible"}

st.title("Armá tu combo de cumpleaños")
source_status("CSV", stock_source, len(products), stock_error)
source_status("Reglas", rules_source, len(rules), rules_error)
source_status("Imágenes", images_source, len(images), images_error)
st.caption(f"Catálogo reducido: {len(catalog)} productos permitidos")
if fresh["ok"]:
    st.info(fresh["message"])
else:
    st.error(fresh["message"])

combo_lines = reconstruct_lines(st.session_state.combo_selection, catalog)
bags_lines = reconstruct_lines(st.session_state.bags_selection, catalog, "bolsas")
extras_lines = reconstruct_lines(st.session_state.extras_selection, catalog, "extras")
totals = calculate_order(combo_lines, bags_lines, extras_lines, discount)

if st.session_state.step == 1:
    st.header("Paso 1 · Combo de golosinas")
    kids = st.number_input("Cantidad de invitados", 10, 150, int(st.session_state.kids), 1)
    profile = st.radio("Tipo de combo", ["economico", "variado", "premium"], index=["economico", "variado", "premium"].index(st.session_state.profile))
    st.session_state.kids, st.session_state.profile = int(kids), profile
    if st.button("🎲 Generar una opción", type="primary", disabled=not fresh["ok"]):
        started = time.perf_counter()
        combo = generate_combo(allowed_products, allowed_rules, allowed_images, int(kids), profile)
        generation_seconds = time.perf_counter() - started
        st.session_state.combo_selection = minimal_selection(combo)
        st.session_state.combo_id = str(uuid.uuid4())[:8]
        st.session_state.combo_number += 1
        entry = {"id": st.session_state.combo_id, "number": st.session_state.combo_number, "kids": int(kids), "profile": profile, "items": dict(st.session_state.combo_selection)}
        st.session_state.history = append_history(st.session_state.history, entry)
        combo_lines = reconstruct_lines(st.session_state.combo_selection, catalog)
    for line in combo_lines:
        with st.container(border=True):
            st.markdown(f"**{line['name']}** · SKU {line['sku']}")
            quantity = st.number_input("Cantidad", 0, line["stock"], line["quantity"], 1, key=f"combo_{line['sku']}")
            st.session_state.combo_selection = set_quantity(st.session_state.combo_selection, line["sku"], quantity, line["stock"])
    if st.session_state.combo_id:
        favorite = st.session_state.combo_id in st.session_state.favorites
        if st.button("⭐ Guardado" if favorite else "☆ Guardar favorito"):
            if favorite:
                st.session_state.favorites.discard(st.session_state.combo_id)
            else:
                st.session_state.favorites.add(st.session_state.combo_id)
    if st.session_state.combo_selection and st.button("Continuar a Bolsitas y Extras"):
        st.session_state.step = navigate(1, 2)
        st.rerun()

elif st.session_state.step == 2:
    st.header("Paso 2 · Bolsitas y Extras")
    render_optional("bolsas", "Bolsitas", catalog, "bags_selection")
    render_optional("extras", "Extras", catalog, "extras_selection")
    bags_lines = reconstruct_lines(st.session_state.bags_selection, catalog, "bolsas")
    extras_lines = reconstruct_lines(st.session_state.extras_selection, catalog, "extras")
    totals = calculate_order(combo_lines, bags_lines, extras_lines, discount)
    render_price_summary(totals)
    back, forward = st.columns(2)
    if back.button("Volver al Combo"):
        st.session_state.step = navigate(2, 1)
        st.rerun()
    if forward.button("Continuar al Pedido final", type="primary"):
        st.session_state.step = navigate(2, 3)
        st.rerun()

else:
    st.header("Paso 3 · Pedido final")
    for title, lines in (("Combo de golosinas", combo_lines), ("Bolsitas", bags_lines), ("Extras", extras_lines)):
        st.subheader(title)
        if not lines:
            st.caption("Sin productos seleccionados")
        for line in lines:
            st.write(f"{line['quantity']} × {line['name']} · {money(line['subtotal'])}")
    render_price_summary(totals)
    c1, c2 = st.columns(2)
    if c1.button("Volver al Combo"):
        st.session_state.step = navigate(3, 1)
        st.rerun()
    if c2.button("Volver a Bolsitas y Extras"):
        st.session_state.step = navigate(3, 2)
        st.rerun()
    if st.button("Preparar PDF"):
        started = time.perf_counter()
        pdf = build_pdf(combo_lines, bags_lines, extras_lines, totals, st.session_state.kids, st.session_state.profile, ROOT / "assets/cotyland_logo.png")
        pdf_seconds = time.perf_counter() - started
        st.download_button("Descargar PDF final", pdf, file_name=f"pedido_cotyland_{st.session_state.combo_id}.pdf", mime="application/pdf")
        del pdf

if st.session_state.history:
    st.divider()
    st.subheader("Historial")
    for entry in reversed(st.session_state.history):
        star = "⭐ " if entry["id"] in st.session_state.favorites else ""
        if st.button(f"{star}Usar Combo #{entry['number']} · {entry['profile']} · {entry['kids']} invitados", key=f"history_{entry['id']}"):
            st.session_state.combo_selection = dict(entry["items"])
            st.session_state.combo_id = entry["id"]
            st.session_state.kids = entry["kids"]
            st.session_state.profile = entry["profile"]
            st.session_state.step = 1
            st.rerun()
