from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote, urlparse
import io, json, logging, time, uuid

import streamlit as st

from engine.generator import brand_line, generate_combo
from services.catalog import (
    LastValidStore, api_download, api_export_xlsx, api_metadata, build_reduced_catalog,
    drive_service, load_json_bytes, load_rules_xlsx, metadata_version, needs_refresh,
    optional_products, parse_csv_bytes, public_drive_download, public_drive_metadata,
    public_google_sheet_export, public_sheet_metadata, recover_source,
)
from services.freshness import freshness_status
from services import order_service
from services.pdf_service import build_comparison_pdf, build_pdf, money

active_selection=order_service.active_selection
add_flavor_candidates=order_service.add_flavor_candidates
append_history=order_service.append_history
build_combo_config=order_service.build_combo_config
calculate_order=order_service.calculate_order
navigate=order_service.navigate
normalize_selection=order_service.normalize_selection
rebalance_flavor=order_service.rebalance_flavor
reconstruct_combo_lines=order_service.reconstruct_combo_lines
reconstruct_lines=order_service.reconstruct_lines
remove_product=order_service.remove_product
restore_product=order_service.restore_product
set_free_quantity=order_service.set_free_quantity
set_quantity=order_service.set_quantity

ROOT=Path(__file__).parent
st.set_page_config(page_title="Armá tu combo | Cotyland",page_icon="🎉",layout="wide")
LOGGER=logging.getLogger(__name__)

def load_styles():
    st.markdown(f"<style>{(ROOT/'assets/styles.css').read_text(encoding='utf-8')}</style>",unsafe_allow_html=True)

load_styles()

@st.cache_resource
def get_drive_service():
    info=st.secrets.get("google_service_account",{})
    return drive_service(info) if info and info.get("client_email") else None

@st.cache_resource
def get_last_valid_store(): return LastValidStore()

@st.cache_data(ttl=900,max_entries=6,show_spinner=False)
def get_source_metadata(file_id,source_type):
    started=time.perf_counter(); service=get_drive_service()
    metadata=api_metadata(service,file_id) if service else (public_sheet_metadata(file_id) if source_type=="rules" else public_drive_metadata(file_id))
    return metadata,time.perf_counter()-started

@st.cache_data(max_entries=4,show_spinner="Actualizando stock y precios...")
def load_stock_version(file_id,version):
    started=time.perf_counter(); service=get_drive_service(); content=api_download(service,file_id) if service else public_drive_download(file_id)
    return parse_csv_bytes(content),time.perf_counter()-started

@st.cache_data(max_entries=4,show_spinner="Actualizando reglas...")
def load_rules_version(file_id,version):
    started=time.perf_counter(); service=get_drive_service(); content=api_export_xlsx(service,file_id) if service else public_google_sheet_export(file_id)
    rules=load_rules_xlsx(io.BytesIO(content))
    if rules.empty: raise ValueError("La planilla no contiene reglas activas")
    return rules,time.perf_counter()-started

@st.cache_data(max_entries=4,show_spinner=False)
def load_images_version(file_id,version):
    started=time.perf_counter(); service=get_drive_service(); content=api_download(service,file_id) if service else public_drive_download(file_id); data=load_json_bytes(content)
    return (data.get("images",{}),data.get("logoUrl","")),time.perf_counter()-started

@st.cache_data(max_entries=6,show_spinner=False)
def reduced_catalog(products,rules,images,stock_version,rules_version,images_version):
    started=time.perf_counter(); return build_reduced_catalog(products,rules,images),time.perf_counter()-started

def resolve_source(key,file_id,source_type,loader,fallback_loader):
    store=get_last_valid_store()
    try:
        metadata,metadata_seconds=get_source_metadata(file_id,source_type); version=metadata_version(metadata); cached=store.get(key)
        if not needs_refresh(cached,version): return cached[0],version,"Google Drive",None,{"metadata":metadata_seconds,"download":0.0}
        value,download_seconds=loader(file_id,version); store.set(key,(value,version)); store.set(f"{key}_metadata",metadata)
        return value,version,"Google Drive",None,{"metadata":metadata_seconds,"download":download_seconds}
    except Exception as exc:
        value,version,source=recover_source(store,key,fallback_loader); return value,version,source,str(exc),{}

