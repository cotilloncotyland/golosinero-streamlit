from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd
import requests


REQUIRED_COLUMNS = [
    "Descripcion",
    "Precio_Venta_Final",
    "IdArticulo",
    "Stock",
]


class LastValidStore:
    def __init__(self):
        self._values = {}
        self._lock = RLock()

    def get(self, key):
        with self._lock:
            return self._values.get(key)

    def set(self, key, value):
        with self._lock:
            self._values[key] = value


def metadata_version(metadata: dict) -> str:
    """
    Devuelve una versión estable de la fuente.

    Para archivos públicos de Drive se prioriza el SHA-256 del contenido,
    porque Last-Modified puede quedar desactualizado por la caché pública
    de Google Drive.
    """
    for key in (
        "sha256Checksum",
        "md5Checksum",
        "modifiedTime",
        "size",
        "etag",
        "Last-Modified",
        "Content-Length",
    ):
        value = metadata.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"

    return "unknown"


def needs_refresh(cached, version: str) -> bool:
    return cached is None or cached[1] != version


def recover_source(store: LastValidStore, key: str, fallback_loader):
    cached = store.get(key)

    if cached is not None:
        return cached[0], cached[1], "última caché válida"

    return fallback_loader(), "fallback", "fallback local"


def build_reduced_catalog(
    products: pd.DataFrame,
    rules: pd.DataFrame,
    images: dict,
) -> pd.DataFrame:
    product_fields = products[["sku", "name", "price", "stock"]].copy()

    catalog = rules[
        ["sku", "category", "pack_units"]
    ].merge(
        product_fields,
        on="sku",
        how="inner",
    )

    catalog["image_url"] = catalog["sku"].map(images).fillna("")

    return catalog[
        [
            "sku",
            "name",
            "price",
            "stock",
            "category",
            "pack_units",
            "image_url",
        ]
    ].drop_duplicates(
        "sku",
        keep="last",
    )


def optional_products(
    catalog: pd.DataFrame,
    category: str,
) -> pd.DataFrame:
    return catalog[
        (catalog["category"] == category)
        & (catalog["stock"] > 0)
    ].copy()


def normalize_sku(value: Any) -> str:
    s = "" if value is None else str(value)

    s = (
        s.replace("\ufeff", "")
        .replace("\xa0", " ")
        .strip()
    )

    s = re.sub(r"\s+", "", s).strip("'")

    return re.sub(r"\.0+$", "", s)


