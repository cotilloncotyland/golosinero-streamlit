# Golosinero Cotyland · Streamlit MVP

Primera migración del generador validado en Apps Script.

## Qué incluye
- Parser seguro para `GOLOSINERO.CSV`, línea por línea y separado por `;`.
- Lectura del CSV desde Google Drive con caché basada en `modifiedTime`.
- Política de vigencia distinta durante horario abierto y fuera de horario.
- Imágenes por `imagenes_index.json` de Drive o fallback incluido.
- Generación de combos, reparto editable, favoritos e historial.
- PDF en memoria, sin guardar nada en Drive.
- Mensaje final para enviar el PDF por WhatsApp manualmente.

## Regla de actualización
Si el archivo conserva el mismo ID y cambia su contenido, Drive cambia `modifiedTime`. La app consulta metadatos cada 60 segundos y recarga el CSV solo cuando cambia la versión.

Si la PC está apagada sábado/domingo, no se bloquea de inmediato: `max_age_hours_closed` define la tolerancia fuera de horario. Durante horario abierto usa `max_age_minutes_open`.

## Probar local
```bash
pip install -r requirements.txt
streamlit run app.py
```

Sin secretos intenta leer el CSV público por ID y usa los archivos fallback si falla.

## Subir a GitHub
1. Crear repositorio privado.
2. Subir todos los archivos, excepto `.streamlit/secrets.toml`.
3. En Streamlit Community Cloud, crear app desde `app.py`.
4. Pegar el contenido de `.streamlit/secrets.toml.example` en **App settings > Secrets** y completar credenciales.

## Drive privado
Crear una cuenta de servicio, compartir el CSV y el archivo `imagenes_index.json` con el correo `client_email` como lector, y pegar la credencial en Streamlit Secrets.

## Reglas desde Google Sheets
Configurar la planilla mediante `drive.rules_file_id`. La app la exporta como XLSX, mantiene el resultado en caché durante 15 minutos y usa `data/reglas_combos.xlsx` como fallback si Drive falla. La interfaz muestra siempre la fuente y la cantidad de reglas activas.

Si se usa una cuenta de servicio, compartir también la Google Sheet con el correo `client_email` como lector.

## Importante
Esta versión es un MVP para comparar comportamiento y velocidad. Antes de abrirla al público hay que validar nuevamente cobertura, surtido y cantidades con una batería de pruebas contra la versión Apps Script.