def init_state():
    defaults={"step":1,"kids":20,"profile":"variado","combo_id":None,"combo_config":{"items":{},"removed_product_key":None},"bags_selection":{},"extras_selection":{},"history":[],"favorites":{},"combo_number":0,"pending_remove_key":None}
    for key,value in defaults.items():
        if key not in st.session_state: st.session_state[key]=value
    if not isinstance(st.session_state.favorites,dict): st.session_state.favorites={}

def source_status(label,source,count,error):
    message=f"{label}: {source} · {count:,}".replace(",", ".")
    st.warning(f"{message}. Detalle: {error}") if error else st.success(message)

def safe_image_url(value):
    url=str(value or "").strip(); parsed=urlparse(url)
    return url if parsed.scheme in {"http","https"} and parsed.netloc else ""

def image_markup(url,name,final=False):
    safe=safe_image_url(url); label=escape(str(name),quote=True); css="final-thumb" if final else "product-thumb"
    if not safe:
        return '<span class="thumb-placeholder visible">Imagen no disponible</span>'
    safe=escape(safe,quote=True)
    return f'<a class="thumb-link" href="{safe}" target="_blank" rel="noopener" aria-label="Ampliar {label}"><img class="{css}" src="{safe}" alt="{label}" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'"><span class="thumb-placeholder">Imagen no disponible</span></a>'

def render_brand(updated_at):
    logo,text=st.columns([1,5],vertical_alignment="center")
    with logo: st.image(ROOT/"assets/cotyland_logo.png",width=150)
    with text: st.markdown('<div class="brand-copy"><strong>Armá tu pedido a tu manera</strong>Diseñado y desarrollado por Cotyland para nuestros clientes 😉</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="update-line">Última actualización: {escape(updated_at)}</div>',unsafe_allow_html=True)

def render_progress(step):
    labels=("Combo","Bolsitas","Extras","Final")
    nodes=[]
    for number,label in enumerate(labels,1):
        state="active" if number==step else ("done" if number<step else "")
        nodes.append(f'<div class="progress-step {state}" data-step="{number}">{label}</div>')
    st.markdown('<div class="progress-wrap">'+"".join(nodes)+"</div>",unsafe_allow_html=True)

def render_heading(step,title,help_text):
    st.markdown(f'<div class="section-kicker">Paso {step} de 4</div><h1 class="section-title">{escape(title)}</h1><p class="section-help">{escape(help_text)}</p>',unsafe_allow_html=True)

def modified_label(metadata):
    raw=str(metadata.get("modifiedTime") or metadata.get("Last-Modified") or "").strip()
    if not raw: return "no informada"
    try:
        return datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw

def has_combo(): return bool(active_selection(st.session_state.combo_config))

def clear_combo_widgets():
    for key in list(st.session_state):
        if key.startswith(("flavor_","free_")): del st.session_state[key]

def logical_description(logical_key,catalog,config):
    if not logical_key: return ""
    items=[x for x in config.get("items",{}).values() if x.get("logical_key")==logical_key]
    if not items: return str(logical_key)
    if items[0].get("mode")=="compensated": return f"Grupo de sabores {logical_key}"
    rows=catalog[catalog["sku"]==items[0]["sku"]]
    return str(rows.iloc[0]["name"]) if not rows.empty else items[0]["sku"]

def update_flavor_quantity(sku):
    requested=st.session_state[f"flavor_{sku}"]; stocks={str(row.sku):int(row.stock) for row in catalog.itertuples()}
    config,ok=rebalance_flavor(st.session_state.combo_config,sku,requested,stocks)
    st.session_state.combo_config=config
    group=config["items"][sku]["flavor_group"] if sku in config["items"] else ""
    for item in config.get("items",{}).values():
        if item.get("flavor_group")==group: st.session_state[f"flavor_{item['sku']}"]=int(item["quantity"])
    st.session_state.flavor_error=None if ok else "No hay stock suficiente para mantener la cantidad obligatoria."

