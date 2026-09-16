import logging
import re
import requests
import io
import urllib3
import pymysql 
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Desactivar advertencias de SSL por el uso de verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configurar logs para ver errores en la consola
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token que te da BotFather en Telegram
TOKEN = "8828583094:AAHRdTseIjTnNJgjfmU_hi-yPqL9uhFRm-A"

# CONFIGURACIÓN DE MARIADB
# DB_CONFIG = {
    # 'host': 'localhost',
    # 'user': 'root',
    # 'password': '6595657', # Debe ser la misma que pusiste en el comando SQL (o '' si la dejaste vacía)
    # 'database': 'mi_gran_base',   # El nombre de tu base de datos real
    # 'charset': 'utf8mb4',
    # 'cursorclass': pymysql.cursors.DictCursor
# }
# ----------------------------------------- NUEVO DEF: GUARDAS DATOS EN (MARIADB) ---------------------------------
# def guardar_o_actualizar_datos(cedula: str, nombre: str = None, telefono: str = None, empresas: str = None):
    # try:
        # conexion = pymysql.connect(**DB_CONFIG)
        # with conexion.cursor() as cursor:
            # Primero verificamos si ya existe el registro para no sobrescribir datos buenos con nulos
            # cursor.execute("SELECT nombre, telefono, empresas FROM contactos WHERE cedula = %s", (cedula,))
            # existente = cursor.fetchone()
            
            # if existente:
                # Mantenemos los datos viejos si los nuevos vienen vacíos o como "No especificado"
                # nombre_final = nombre if nombre and nombre != "No especificado" else existente.get('nombre')
                # telefono_final = telefono if telefono else existente.get('telefono')
                # empresas_final = empresas if empresas else existente.get('empresas')
                
                # sql = """
                    # UPDATE contactos 
                    # SET nombre = %s, telefono = %s, empresas = %s 
                    # WHERE cedula = %s
                # """
                # cursor.execute(sql, (nombre_final, telefono_final, empresas_final, cedula))
            # else:
                # Si no existe, lo creamos de cero
                # sql = """
                    # INSERT INTO contactos (cedula, nombre, telefono, empresas) 
                    # VALUES (%s, %s, %s, %s)
                # """
                # cursor.execute(sql, (cedula, nombre, telefono, empresas))
                
            # conexion.commit()
        # conexion.close()
    # except Exception as e:
        # logger.error(f"Error al guardar automáticamente en MariaDB: {e}")
        
        


# ----------------------------------------- NUEVO DEF: TELEFONOS (MARIADB) ---------------------------------
def consultar_telefono(cedula: str) -> str:
    try:
        # Conectar a MariaDB
        conexion = pymysql.connect(**DB_CONFIG)
        with conexion.cursor() as cursor:
            # Consulta adaptada a tu tabla (asumiendo que la tabla se llama 'contactos'
            # y tiene las columnas 'cedula' y 'telefono')
            sql = "SELECT telefono FROM datos_importados WHERE cedula = %s"
            cursor.execute(sql, (cedula,))
            resultado = cursor.fetchone()
            
        conexion.close()
        
        if resultado and resultado.get('telefono'):
            return f"📞 **Teléfono asociado:** `{resultado['telefono']}`"
        else:
            return "📱 *No se encontró número telefónico registrado para esta cédula.*"
            
    except Exception as e:
        logger.error(f"Error en la base de datos MariaDB: {e}")
        return "❌ Error al consultar la base de datos de teléfonos."