def parse_decimal(value: Any) -> float:
    s = (
        str(value or "")
        .strip()
        .replace("$", "")
        .replace(" ", "")
    )

    if not s:
        return 0.0

    if "," in s:
        s = s.replace(".", "").replace(",", ".")

    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_csv_bytes(content: bytes) -> pd.DataFrame:
    # Parser validado:
    # líneas físicas + separador ;.
    # No interpreta las comillas de pulgadas.
    text = content.decode(
        "utf-8-sig",
        errors="replace",
    )

    rows = []

    lines = [
        line
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        raise ValueError("El CSV está vacío")

    headers = [
        column.strip()
        for column in lines[0].split(";")
    ]

    if headers[:4] != REQUIRED_COLUMNS:
        raise ValueError(
            f"Encabezados inválidos: {headers[:4]}"
        )

    malformed = []

    for number, line in enumerate(
        lines[1:],
        start=2,
    ):
        parts = line.split(";")

        if len(parts) != 4:
            malformed.append(
                (
                    number,
                    len(parts),
                    line[:100],
                )
            )
            continue

        rows.append(parts)

    if malformed:
        raise ValueError(
            "Hay "
            f"{len(malformed)} filas mal formadas. "
            f"Primera: {malformed[0]}"
        )

    df = pd.DataFrame(
        rows,
        columns=REQUIRED_COLUMNS,
    )

    df["sku"] = df["IdArticulo"].map(
        normalize_sku
    )

    df["name"] = (
        df["Descripcion"]
        .astype(str)
        .str.strip()
    )

    df["price"] = df[
        "Precio_Venta_Final"
    ].map(
        parse_decimal
    )

    df["stock_raw"] = df["Stock"].map(
        parse_decimal
    )

    # Para ventas por unidades/cajas,
    # nunca prometer fracciones.
    df["stock"] = (
        df["stock_raw"]
        .clip(lower=0)
        .astype(int)
    )

    df = (
        df[df["sku"] != ""]
        .drop_duplicates(
            "sku",
            keep="last",
        )
    )

    return df[
        [
            "sku",
            "name",
            "price",
            "stock",
            "stock_raw",
        ]
    ]


def load_rules_xlsx(path_or_bytes) -> pd.DataFrame:
    df = pd.read_excel(
        path_or_bytes,
        sheet_name="Planilla",
        dtype=str,
    )

    categories = [
        "ALFAJOR",
        "CHOCOLATE",
        "CHUPETIN",
        "CARAMELOS",
        "PASTILLAS",
        "JUGOS",
        "GOMITAS",
        "MALVAVISCOS",
        "BOLSAS",
        "EXTRAS",
        "TURRONES",
    ]

    records = []

    for _, row in df.iterrows():
        sku = normalize_sku(
            row.get("SKU")
        )

        if not sku:
            continue

        divisible = str(
            row.get("DIVISIBLE") or ""
        ).strip()

        try:
            pack = max(
                1,
                int(
                    float(
                        divisible.replace(",", ".")
                    )
                ),
            )
        except Exception:
            pack = 1

        for category in categories:
            value = str(
                row.get(category) or ""
            ).strip().lower()

            if value in {
                "✓",
                "x",
                "1",
                "true",
                "si",
                "sí",
                "yes",
            }:
                records.append(
                    {
                        "sku": sku,
                        "category": category.lower(),
                        "pack_units": pack,
                    }
                )
                break

    return pd.DataFrame(records)


def get_file_id_from_url(url: str) -> str:
    match = re.search(
        r"(?:/d/|id=)([\w-]+)",
        url or "",
    )

    return match.group(1) if match else ""


def public_drive_download(file_id: str) -> bytes:
    response = requests.get(
        "https://drive.google.com/uc",
        params={
            "export": "download",
            "id": file_id,
        },
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=35,
    )

    response.raise_for_status()

    return response.content


def public_google_sheet_export(file_id: str) -> bytes:
    response = requests.get(
        (
            "https://docs.google.com/"
            f"spreadsheets/d/{file_id}/export"
        ),
        params={
            "format": "xlsx",
        },
        timeout=35,
    )

    response.raise_for_status()

    return response.content


def public_drive_metadata(file_id: str) -> dict:
    """
    Obtiene una versión fiable de un archivo público de Drive.

    Google Drive puede devolver un encabezado Last-Modified antiguo
    aunque el contenido del archivo haya cambiado. Por eso se descarga
    el contenido y se calcula su SHA-256.

    Esta función debe permanecer cubierta por el caché de metadatos de
    Streamlit para no descargar el archivo en cada interacción.
    """
    response = requests.get(
        "https://drive.google.com/uc",
        params={
            "export": "download",
            "id": file_id,
            # Evita reutilizar una respuesta pública cacheada.
            "_": int(
                datetime.now(
                    timezone.utc
                ).timestamp()
            ),
        },
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=35,
    )

    response.raise_for_status()

    content = response.content

    return {
        "id": file_id,
        "name": "GOLOSINERO.CSV",
        "sha256Checksum": hashlib.sha256(
            content
        ).hexdigest(),
        "Last-Modified": response.headers.get(
            "Last-Modified"
        ),
        "Content-Length": str(
            len(content)
        ),
        "checkedAt": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def public_sheet_metadata(file_id: str) -> dict:
    response = requests.get(
        (
            "https://docs.google.com/"
            f"spreadsheets/d/{file_id}/export"
        ),
        params={
            "format": "xlsx",
        },
        stream=True,
        timeout=20,
    )

    response.raise_for_status()

    return {
        "id": file_id,
        "Last-Modified": response.headers.get(
            "Last-Modified"
        ),
        "Content-Length": response.headers.get(
            "Content-Length"
        ),
        "etag": response.headers.get(
            "ETag"
        ),
    }


def drive_service(secrets):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = dict(secrets)

    credentials = (
        service_account
        .Credentials
        .from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/"
                "auth/drive.readonly"
            ],
        )
    )

    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def api_metadata(
    service,
    file_id: str,
) -> dict:
    return (
        service.files()
        .get(
            fileId=file_id,
            fields=(
                "id,name,mimeType,size,"
                "modifiedTime,md5Checksum"
            ),
        )
        .execute()
    )


def api_download(
    service,
    file_id: str,
) -> bytes:
    from googleapiclient.http import (
        MediaIoBaseDownload,
    )

    request = service.files().get_media(
        fileId=file_id
    )

    file_handle = io.BytesIO()

    downloader = MediaIoBaseDownload(
        file_handle,
        request,
    )

    done = False

    while not done:
        _, done = downloader.next_chunk()

    return file_handle.getvalue()


def api_export_xlsx(
    service,
    file_id: str,
) -> bytes:
    from googleapiclient.http import (
        MediaIoBaseDownload,
    )

    request = service.files().export_media(
        fileId=file_id,
        mimeType=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
    )

    file_handle = io.BytesIO()

    downloader = MediaIoBaseDownload(
        file_handle,
        request,
    )

    done = False

    while not done:
        _, done = downloader.next_chunk()

    return file_handle.getvalue()


def load_json_bytes(content: bytes) -> dict:
    return json.loads(
        content.decode("utf-8-sig")
    )