def update_free_quantity(sku,stock):
    st.session_state.combo_config=set_free_quantity(st.session_state.combo_config,sku,st.session_state[f"free_{sku}"],stock)

def update_optional_quantity(selection_key,sku,stock,widget_key):
    st.session_state[selection_key]=set_quantity(st.session_state[selection_key],sku,st.session_state[widget_key],stock)

def adjust_flavor_quantity(sku,delta,stock):
    current=int(st.session_state.combo_config["items"][sku]["quantity"]); requested=max(0,min(int(stock),current+delta))
    stocks={str(row.sku):int(row.stock) for row in catalog.itertuples()}; config,ok=rebalance_flavor(st.session_state.combo_config,sku,requested,stocks)
    st.session_state.combo_config=config; st.session_state.flavor_error=None if ok else "No hay stock suficiente para mantener la cantidad obligatoria."

def adjust_free_quantity(sku,delta,stock):
    item=st.session_state.combo_config["items"][sku]; requested=max(int(item["base_quantity"]),min(int(stock),int(item["quantity"])+delta))
    st.session_state.combo_config=set_free_quantity(st.session_state.combo_config,sku,requested,stock)

def adjust_optional_quantity(selection_key,sku,delta,stock):
    current=int(st.session_state[selection_key].get(sku,0)); st.session_state[selection_key]=set_quantity(st.session_state[selection_key],sku,current+delta,stock)

def compact_quantity(value,minus_key,plus_key,minus_action,plus_action,disabled=False):
    minus,amount,plus=st.columns([1,1.25,1])
    minus.button("−",key=minus_key,on_click=minus_action,disabled=disabled,use_container_width=True)
    amount.markdown(f'<div class="qty-value">{int(value)}</div>',unsafe_allow_html=True)
    plus.button("＋",key=plus_key,on_click=plus_action,disabled=disabled,use_container_width=True)

def render_remove_control(logical_key):
    removed=st.session_state.combo_config.get("removed_product_key")
    if removed==logical_key:
        if st.button("Restaurar producto",key=f"restore_{logical_key}"):
            st.session_state.combo_config=restore_product(st.session_state.combo_config); st.rerun()
        return
    if st.button("Quitar producto",key=f"remove_{logical_key}",disabled=removed is not None):
        st.session_state.pending_remove_key=logical_key; st.rerun()
    if st.session_state.pending_remove_key==logical_key:
        st.warning("Podés quitar un solo producto del combo. Los demás quedarán obligatorios.")
        yes,no=st.columns(2)
        if yes.button("Confirmar",key=f"confirm_{logical_key}"):
            st.session_state.combo_config=remove_product(st.session_state.combo_config,logical_key); st.session_state.pending_remove_key=None; st.rerun()
        if no.button("Cancelar",key=f"cancel_{logical_key}"):
            st.session_state.pending_remove_key=None; st.rerun()

