"""
Monitor de stock - Xbox Series X (cadenamulti.co)
==================================================
Pensado para correr como job programado de GitHub Actions (o localmente).
Cada ejecución hace UNA sola consulta, evalúa el stock, y termina.
GitHub Actions se encarga de volver a llamarlo cada N minutos.

Método de detección (en orden de prioridad):
  1. Metaetiqueta <meta property="product:availability" content="in stock|out of stock">
     -> Es la señal más confiable: Shopify siempre la rellena de forma estándar.
  2. Respaldo: presencia del texto "Añadir a la cesta" en la página.

Variables de entorno requeridas (se configuran como GitHub Secrets, NO en el código):
  - TELEGRAM_TOKEN
  - TELEGRAM_CHAT_ID
  - PRODUCT_URL   (opcional, tiene un valor por defecto abajo)
  - DAILY_PING    ("true"/"false") -> la pone el workflow según qué cron disparó la corrida.
                   Si es "true", el bot manda un mensaje de estado SIEMPRE, aunque no haya stock.
                   Si es "false" (el caso normal cada 5 min), solo manda mensaje si SÍ hay stock.
"""

import os
import sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================

# URL del producto. Puede sobreescribirse con la variable de entorno PRODUCT_URL
PRODUCT_URL = os.environ.get(
    "PRODUCT_URL",
    "https://cadenamulti.co/products/xbox-series-x-1tb-ssd-1-control",
)

# Estos DOS los tomamos de GitHub Secrets, nunca hardcodeados aquí
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TEXTO_BOTON_COMPRA = "añadir a la cesta"  # respaldo por si la metaetiqueta falla

# ¿Esta corrida es el "ping diario"? Lo decide el workflow de GitHub Actions.
DAILY_PING = os.environ.get("DAILY_PING", "false").strip().lower() == "true"


# ============================================================
# LÓGICA
# ============================================================

def enviar_alerta_telegram(mensaje: str) -> None:
    """Envía un mensaje al chat de Telegram configurado."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en las variables de entorno.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
    }
    try:
        respuesta = requests.post(url, data=payload, timeout=10)
        respuesta.raise_for_status()
        print(f"[{datetime.now()}] Alerta enviada a Telegram correctamente.")
    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] ERROR al enviar alerta a Telegram: {e}")


def hay_stock_disponible(html: str) -> bool:
    """
    Determina si el producto tiene stock.

    1) Prioridad: metaetiqueta product:availability (estándar Shopify/OpenGraph)
    2) Respaldo: presencia del botón "Añadir a la cesta" en el texto de la página
    """
    soup = BeautifulSoup(html, "html.parser")

    meta_disponibilidad = soup.find("meta", attrs={"property": "product:availability"})
    if meta_disponibilidad and meta_disponibilidad.get("content"):
        valor = meta_disponibilidad["content"].strip().lower()
        print(f"[{datetime.now()}] Metaetiqueta product:availability = '{valor}'")
        return valor == "in stock"

    # Si por alguna razón la metaetiqueta no está, usamos el respaldo
    print(f"[{datetime.now()}] Metaetiqueta no encontrada, usando respaldo de texto.")
    texto_pagina = soup.get_text(separator=" ", strip=True).lower()
    return TEXTO_BOTON_COMPRA in texto_pagina


def revisar_stock() -> None:
    """Hace una consulta a la tienda y evalúa/alerta si hay stock.

    Comportamiento:
      - Corrida normal (cada 5 min, DAILY_PING=false): solo avisa si SÍ hay stock.
      - Corrida de ping diario (DAILY_PING=true): SIEMPRE manda un mensaje,
        confirmando que el bot sigue vivo y el estado actual del stock.
    """
    try:
        respuesta = requests.get(PRODUCT_URL, headers=HEADERS, timeout=15)
        respuesta.raise_for_status()

        stock_disponible = hay_stock_disponible(respuesta.text)

        if stock_disponible:
            mensaje = (
                "🚨 <b>¡STOCK DISPONIBLE!</b> 🚨\n"
                "La Xbox Series X parece estar disponible ahora mismo.\n\n"
                f"👉 {PRODUCT_URL}"
            )
            print(f"[{datetime.now()}] ¡Stock detectado! Enviando alerta...")
            enviar_alerta_telegram(mensaje)

        elif DAILY_PING:
            mensaje = (
                "🤖 <b>Ping diario</b>\n"
                "El bot de monitoreo sigue activo y funcionando correctamente.\n"
                "Hasta el momento, sigue <b>sin stock</b>.\n\n"
                f"👉 {PRODUCT_URL}"
            )
            print(f"[{datetime.now()}] Enviando ping diario (sin stock)...")
            enviar_alerta_telegram(mensaje)

        else:
            print(f"[{datetime.now()}] Sin stock todavía. (corrida silenciosa)")

    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] ERROR al consultar la página: {e}")

        # Si justo el día del ping diario la tienda falla, igual avisamos
        # que el bot está vivo, para que no pienses que se murió.
        if DAILY_PING:
            enviar_alerta_telegram(
                "🤖 <b>Ping diario</b>\n"
                "El bot sigue activo, pero hubo un error consultando la "
                "página en este intento. Se seguirá revisando cada 5 minutos."
            )

        # No relanzamos la excepción: si esta corrida falla (ej. la tienda
        # estuvo caída un segundo), simplemente no pasa nada y GitHub
        # Actions volverá a intentarlo en la siguiente corrida programada.
        sys.exit(0)  # salimos limpio, sin marcar el job como fallido


if __name__ == "__main__":
    revisar_stock()
