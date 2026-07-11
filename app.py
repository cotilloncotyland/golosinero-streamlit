from __future__ import annotations
from pathlib import Path
from datetime import datetime
import io, json, uuid
import streamlit as st
import pandas as pd

from services.catalog import parse_csv_bytes, load_rules_xlsx, public_drive_download, drive_service, api_metadata, api_download, load_json_bytes
from services.freshness import freshness_status
from engine.generator import generate_combo, combo_total
from engine.models import ComboItem
from services.pdf_service import build_pdf, money

ROOT=Path(__file__).parent
st.set_page_config(page_title="Armá tu combo | Cotyland",page_icon="🎉",layout="wide")

@st.cache_resource
def get_drive_service():
    try:
        info=st.secrets.get("google_service_account",{})
        if info and info.get("client_email"):
            return drive_service(info)
    except Exception: pass
    return None

@st.cache_data(ttl=60,show_spinner=False)
def get_stock_metadata(file_id):
    service=get_drive_service()
    if service: return api_metadata(service,file_id)
    return {"id":file_id,"name":"GOLOSINERO.CSV","modifiedTime":None}

@st.cache_data(show_spinner="Actualizando stock y precios...")
def load_stock(file_id, version):
    service=get_drive_service()
    content=api_download(service,file_id) if service else public_drive_download(file_id)
    return parse_csv_bytes(content)

@st.cache_data(ttl=300,show_spinner=False)
def load_images(index_id):
    if index_id:
        service=get_drive_service()
        try:
            content=api_download(service,index_id) if service else public_drive_download(index_id)
            data=load_json_bytes(content)
            return data.get("images",{}),data.get("logoUrl","")
        except Exception: pass
    data=json.loads((ROOT/'data/imagenes_index_fallback.json').read_text(encoding='utf-8'))
    return data.get("images",{}),data.get("logoUrl","")

@st.cache_data(show_spinner=False)
def load_rules():
    return load_rules_xlsx(ROOT/'data/reglas_combos.xlsx')


def init_state():
    defaults={"history":[],"favorites":set(),"active_id":None,"combo":None,"combo_id":None}
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k]=v
init_state()

# Data source
stock_id=st.secrets.get("drive",{}).get("stock_file_id","1D4gde-bbWlPw910hxaVQidpfIULShhS8")
index_id=st.secrets.get("drive",{}).get("images_index_file_id","")
meta=get_stock_metadata(stock_id)
version=meta.get("modifiedTime") or meta.get("md5Checksum") or str(meta.get("size","public"))
try:
    products=load_stock(stock_id,version)
except Exception as exc:
    st.warning(f"No pude leer Drive, uso la copia de prueba incluida. Detalle: {exc}")
    products=parse_csv_bytes((ROOT/'data/GOLOSINERO_fallback.csv').read_bytes())
rules=load_rules(); images,logo_url=load_images(index_id)

fresh_cfg=dict(st.secrets.get("freshness",{})) or {"timezone":"America/Argentina/Buenos_Aires","max_age_minutes_open":120,"max_age_hours_closed":72,"open_weekdays":[0,1,2,3,4,5],"open_ranges":["09:00-13:00","14:30-19:30"]}
fresh=freshness_status(meta.get("modifiedTime"),fresh_cfg)
discount=int(st.secrets.get("app",{}).get("discount_percent",5))

# Header
c1,c2=st.columns([1,4])
with c1:
    st.image(str(ROOT/'assets/cotyland_logo.png'),width=170)
with c2:
    st.title("Armá tu combo de cumpleaños")
    st.caption("Elegí, compará, editá sabores y descargá el presupuesto.")

if fresh["ok"]:
    st.success(f"🟢 {fresh['message']} · {len(products):,} SKU leídos".replace(",","."))
else:
    st.error("🔴 "+fresh["message"])