def render_combo_editor(catalog):
    config=st.session_state.combo_config; groups={}
    for item in config.get("items",{}).values(): groups.setdefault(item["logical_key"],[]).append(item)
    for logical_key,items in groups.items():
        removed=config.get("removed_product_key")==logical_key
        with st.container(border=True):
            mode=items[0]["mode"]
            st.markdown(f"**{escape(logical_description(logical_key,catalog,config))}** " + ('<span class="removed-label">QUITADO</span>' if removed else ""),unsafe_allow_html=True)
            if mode=="compensated":
                st.caption(f"Elegí sabores manteniendo {items[0]['required_total']} unidades en total.")
                for item in items:
                    row=catalog[catalog["sku"]==item["sku"]]
                    if row.empty or int(row.iloc[0]["stock"])<=0: continue
                    product=row.iloc[0]; qty=int(item["quantity"]); media,details,controls=st.columns([1.05,3.1,2],vertical_alignment="center")
                    with media: st.markdown(image_markup(product["image_url"],product["name"]),unsafe_allow_html=True)
                    with details:
                        st.markdown(f"**{escape(str(product['name']))}**")
                        st.markdown(f'<div class="product-price">{money(product["price"])} c/u</div><div class="product-subtotal">{money(qty*float(product["price"]))}</div>',unsafe_allow_html=True)
                    with controls:
                        compact_quantity(qty,f"flavor_minus_{item['sku']}",f"flavor_plus_{item['sku']}",lambda sku=item["sku"],stock=int(product["stock"]):adjust_flavor_quantity(sku,-1,stock),lambda sku=item["sku"],stock=int(product["stock"]):adjust_flavor_quantity(sku,1,stock),removed)
            else:
                row=catalog[catalog["sku"]==items[0]["sku"]]
                if not row.empty:
                    item=items[0]; product=row.iloc[0]; qty=int(item["quantity"]); media,details,controls=st.columns([1.05,3.1,2],vertical_alignment="center")
                    with media: st.markdown(image_markup(product["image_url"],product["name"]),unsafe_allow_html=True)
                    with details:
                        st.markdown(f"**{escape(str(product['name']))}**")
                        st.markdown(f'<div class="product-price">{money(product["price"])} c/u</div><div class="product-meta">Cantidad {qty}</div><div class="product-subtotal">{money(qty*float(product["price"]))}</div>',unsafe_allow_html=True)
                    with controls:
                        if mode=="free": compact_quantity(qty,f"free_minus_{item['sku']}",f"free_plus_{item['sku']}",lambda sku=item["sku"],stock=int(product["stock"]):adjust_free_quantity(sku,-1,stock),lambda sku=item["sku"],stock=int(product["stock"]):adjust_free_quantity(sku,1,stock),removed)
                        else: st.markdown(f'<div class="qty-value">{qty}</div><div class="product-meta" style="text-align:center">Cantidad fija</div>',unsafe_allow_html=True)
            render_remove_control(logical_key)
    if st.session_state.get("flavor_error"): st.error(st.session_state.flavor_error)

def render_optional(category,title,catalog,selection_key):
    products=optional_products(catalog,category); selection=normalize_selection(st.session_state[selection_key],catalog,category)
    if products.empty: st.info(f"No hay productos disponibles en {title}.")
    columns=st.columns(2)
    for index,row in enumerate(products.itertuples()):
        qty=int(selection.get(row.sku,0))
        with columns[index%2]:
            with st.container(border=True):
                media,details=st.columns([1,2.25],vertical_alignment="center")
                with media: st.markdown(image_markup(row.image_url,row.name),unsafe_allow_html=True)
                with details:
                    st.markdown(f"**{escape(str(row.name))}**")
                    st.markdown(f'<div class="product-price">{money(row.price)} c/u</div><div class="stock-label">Stock disponible: {int(row.stock)}</div><div class="product-subtotal">{money(qty*row.price)}</div>',unsafe_allow_html=True)
                compact_quantity(qty,f"{selection_key}_minus_{row.sku}",f"{selection_key}_plus_{row.sku}",lambda sku=row.sku,stock=int(row.stock):adjust_optional_quantity(selection_key,sku,-1,stock),lambda sku=row.sku,stock=int(row.stock):adjust_optional_quantity(selection_key,sku,1,stock))
    st.session_state[selection_key]=selection

def render_price_summary(totals):
    st.markdown(f'''<div class="desktop-breakdown"><div class="summary-title">Resumen del pedido</div>
    <div class="summary-line"><span>Subtotal del combo</span><strong>{money(totals['combo_subtotal'])}</strong></div>
    <div class="summary-line saving"><span>Descuento</span><strong>-{money(totals['discount_amount'])}</strong></div>
    <div class="summary-line"><span>Bolsitas</span><strong>{money(totals['bags_subtotal'])}</strong></div>
    <div class="summary-line"><span>Extras</span><strong>{money(totals['extras_subtotal'])}</strong></div></div>
    <div class="summary-total"><span>TOTAL</span><strong>{money(totals['total'])}</strong></div>
    <div class="summary-saving">Ahorrás {money(totals['savings'])}</div>''',unsafe_allow_html=True)

