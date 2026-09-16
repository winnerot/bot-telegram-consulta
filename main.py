import asyncio
from concurrent.futures import ThreadPoolExecutor
import http.server
import logging
import os
import re
import socketserver
import threading
import urllib3

from bs4 import BeautifulSoup
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Desactivar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configurar logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuración de hilos para consultas
executor = ThreadPoolExecutor(max_workers=4)

# ==============================================================================
# TOKEN DE TU BOT DE TELEGRAM
# ==============================================================================
TOKEN = "8828583094:AAHRdTseIjTnNJgjfmU_hi-yPqL9uhFRm-A"


# ==============================================================================
# SERVIDOR HTTP PARA PLAN FREE EN RENDER
# ==============================================================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))

    class SimpleHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot activo 24/7")

        def log_message(self, format, *args):
            return

    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("0.0.0.0", port), SimpleHandler) as server:
            server.serve_forever()
    except Exception as e:
        logger.error(f"Error en servidor HTTP auxiliar: {e}")


# ==============================================================================
# CONSULTA SENIAT
# ==============================================================================
def consultar_seniat(cedula: str) -> str:
    url = f"http://contribuyente.seniat.gob.ve/relacionesrif/inicioConsulta.do?personalidad=1&ci={cedula}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=5, verify=False)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            texto_total = soup.get_text(separator=" ", strip=True)

            if any(
                kw in texto_total.lower()
                for kw in ["no existe", "no se encuentra", "error", "invalida"]
            ):
                return "❌ La cédula no se encuentra registrada en el sistema del SENIAT (EMPRESAS)."

            nombre_persona = "No especificado"
            tds = soup.find_all("td")
            for td in tds:
                texto_td = td.get_text(strip=True)
                if "NOMBRE:" in texto_td.upper() or "NOMBRE" in texto_td.upper():
                    cleaned = re.sub(
                        r"nombre\s*:\s*", "", texto_td, flags=re.IGNORECASE
                    ).strip()
                    if cleaned:
                        nombre_persona = cleaned
                        break

            relaciones = []
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    cols_text = [c.get_text(strip=True) for c in cols]

                    if len(cols_text) >= 3:
                        primer_col = cols_text[0].upper()
                        if any(
                            primer_col.startswith(pref)
                            for pref in ["V", "J", "E", "G"]
                        ) or ("-" in primer_col):
                            relaciones.append(
                                {
                                    "rif": cols_text[0],
                                    "nombre": cols_text[1]
                                    if len(cols_text) > 1
                                    else "N/A",
                                    "tipo": cols_text[2]
                                    if len(cols_text) > 2
                                    else "N/A",
                                    "fecha": cols_text[3]
                                    if len(cols_text) > 3
                                    else "N/A",
                                }
                            )

            resultado = f"✅ **Resultados SENIAT (EMPRESA):**\n\n"
            resultado += f"👤 **Nombre:** {nombre_persona}\n\n"

            if relaciones:
                resultado += f"📋 **Contribuyentes Relacionados:**\n"
                for rel in relaciones:
                    resultado += f"  • **RIF:** `{rel['rif']}`\n"
                    resultado += f"    **Nombre:** {rel['nombre']}\n"
                    resultado += f"    **Relación:** {rel['tipo']}\n"
                    resultado += f"    **Fecha Inicio:** {rel['fecha']}\n\n"
            else:
                resultado += "📌 *No se encontraron empresas o relaciones asociadas a esta cédula.*\n"

            return resultado.strip()
        else:
            return f"❌ Error del servidor SENIAT: {response.status_code}"

    except requests.exceptions.Timeout:
        return "⚠️ SENIAT: Tiempo de espera agotado (Servidor caído o IP bloqueada)."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error SENIAT: {e}")
        return "❌ SENIAT: Error de conexión."


