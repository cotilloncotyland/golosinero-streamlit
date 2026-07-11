from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def parse_ranges(ranges):
    out=[]
    for value in ranges:
        a,b=value.split("-",1)
        ah,am=map(int,a.split(":")); bh,bm=map(int,b.split(":"))
        out.append((time(ah,am),time(bh,bm)))
    return out


def freshness_status(modified_iso, settings, now=None):
    tz=ZoneInfo(settings.get("timezone","America/Argentina/Buenos_Aires"))
    now=now or datetime.now(tz)
    if not modified_iso:
        return {"ok":True,"age_minutes":None,"store_open":False,"message":"No se pudo comprobar la fecha automáticamente. Usando la última base válida."}
    dt=datetime.fromisoformat(modified_iso.replace("Z","+00:00")).astimezone(tz)
    age=(now-dt).total_seconds()/60
    weekdays=list(settings.get("open_weekdays",[0,1,2,3,4,5]))
    ranges=parse_ranges(settings.get("open_ranges",["09:00-13:00","14:30-19:30"]))
    is_open=now.weekday() in weekdays and any(a <= now.time() <= b for a,b in ranges)
    limit=float(settings.get("max_age_minutes_open",120)) if is_open else float(settings.get("max_age_hours_closed",72))*60
    ok=age <= limit
    if ok:
        msg=f"Datos actualizados hace {max(0,int(age))} minutos."
    else:
        msg=f"La base no se actualiza desde hace {int(age/60)} h. Por seguridad, la generación está pausada."
    return {"ok":ok,"age_minutes":age,"store_open":is_open,"message":msg,"modified_local":dt.strftime("%d/%m/%Y %H:%M")}