def render_final_lines(title,lines):
    st.subheader(title)
    if not lines: st.caption("Sin productos seleccionados"); return
    with st.container(border=True):
        for line in lines:
            st.markdown(f'<div class="final-row">{image_markup(line.get("image_url"),line["name"],True)}<div class="final-qty">{int(line["quantity"])}×</div><div class="final-name">{escape(str(line["name"]))}</div><div class="final-price">{money(line["subtotal"])}</div></div>',unsafe_allow_html=True)

def update_history_current():
    for entry in st.session_state.history:
        if entry["id"]==st.session_state.combo_id: entry["config"]=deepcopy(st.session_state.combo_config)

init_state()
drive_cfg=st.secrets.get("drive",{}); company=dict(st.secrets.get("company",{}))
stock_id=drive_cfg.get("stock_file_id","1D4gde-bbWlPw910hxaVQidpfIULShhS8"); rules_id=drive_cfg.get("rules_file_id","10kmGyYwpE4f-ujUgAigwDrQ7uS5DQHs_jQYxcFDNDQc"); images_id=drive_cfg.get("images_index_file_id","1fqSlwCqGvyB2W9W0b-3zZrvxp-KjHI4i")
products,stock_version,stock_source,stock_error,_=resolve_source("stock",stock_id,"stock",load_stock_version,lambda:parse_csv_bytes((ROOT/"data/GOLOSINERO_fallback.csv").read_bytes()))
rules,rules_version,rules_source,rules_error,_=resolve_source("rules",rules_id,"rules",load_rules_version,lambda:load_rules_xlsx(ROOT/"data/reglas_combos.xlsx"))
(images,logo_url),images_version,images_source,images_error,_=resolve_source("images",images_id,"images",load_images_version,lambda:(lambda d:(d.get("images",{}),d.get("logoUrl","")))(json.loads((ROOT/"data/imagenes_index_fallback.json").read_text(encoding="utf-8"))))
catalog,_=reduced_catalog(products,rules,images,stock_version,rules_version,images_version)
allowed_products=catalog[["sku","name","price","stock"]]; allowed_rules=rules[rules["sku"].isin(set(catalog["sku"]))]; allowed_images=dict(zip(catalog["sku"],catalog["image_url"]))
discount=int(st.secrets.get("app",{}).get("discount_percent",5)); fresh_cfg=dict(st.secrets.get("freshness",{})) or {"timezone":"America/Argentina/Buenos_Aires","max_age_minutes_open":120,"max_age_hours_closed":72,"open_weekdays":[0,1,2,3,4,5],"open_ranges":["09:00-13:00","14:30-19:30"]}
stock_metadata=get_last_valid_store().get("stock_metadata") or {}; fresh=freshness_status(stock_metadata.get("modifiedTime"),fresh_cfg) if stock_metadata else {"ok":True,"message":"Catálogo disponible"}

if st.session_state.step>1 and not has_combo(): st.session_state.step=1
combo_lines=reconstruct_combo_lines(st.session_state.combo_config,catalog); bags_lines=reconstruct_lines(st.session_state.bags_selection,catalog,"bolsas"); extras_lines=reconstruct_lines(st.session_state.extras_selection,catalog,"extras"); totals=calculate_order(combo_lines,bags_lines,extras_lines,discount)

for label,error in (("stock",stock_error),("reglas",rules_error),("imágenes",images_error)):
    if error: LOGGER.warning("No se pudo actualizar %s: %s",label,error)
if stock_error and stock_source=="fallback local": st.error("No pudimos actualizar el catálogo. Estamos mostrando la última versión disponible.")