# ----------------------------------------- DEF SENIAT ---------------------------------
def consultar_seniat(cedula: str) -> str:
    url = f"http://contribuyente.seniat.gob.ve/relacionesrif/inicioConsulta.do?personalidad=1&ci={cedula}"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=15, verify=False)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            texto_total = soup.get_text(separator=" ", strip=True)
            
            if "no existe" in texto_total.lower() or "no se encuentra" in texto_total.lower() or "error" in texto_total.lower() or "invalida" in texto_total.lower():
                return "❌ La cédula no se encuentra registrada en el sistema del SENIAT(EMPRESAS)."

            nombre_persona = "No especificado"
            tds = soup.find_all('td')
            for td in tds:
                texto_td = td.get_text(strip=True)
                if "NOMBRE:" in texto_td.upper() or "NOMBRE" in texto_td.upper():
                    cleaned = re.sub(r'nombre\s*:\s*', '', texto_td, flags=re.IGNORECASE).strip()
                    if cleaned:
                        nombre_persona = cleaned
                        break

            relaciones = []
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                for row in rows:
                    cols = row.find_all(['td', 'th'])
                    cols_text = [c.get_text(strip=True) for c in cols]
                    
                    if len(cols_text) >= 3:
                        primer_col = cols_text[0].upper()
                        if any(primer_col.startswith(pref) for pref in ["V", "J", "E", "G"]) or "-" in primer_col:
                            relaciones.append({
                                "rif": cols_text[0],
                                "nombre": cols_text[1] if len(cols_text) > 1 else "N/A",
                                "tipo": cols_text[2] if len(cols_text) > 2 else "N/A",
                                "fecha": cols_text[3] if len(cols_text) > 3 else "N/A"
                            })

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

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión SENIAT: {e}")
        return "❌ Error de conexión con el servidor del SENIAT."
       
# ----------------------------------------- DEF IVSS ---------------------------------
def consultar_ivss(cedula: str) -> str:
    url_base = "http://www.ivss.gob.ve:28083/CuentaIndividualIntranet/"
    url_accion = "http://www.ivss.gob.ve:28083/CuentaIndividualIntranet/CtaIndividualCTRL"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": url_base,
            "Origin": "http://www.ivss.gob.ve:28083",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        session = requests.Session()
        session.get(url_base, headers=headers, timeout=15, verify=False)
        
        payload = {
            "Accion": "",
            "Accion1": "",
            "nacionalidad_aseg": "V",
            "cedula_aseg": cedula,
            "consultar": "Buscar"
        }

        response = session.post(url_accion, data=payload, headers=headers, timeout=15, verify=False)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            texto_total = soup.get_text(separator=" ", strip=True)
            if "no existe" in texto_total.lower() or "no registrado" in texto_total.lower() or "error" in texto_total.lower():
                return f"⚠️ La cédula `{cedula}` no se encuentra registrada en el sistema del IVSS."

            empresas = []
            fechas_ingreso = []
            estatus_list = []

            for tr in soup.find_all('tr'):
                tds = tr.find_all(['td', 'th'])
                for i, td in enumerate(tds):
                    txt = td.get_text(strip=True).upper()
                    
                    if "EMPRESA" in txt or "RAZON SOCIAL" in txt:
                        if i + 1 < len(tds):
                            val = tds[i+1].get_text(strip=True)
                            if val and val != ":" and val not in empresas:
                                empresas.append(val)
                    
                    if "FECHA" in txt and "INGRESO" in txt:
                        if i + 1 < len(tds):
                            val = tds[i+1].get_text(strip=True)
                            if val and val != ":" and val not in fechas_ingreso:
                                fechas_ingreso.append(val)
                             
                    if "ESTATUS" in txt or "ESTADO" in txt:
                        if i + 1 < len(tds):
                            val = tds[i+1].get_text(strip=True)
                            if val and val != ":" and val not in estatus_list:
                                estatus_list.append(val)

            resultado_msj = f"✅ **Resultados IVSS SEGURO:**\n\n"
            
            if empresas or fechas_ingreso or estatus_list:
                if empresas:
                    resultado_msj += f"**Empresa(s):**\n" + "\n".join([f"- {e}" for e in empresas]) + "\n\n"
                if fechas_ingreso:
                    resultado_msj += f"**Fecha(s) de Ingreso:**\n" + "\n".join([f"- {f}" for f in fechas_ingreso]) + "\n\n"
                if estatus_list:
                    resultado_msj += f"**Estatus:**\n" + "\n".join([f"- {es}" for es in estatus_list]) + "\n"
                 
                return resultado_msj
            else:
                return f"Resultados IVSS: ⚠️ NO ASEGURADO"

        else:
            return f"❌ Error del servidor IVSS: {response.status_code}"

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        return "❌ Error de conexión con el servidor del IVSS."
       
