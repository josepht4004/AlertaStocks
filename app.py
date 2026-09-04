"""
Monitor de Stock - Xbox Series X (cadenamulti.co)
==================================================
Diseñado para correr 24/7 en Hugging Face Spaces (o localmente).

Funcionalidades:
  1. Monitoreo automático cada 20 minutos en segundo plano (avisa si hay stock).
  2. Respuesta interactiva en Telegram: si envías 'status', '/status' o cualquier
     mensaje, realiza una consulta en tiempo real y responde con el estado.
  3. Mini servidor web / interfaz para que Hugging Face mantenga el Space activo (Running).

Variables de entorno requeridas:
  - TELEGRAM_TOKEN
  - TELEGRAM_CHAT_ID
  - PRODUCT_URL (opcional)
  - CHECK_INTERVAL_MINUTES (opcional, por defecto 20)
"""

import os
import sys
import time
import threading
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import telebot

# ============================================================
# CONFIGURACIÓN
# ============================================================

PRODUCT_URL = os.environ.get(
    "PRODUCT_URL",
    "https://cadenamulti.co/products/xbox-series-x-1tb-ssd-1-control",
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "20"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TEXTO_BOTON_COMPRA = "añadir a la cesta"

# Estado global para consulta del servidor web
ultimo_estado = {
    "hora": "Aún no ejecutado",
    "en_stock": False,
    "mensaje": "Iniciando monitoreo..."
}


# ============================================================
# LÓGICA DE DETECCIÓN DE STOCK
# ============================================================

def hay_stock_disponible(html: str) -> bool:
    """
    Determina si el producto tiene stock:
    1) Prioridad: metaetiqueta product:availability
    2) Respaldo: presencia del botón 'Añadir a la cesta'
    """
    soup = BeautifulSoup(html, "html.parser")

    meta_disponibilidad = soup.find("meta", attrs={"property": "product:availability"})
    if meta_disponibilidad and meta_disponibilidad.get("content"):
        valor = meta_disponibilidad["content"].strip().lower()
        print(f"[{datetime.now()}] Metaetiqueta product:availability = '{valor}'")
        return valor == "in stock"

    print(f"[{datetime.now()}] Metaetiqueta no encontrada, usando respaldo de texto.")
    texto_pagina = soup.get_text(separator=" ", strip=True).lower()
    return TEXTO_BOTON_COMPRA in texto_pagina


def consultar_stock_actual() -> tuple[bool, str]:
    """
    Realiza la petición web y devuelve (hay_stock, mensaje_formateado).
    """
    global ultimo_estado
    ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        respuesta = requests.get(PRODUCT_URL, headers=HEADERS, timeout=15)
        respuesta.raise_for_status()
        en_stock = hay_stock_disponible(respuesta.text)

        ultimo_estado["hora"] = ahora_str
        ultimo_estado["en_stock"] = en_stock

        if en_stock:
            msg = (
                "🚨 <b>¡STOCK DISPONIBLE!</b> 🚨\n\n"
                "La <b>Xbox Series X</b> parece estar disponible ahora mismo.\n\n"
                f"🕒 <i>Consultado: {ahora_str}</i>\n"
                f"👉 <a href='{PRODUCT_URL}'>Ir a la tienda</a>"
            )
            ultimo_estado["mensaje"] = "¡En stock!"
        else:
            msg = (
                "🔴 <b>Sin stock disponible</b>\n\n"
                "Se revisó la tienda y el producto continúa <b>agotado</b>.\n\n"
                f"🕒 <i>Consultado: {ahora_str}</i>\n"
                f"👉 <a href='{PRODUCT_URL}'>Ver enlace del producto</a>"
            )
            ultimo_estado["mensaje"] = "Sin stock"

        return en_stock, msg

    except requests.exceptions.RequestException as e:
        error_msg = (
            "⚠️ <b>Error al consultar la tienda</b>\n\n"
            f"Ocurrió un problema de conexión al revisar el producto: <code>{e}</code>\n\n"
            f"🕒 <i>Intento: {ahora_str}</i>"
        )
        ultimo_estado["hora"] = ahora_str
        ultimo_estado["mensaje"] = f"Error: {e}"
        print(f"[{ahora_str}] ERROR en consulta: {e}")
        return False, error_msg


# ============================================================
# BOT DE TELEGRAM & COMANDOS
# ============================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None


def notificar_telegram(mensaje: str, chat_id: str = None) -> None:
    """Envía un mensaje formateado en HTML al chat_id (o al configurado por defecto)."""
    destino = chat_id or TELEGRAM_CHAT_ID
    if not bot or not destino:
        print(f"[{datetime.now()}] Telegram no configurado correctamente.")
        return

    try:
        bot.send_message(
            chat_id=destino,
            text=mensaje,
            parse_mode="HTML",
            disable_web_page_preview=False
        )
        print(f"[{datetime.now()}] Mensaje enviado a Telegram ({destino}).")
    except Exception as e:
        print(f"[{datetime.now()}] Error enviando a Telegram: {e}")


if bot:
    @bot.message_handler(commands=["start", "help"])
    def cmd_start(message):
        texto = (
            "🤖 <b>Bot de Monitoreo de Stock</b>\n\n"
            "Comandos disponibles:\n"
            "• <code>status</code> o <code>/status</code>: Consulta el stock en tiempo real.\n"
            "• <code>/ping</code>: Comprueba si el bot está en línea.\n\n"
            f"⏱ <i>Monitoreo automático activo cada {CHECK_INTERVAL_MINUTES} minutos.</i>"
        )
        bot.reply_to(message, texto, parse_mode="HTML")

    @bot.message_handler(commands=["ping"])
    def cmd_ping(message):
        bot.reply_to(message, "🏓 ¡Pong! El bot está activo y monitoreando.", parse_mode="HTML")

    @bot.message_handler(commands=["status"])
    def cmd_status(message):
        bot.send_chat_action(message.chat.id, "typing")
        _, msg = consultar_stock_actual()
        bot.reply_to(message, msg, parse_mode="HTML")

    @bot.message_handler(func=lambda msg: True)
    def handle_text(message):
        texto_recibido = (message.text or "").strip().lower()
        if "status" in texto_recibido or "estado" in texto_recibido or "stock" in texto_recibido:
            bot.send_chat_action(message.chat.id, "typing")
            _, msg = consultar_stock_actual()
            bot.reply_to(message, msg, parse_mode="HTML")
        else:
            bot.reply_to(
                message,
                "Escribe <b>status</b> para consultar el stock en tiempo real.",
                parse_mode="HTML"
            )


# ============================================================
# TAREA EN SEGUNDO PLANO (CADA 20 MINUTOS)
# ============================================================

def bucle_monitoreo_automatico():
    """Revisa el stock periódicamente y avisa si hay disponibilidad."""
    print(f"[{datetime.now()}] Iniciando bucle automático cada {CHECK_INTERVAL_MINUTES} minutos...")

    # Mensaje inicial al encender
    if TELEGRAM_CHAT_ID:
        notificar_telegram(
            f"🚀 <b>Bot de monitoreo iniciado</b>\n"
            f"Revisando stock cada {CHECK_INTERVAL_MINUTES} minutos.\n"
            "Envía <code>status</code> en cualquier momento para consultar."
        )

    while True:
        try:
            print(f"[{datetime.now()}] [Auto-check] Verificando stock...")
            en_stock, msg = consultar_stock_actual()

            # Solo enviamos alerta si SÍ hay stock
            if en_stock:
                print(f"[{datetime.now()}] ¡Stock encontrado! Enviando alerta...")
                notificar_telegram(msg)
            else:
                print(f"[{datetime.now()}] Sin stock. Próxima revisión en {CHECK_INTERVAL_MINUTES} min.")

        except Exception as e:
            print(f"[{datetime.now()}] Excepción en bucle de monitoreo: {e}")

        time.sleep(CHECK_INTERVAL_MINUTES * 60)


# ============================================================
# MINI SERVIDOR WEB PARA HUGGING FACE SPACES (PUERTO 7860)
# ============================================================

def iniciar_servidor_web():
    """Servidor HTTP simple para que Hugging Face detecte la app como 'Running' en el puerto 7860."""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            
            estado_color = "#28a745" if ultimo_estado["en_stock"] else "#dc3545"
            estado_texto = "¡HAY STOCK!" if ultimo_estado["en_stock"] else "Sin Stock"

            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Monitor Stock Xbox</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 2rem; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); max-width: 480px; width: 90%; text-align: center; }}
        .badge {{ display: inline-block; padding: 0.5rem 1rem; border-radius: 9999px; background: {estado_color}; color: white; font-weight: bold; margin: 1rem 0; font-size: 1.1rem; }}
        .info {{ color: #94a3b8; font-size: 0.9rem; margin-top: 1rem; line-height: 1.6; }}
        a {{ color: #38bdf8; text-decoration: none; font-weight: 500; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🎮 Monitor de Stock Xbox</h2>
        <div class="badge">{estado_texto}</div>
        <p><strong>Último chequeo:</strong> {ultimo_estado['hora']}</p>
        <p><strong>Estado:</strong> {ultimo_estado['mensaje']}</p>
        <div class="info">
            <p>⏱ Frecuencia automática: Cada {CHECK_INTERVAL_MINUTES} minutos</p>
            <p>🤖 Bot de Telegram: <strong>Activo y escuchando comandos</strong></p>
            <p><a href="{PRODUCT_URL}" target="_blank">Ver producto en la tienda &rarr;</a></p>
        </div>
    </div>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        def log_message(self, format, *args):
            return  # Silenciar logs http para no saturar consola

    puerto = int(os.environ.get("PORT", 7860))
    servidor = HTTPServer(("0.0.0.0", puerto), StatusHandler)
    print(f"[{datetime.now()}] Servidor web listo en http://0.0.0.0:{puerto}")
    servidor.serve_forever()


# ============================================================
# ENTRADA PRINCIPAL
# ============================================================

def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: La variable de entorno TELEGRAM_TOKEN no está configurada.")
        sys.exit(1)

    # 1. Hilo 1: Monitoreo periódico cada 20 min
    t_monitor = threading.Thread(target=bucle_monitoreo_automatico, daemon=True)
    t_monitor.start()

    # 2. Hilo 2: Servidor web en puerto 7860 (para Hugging Face)
    t_web = threading.Thread(target=iniciar_servidor_web, daemon=True)
    t_web.start()

    # 3. Hilo Principal: Escuchar mensajes de Telegram (Long Polling)
    print(f"[{datetime.now()}] Bot de Telegram escuchando mensajes...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"[{datetime.now()}] Error en polling de Telegram: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