render_brand(modified_label(stock_metadata)); render_progress(st.session_state.step)
main,summary=st.columns([3.35,1.25],gap="large")

with main:
    if st.session_state.step==1:
        render_heading(1,"Generá tu combo","Elegí la cantidad de invitados y el perfil. Después podés personalizarlo.")
        setup_left,setup_right=st.columns([1,1.6],vertical_alignment="bottom")
        with setup_left: kids=st.number_input("Cantidad de invitados",10,150,int(st.session_state.kids),1)
        profiles=["economico","variado","premium"]
        with setup_right: profile=st.radio("Tipo de combo",profiles,index=profiles.index(st.session_state.profile),horizontal=True)
        st.session_state.kids,st.session_state.profile=int(kids),profile
        if st.button("🎲 Generar una opción",type="primary",disabled=not fresh["ok"],use_container_width=True):
            clear_combo_widgets(); combo=generate_combo(allowed_products,allowed_rules,allowed_images,int(kids),profile); config=build_combo_config(combo)
            for group in {x["flavor_group"] for x in config["items"].values() if x["mode"]=="compensated"}:
                template=next(x for x in config["items"].values() if x.get("flavor_group")==group)
                candidates=[{"sku":row.sku} for row in catalog.itertuples() if row.category==template["category"] and int(row.pack_units)==template["pack_units"] and int(row.stock)>0 and brand_line(row.name,row.category)==group]
                config=add_flavor_candidates(config,group,candidates)
            st.session_state.combo_config=config; st.session_state.combo_id=str(uuid.uuid4())[:8]; st.session_state.combo_number+=1
            entry={"id":st.session_state.combo_id,"number":st.session_state.combo_number,"kids":int(kids),"profile":profile,"config":deepcopy(config)}; st.session_state.history=append_history(st.session_state.history,entry); st.rerun()
        if has_combo():
            st.subheader("Tu combo está listo"); render_combo_editor(catalog)
            favorite=st.session_state.combo_id in st.session_state.favorites
            if st.button("⭐ Guardado" if favorite else "☆ Guardar favorito"):
                if favorite: st.session_state.favorites.pop(st.session_state.combo_id,None)
                else: st.session_state.favorites[st.session_state.combo_id]={"id":st.session_state.combo_id,"number":st.session_state.combo_number,"kids":st.session_state.kids,"profile":st.session_state.profile,"config":deepcopy(st.session_state.combo_config)}
                st.rerun()
        else: st.info("Primero generá o seleccioná un combo.")

    elif st.session_state.step==2:
        render_heading(2,"Elegí las Bolsitas","Sumá solamente las bolsas que necesites o continuá sin agregar ninguna.")
        render_optional("bolsas","Bolsitas",catalog,"bags_selection")
        if st.button("← Volver al Combo"): st.session_state.step=1; st.rerun()

    elif st.session_state.step==3:
        render_heading(3,"Agregá Extras","Completá el pedido con productos opcionales o continuá sin extras.")
        render_optional("extras","Extras",catalog,"extras_selection")
        if st.button("← Volver a Bolsitas"): st.session_state.step=2; st.rerun()

    else:
        render_heading(4,"Finalizá el pedido","Revisá el resumen, prepará el PDF y comunicate con Cotyland.")
        render_final_lines("Golosinas del combo",combo_lines); render_final_lines("Bolsitas",bags_lines); render_final_lines("Extras",extras_lines)
        removed=logical_description(st.session_state.combo_config.get("removed_product_key"),catalog,st.session_state.combo_config)
        if st.button("Preparar PDF"):
            pdf=build_pdf(combo_lines,bags_lines,extras_lines,totals,st.session_state.kids,st.session_state.profile,company,removed,ROOT/"assets/cotyland_logo.png")
            st.download_button("Descargar PDF final",pdf,file_name=f"pedido_cotyland_{st.session_state.combo_id}.pdf",mime="application/pdf",use_container_width=True); del pdf
        back_combo,back_extras=st.columns(2)
        if back_combo.button("Editar Combo",use_container_width=True): st.session_state.step=1; st.rerun()
        if back_extras.button("Editar Extras",use_container_width=True): st.session_state.step=3; st.rerun()