# ----------------------------------------------------- COMANDOS Y MANEJADORES -----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"¡Hola {user_name}! 🤖\n"
        "BOT By: Marquez.\n\n"
        "Envíame un número de **Cédula de Identidad** (ej: `12345678`) para consultar."
    )

async def manejar_cedula(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text.strip()
    
    if not texto_usuario.isdigit() or len(texto_usuario) < 6 or len(texto_usuario) > 9:
        await update.message.reply_text("⚠️ Por favor, ingresa un número de cédula válido (solo dígitos, sin puntos).")
        return

    mensaje_espera = await update.message.reply_text(f"🔍 Consultando la cédula **{texto_usuario}**, por favor espera...")

    resultado = procesar_todas_las_consultas(texto_usuario)

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=mensaje_espera.message_id,
        text=resultado,
        parse_mode="Markdown"
    )

def procesar_todas_las_consultas(cedula: str) -> str:
    # 1. Consultamos los servicios habituales
    resultado_ivss = consultar_ivss(cedula)
    resultado_seniat = consultar_seniat(cedula)
    resultado_telefono = consultar_telefono(cedula) # Busca en tu BD de teléfonos
    
    # 2. Extraemos el nombre limpio del texto que devolvió el SENIAT para guardarlo
    nombre_extraido = "No especificado"
    if "👤 **Nombre:**" in resultado_seniat:
        try:
            lineas = resultado_seniat.split("\n")
            for linea in lineas:
                if "👤 **Nombre:**" in linea:
                    nombre_extraido = linea.replace("👤 **Nombre:**", "").strip()
        except Exception:
            pass

    # 3. Extraemos las empresas del IVSS si las hay para guardarlas
    empresas_extraidas = ""
    if "**Empresa(s):**" in resultado_ivss:
        try:
            partes = resultado_ivss.split("**Empresa(s):**")
            if len(partes) > 1:
                empresas_extraidas = partes[1].split("──────────────────")[0].strip()
        except Exception:
            pass

    # 4. 🚀 GUARDADO AUTOMÁTICO EN LA BASE DE DATOS
    # Obtenemos el teléfono actual de la BD si lo hubiera
    # telefono_actual = None
    # try:
        # conexion = pymysql.connect(**DB_CONFIG)
        # with conexion.cursor() as cursor:
            # cursor.execute("SELECT telefono FROM contactos WHERE cedula = %s", (cedula,))
            # res_tel = cursor.fetchone()
            # if res_tel and res_tel.get('telefono'):
                # telefono_actual = res_tel.get('telefono')
        # conexion.close()
    # except Exception:
        # pass

    # Ejecutamos la inserción/actualización inteligente
    # guardar_o_actualizar_datos(
        # cedula=cedula, 
        # nombre=nombre_extraido, 
        # telefono=telefono_actual, 
        # empresas=empresas_extraidas
    # )

    # 5. Armamos el reporte final para Telegram
    reporte = "📋 **REPORTE CONSOLIDADO DE CONSULTAS**\n"
    reporte += f"🆔 **Cédula analizada:** `{cedula}`\n"
    reporte += f"──────────────────\n"
    reporte += f"{resultado_seniat}\n"
    reporte += f"──────────────────\n"
    reporte += f"{resultado_ivss}\n"
    reporte += f"──────────────────\n"

    
    return reporte

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_cedula))

    print("🚀 Bot iniciado y listo para recibir cédulas con soporte MariaDB...")
    app.run_polling()

if __name__ == "__main__":
    main()