with st.sidebar:
    st.header("1. Tu fiesta")
    kids=st.number_input("Cantidad de invitados",min_value=10,max_value=150,value=20,step=1)
    profile=st.radio("Tipo de combo",["economico","variado","premium"],format_func=lambda x:{"economico":"Económico","variado":"Variado","premium":"Premium"}[x])
    can_generate=fresh["ok"]
    if st.button("🎲 Generar una opción",type="primary",use_container_width=True,disabled=not can_generate):
        combo=generate_combo(products,rules,images,int(kids),profile)
        cid=str(uuid.uuid4())[:8]
        entry={"id":cid,"number":len(st.session_state.history)+1,"kids":int(kids),"profile":profile,"items":[x.to_dict() for x in combo]}
        st.session_state.history.append(entry); st.session_state.combo=combo; st.session_state.combo_id=cid; st.session_state.active_id=cid
        st.rerun()
    st.caption("Fuera del horario comercial se permite una antigüedad mayor para cubrir cierres y fines de semana. Los límites se cambian en Secrets, sin tocar código.")

# Active combo
if st.session_state.combo:
    combo=st.session_state.combo
    subtotal,total=combo_total(combo,discount)
    st.subheader(f"Combo #{next((h['number'] for h in st.session_state.history if h['id']==st.session_state.combo_id),1)} · {kids} invitados")
    st.metric("Total estimado",money(total),f"{discount}% aplicado")
    for idx,item in enumerate(combo):
        with st.container(border=True):
            a,b=st.columns([1,4])
            with a:
                if item.image_url: st.image(item.image_url,use_container_width=True)
                else: st.caption("Sin imagen")
            with b:
                st.markdown(f"**{item.name}**")
                st.caption(f"SKU {item.sku} · {item.category.capitalize()} · Stock {item.stock}")
                new_qty=st.number_input("Cantidad",min_value=0,max_value=item.stock,value=item.quantity,key=f"qty_{st.session_state.combo_id}_{idx}")
                item.quantity=int(new_qty)
                if item.note: st.info(item.note)
    subtotal,total=combo_total(combo,discount)
    star=st.session_state.combo_id in st.session_state.favorites
    x,y=st.columns(2)
    with x:
        if st.button("⭐ Guardado" if star else "☆ Me gusta",use_container_width=True):
            if star: st.session_state.favorites.discard(st.session_state.combo_id)
            else: st.session_state.favorites.add(st.session_state.combo_id)
            st.rerun()
    with y:
        pdf=build_pdf(combo,int(kids),profile,discount,ROOT/'assets/cotyland_logo.png')
        st.download_button("📄 Descargar PDF",pdf,file_name=f"combo_cotyland_{st.session_state.combo_id}.pdf",mime="application/pdf",use_container_width=True)
    st.info("Cuando elijas el combo definitivo, descargá el PDF y envialo por WhatsApp a Cotyland para confirmar disponibilidad y preparar el pedido.")
else:
    st.info("Indicá invitados y perfil. Después tocá **Generar una opción**.")

# History / favorites
if st.session_state.history:
    st.divider(); st.subheader("Combos vistos")
    fav_only=st.toggle("Mostrar solo favoritos ⭐",value=False)
    entries=list(reversed(st.session_state.history))
    if fav_only: entries=[h for h in entries if h['id'] in st.session_state.favorites]
    for h in entries:
        items=[ComboItem(**d) for d in h["items"]]
        _,htotal=combo_total(items,discount)
        label=f"{'⭐ ' if h['id'] in st.session_state.favorites else ''}Combo #{h['number']} · {h['profile'].capitalize()} · {h['kids']} invitados · {money(htotal)}"
        with st.expander(label):
            for it in items: st.write(f"{it.quantity} × {it.name}")
            if st.button("Usar y editar este combo",key=f"use_{h['id']}"):
                st.session_state.combo=items; st.session_state.combo_id=h['id']; st.session_state.active_id=h['id']; st.rerun()