with summary:
    st.markdown('<div class="summary-marker"></div>',unsafe_allow_html=True); render_price_summary(totals)
    if st.session_state.step==1:
        if st.button("Continuar a Bolsitas →",type="primary",disabled=not has_combo(),use_container_width=True): st.session_state.step=navigate(1,2,has_combo()); st.rerun()
    elif st.session_state.step==2:
        if st.button("Continuar a Extras →",type="primary",use_container_width=True): st.session_state.step=navigate(2,3,has_combo()); st.rerun()
    elif st.session_state.step==3:
        if st.button("Continuar al pedido →",type="primary",use_container_width=True): st.session_state.step=navigate(3,4,has_combo()); st.rerun()
    else:
        number=company.get("whatsapp_number","5491125244522")
        message=f"Hola Cotyland, preparé un pedido para {st.session_state.kids} invitados, perfil {st.session_state.profile}, total {money(totals['total'])}. Voy a adjuntar el PDF."
        st.link_button("◉ Enviar por WhatsApp",f"https://wa.me/{number}?text={quote(message)}",use_container_width=True)

update_history_current()
if st.session_state.favorites:
    st.divider(); st.subheader("Favoritos")
    for favorite in reversed(list(st.session_state.favorites.values())):
        with st.expander(f"⭐ Combo #{favorite['number']} · {favorite['profile']} · {favorite['kids']} invitados"):
            cols=st.columns(4)
            for col,target,label in zip(cols,(1,2,3,4),("Editar combo","Ir a Bolsitas","Ir a Extras","Pedido final")):
                if col.button(label,key=f"fav_{favorite['id']}_{target}"):
                    clear_combo_widgets(); st.session_state.combo_config=deepcopy(favorite["config"]); st.session_state.combo_id=favorite["id"]; st.session_state.kids=favorite["kids"]; st.session_state.profile=favorite["profile"]; st.session_state.step=target; st.rerun()

if st.session_state.history:
    st.divider(); st.subheader("Combos vistos")
    for entry in reversed(st.session_state.history):
        if st.button(f"Usar Combo #{entry['number']} · {entry['profile']} · {entry['kids']} invitados",key=f"history_{entry['id']}"):
            clear_combo_widgets(); st.session_state.combo_config=deepcopy(entry["config"]); st.session_state.combo_id=entry["id"]; st.session_state.kids=entry["kids"]; st.session_state.profile=entry["profile"]; st.session_state.step=1; st.rerun()
    if st.button("Descargar comparación"):
        entries=[]
        comparison_sources=list(st.session_state.history)
        known_ids={entry["id"] for entry in comparison_sources}
        comparison_sources.extend(entry for entry in st.session_state.favorites.values() if entry["id"] not in known_ids)
        for entry in comparison_sources:
            lines=reconstruct_combo_lines(entry["config"],catalog); entry_totals=calculate_order(lines,[],[],discount); removed=logical_description(entry["config"].get("removed_product_key"),catalog,entry["config"])
            entries.append({**entry,"lines":lines,"totals":entry_totals,"removed_product":removed})
        comparison=build_comparison_pdf(entries,company,ROOT/"assets/cotyland_logo.png")
        st.download_button("Guardar comparación",comparison,file_name="comparacion_combos_cotyland.pdf",mime="application/pdf"); del comparison

contact=[]
for label,key in (("WhatsApp","whatsapp_display"),("Web","website"),("Instagram","instagram"),("Dirección","address")):
    if company.get(key): contact.append(f"**{label}:** {company[key]}")
if contact: st.divider(); st.markdown("  \n".join(contact)); st.caption("Envíanos tu pedido por WhatsApp para confirmar disponibilidad.")
st.caption("Diseñado y desarrollado por Cotyland para nuestros clientes 😉")
