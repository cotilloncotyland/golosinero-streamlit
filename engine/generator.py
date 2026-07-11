from __future__ import annotations
import math, random, re
import pandas as pd
from .models import ComboItem

PROFILE_COUNTS={"economico":(3,4),"variado":(4,6),"premium":(6,8)}
PROFILE_WEIGHTS={
"economico":{"alfajor":2.4,"chocolate":2.4,"chupetin":1.2,"caramelos":1.15,"pastillas":.9,"jugos":1.35,"gomitas":.85,"malvaviscos":.75,"turrones":1.25},
"variado":{"alfajor":1.8,"chocolate":1.9,"chupetin":1.25,"caramelos":1.1,"pastillas":1,"jugos":1.35,"gomitas":1.2,"malvaviscos":1,"turrones":1.25},
"premium":{"alfajor":1.5,"chocolate":2,"chupetin":1.4,"caramelos":1.2,"pastillas":1.1,"jugos":1.4,"gomitas":1.45,"malvaviscos":1.2,"turrones":1.2}}


def brand_line(name, category):
    n=re.sub(r"\s+"," ",name.upper())
    keys=["GUAYMALLEN","GEORGALOS","MISKY","CRAZY POP","BABY DOLL","BAGGIO JUNIOR","FLYNN PAFF"]
    for k in keys:
        if k in n: return f"{category}:{k}"
    return f"{category}:{n.split(' X')[0][:28]}"


def weighted_sample(items, weights, k, rng):
    pool=list(items); out=[]
    while pool and len(out)<k:
        ws=[max(.001,weights.get(x,1)) for x in pool]
        choice=rng.choices(pool,weights=ws,k=1)[0]
        out.append(choice); pool.remove(choice)
    return out


def choose_plan(candidates, kids, profile, rng):
    plans=[]
    for row in candidates.to_dict("records"):
        pack=max(1,int(row["pack_units"])); qty=math.ceil(kids/pack)
        if row["stock"] < qty or row["price"]<=0: continue
        surplus=qty*pack-kids
        # Sobras chicas compiten; las grandes pierden peso pero no se bloquean.
        surplus_ratio=surplus/max(kids,1)
        closeness=1/(1+surplus_ratio*3)
        price_weight=1
        if profile=="economico": price_weight=1/(1+row["price"]/25000)
        plans.append((row,qty,closeness*price_weight))
    if not plans: return None
    return rng.choices(plans,weights=[p[2] for p in plans],k=1)[0][:2]


def mix_flavors(group, kids, rng):
    if len(group)<2: return None
    packs=group["pack_units"].unique()
    if len(packs)!=1: return None
    pack=max(1,int(packs[0])); total_qty=math.ceil(kids/pack)
    if group["stock"].sum()<total_qty: return None
    rows=group.sample(frac=1,random_state=rng.randrange(1_000_000)).to_dict("records")
    allocations=[]; remaining=total_qty
    for i,row in enumerate(rows):
        if remaining<=0: break
        slots=len(rows)-i
        qty=min(int(row["stock"]), math.ceil(remaining/slots), remaining)
        if qty>0: allocations.append((row,qty)); remaining-=qty
    return allocations if remaining==0 else None


def generate_combo(products: pd.DataFrame, rules: pd.DataFrame, images: dict, kids:int, profile:str, seed=None):
    rng=random.Random(seed)
    merged=rules.merge(products,on="sku",how="inner")
    merged=merged[(merged.stock>0)&(merged.price>0)]
    merged["brand_line"]=[brand_line(n,c) for n,c in zip(merged.name,merged.category)]
    available=[c for c in merged.category.unique() if c not in {"extras","bolsas"}]
    lo,hi=PROFILE_COUNTS[profile]; count=min(len(available),rng.randint(lo,hi))
    cats=weighted_sample(available,PROFILE_WEIGHTS[profile],count,rng)
    result=[]
    for cat in cats:
        cand=merged[merged.category==cat].copy()
        if cand.empty: continue
        # Caramelos: una bolsa base; Lheritier mínimo 2.
        if cat=="caramelos":
            row=cand.sample(1,random_state=rng.randrange(1_000_000)).iloc[0].to_dict()
            is_lh="LHERITIER" in row["name"].upper()
            qty=2 if is_lh else 1
            if row["stock"]<qty: continue
            recommended=max(1,math.ceil(kids/max(1,int(row["pack_units"]))))
            note=(f"Incluye 2 bolsas como mínimo. Para {kids} invitados se recomiendan {recommended}." if is_lh else f"Incluye 1 bolsa. Para {kids} invitados se recomiendan {recommended}; podés sumar más.")
            result.append(ComboItem(row["sku"],row["name"],cat,qty,int(row["pack_units"]),float(row["price"]),int(row["stock"]),images.get(row["sku"],""),note=note))
            continue
        # Familias con sabores editables.
        if cat in {"jugos","alfajor","chocolate","chupetin"}:
            groups=[g for _,g in cand.groupby(["brand_line","pack_units"])]
            rng.shuffle(groups)
            mixed=None
            for g in groups:
                if len(g)>=2:
                    mixed=mix_flavors(g,kids,rng)
                    if mixed: break
            if mixed:
                fg=mixed[0][0]["brand_line"]
                for row,qty in mixed:
                    result.append(ComboItem(row["sku"],row["name"],cat,qty,int(row["pack_units"]),float(row["price"]),int(row["stock"]),images.get(row["sku"],""),fg,True,"Reparto editable de sabores."))
                continue
        plan=choose_plan(cand,kids,profile,rng)
        if plan:
            row,qty=plan
            result.append(ComboItem(row["sku"],row["name"],cat,int(qty),int(row["pack_units"]),float(row["price"]),int(row["stock"]),images.get(row["sku"],"")))
    return result


def combo_total(items, discount=5):
    subtotal=sum(i.quantity*i.unit_price for i in items)
    return subtotal, subtotal*(1-discount/100)