# ==============================================================================
# CONSULTA IVSS
# ==============================================================================
def consultar_ivss(cedula: str) -> str:
    url_base = "http://www.ivss.gob.ve:28083/CuentaIndividualIntranet/"
    url_accion = (
        "http://www.ivss.gob.ve:28083/CuentaIndividualIntranet/CtaIndividualCTRL"
    )

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": url_base,
            "Origin": "http://www.ivss.gob.ve:28083",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        session = requests.Session()
        session.get(url_base, headers=headers, timeout=5, verify=False)

        payload = {
            "Accion": "",
            "Accion1": "",
            "nacionalidad_aseg": "V",
            "cedula_aseg": cedula,
            "consultar": "Buscar",
        }

        response = session.post(
            url_accion, data=payload, headers=headers, timeout=5, verify=False
        )

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            texto_total = soup.get_text(separator=" ", strip=True)

            if any(
                kw in texto_total.lower()
                for kw in ["no existe", "no registrado", "error"]
            ):
                return f"⚠️ La cédula `{cedula}` no se encuentra registrada en el sistema del IVSS."

            empresas = []
            fechas_ingreso = []
            estatus_list = []

            for tr in soup.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                for i, td in enumerate(tds):
                    txt = td.get_text(strip=True).upper()

                    if "EMPRESA" in txt or "RAZON SOCIAL" in txt:
                        if i + 1 < len(tds):
                            val = tds[i + 1].get_text(strip=True)
                            if val and val != ":" and val not in empresas:
                                empresas.append(val)

                    if "FECHA" in txt and "INGRESO" in txt:
                        if i + 1 < len(tds):
                            val = tds[i + 1].get_text(strip=True)
                            if val and val != ":" and val not in fechas_ingreso:
                                fechas_ingreso.append(val)

                    if "ESTATUS" in txt or "ESTADO" in txt:
                        if i + 1 < len(tds):
                            val = tds[i + 1].get_text(strip=True)
                            if val and val != ":" and val not in estatus_list:
                                estatus_list.append(val)

            resultado_msj = f"✅ **Resultados IVSS SEGURO:**\n\n"

            if empresas or fechas_ingreso or estatus_list:
                if empresas:
                    resultado_msj += (
                        f"**Empresa(s):**\n"
                        + "\n".join([f"- {e}" for e in empresas])
                        + "\n\n"
                    )
                if fechas_ingreso:
                    resultado_msj += (
                        f"**Fecha(s) de Ingreso:**\n"
                        + "\n".join([f"- {f}" for f in fechas_ingreso])
                        + "\n\n"
                    )
                if estatus_list:
                    resultado_msj += (
                        f"**Estatus:**\n"
                        + "\n".join([f"- {es}" for es in estatus_list])
                        + "\n"
                    )

                return resultado_msj.strip()
            else:
                return f"Resultados IVSS: ⚠️ NO ASEGURADO"

        else:
            return f"❌ Error del servidor IVSS: {response.status_code}"

    except requests.exceptions.Timeout:
        return "⚠️ IVSS: Tiempo de espera agotado (Servidor caído, puerto 28083 bloqueado o IP de Render bloqueada)."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error IVSS: {e}")
        return "❌ IVSS: Error de conexión."


# ==============================================================================
# PROCESADOR UNIFICADO
# ==============================================================================
def procesar_todas_las_consultas(cedula: str) -> str:
    resultado_seniat = consultar_seniat(cedula)
    resultado_ivss = consultar_ivss(cedula)

    reporte = "📋 **REPORTE CONSOLIDADO DE CONSULTAS**\n"
    reporte += f"🆔 **Cédula analizada:** `{cedula}`\n"
    reporte += f"──────────────────\n"
    reporte += f"{resultado_seniat}\n"
    reporte += f"──────────────────\n"
    reporte += f"{resultado_ivss}\n"
    reporte += f"──────────────────\n"

    return reporte


# ==============================================================================
# MANEJADORES DE TELEGRAM
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"¡Hola {user_name}! 🤖\n"
        "BOT By: Marquez.\n\n"
        "Envíame un número de **Cédula de Identidad** (ej: `12345678`) para consultar."
    )


async def manejar_cedula(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text.strip()

    if (
        not texto_usuario.isdigit()
        or len(texto_usuario) < 6
        or len(texto_usuario) > 9
    ):
        await update.message.reply_text(
            "⚠️ Por favor, ingresa un número de cédula válido (solo dígitos, sin puntos)."
        )
        return

    mensaje_espera = await update.message.reply_text(
        f"🔍 Consultando la cédula **{texto_usuario}**, por favor espera..."
    )

    loop = asyncio.get_running_loop()
    try:
        resultado = await loop.run_in_executor(
            executor, procesar_todas_las_consultas, texto_usuario
        )
    except Exception as err:
        logger.error(f"Error en ejecución: {err}")
        resultado = "❌ Ocurrió un error interno procesando la consulta."

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=mensaje_espera.message_id,
        text=resultado,
        parse_mode="Markdown",
    )


# ==============================================================================
# EJECUCIÓN PRINCIPAL
# ==============================================================================
def main():
    # Iniciar servidor web secundario en segundo plano para Render Free
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_cedula)
    )

    print("🚀 Bot iniciado y listo para recibir consultas...")
    app.run_polling()


if __name__ == "__main__":
    main()
