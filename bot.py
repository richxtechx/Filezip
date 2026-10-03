import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import pyzipper

# --- SERVIDOR WEB PARA RENDER (Health Check) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheck)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- LÓGICA DEL BOT DE TELEGRAM ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("❌ No se encontró la variable de entorno TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)
user_sessions = {}

# Límite Telegram: 50 MB (usamos 48 MB como límite seguro)
TELEGRAM_MAX_SIZE = 48 * 1024 * 1024  # 48 MB para margen de seguridad

def format_size(bytes_size):
    """Convierte bytes a formato legible (MB, GB, etc)"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"

def divide_files_by_size(files_list, max_size_per_zip):
    """
    Divide archivos en grupos asegurando que cada grupo
    no supere max_size_per_zip en tamaño acumulativo
    """
    groups = []
    current_group = []
    current_size = 0
    
    # Ordena por tamaño (más pequeños primero para mejor distribución)
    sorted_files = sorted(files_list, key=lambda x: x["size"])
    
    for file_item in sorted_files:
        file_size = file_item["size"]
        
        # Si el archivo individual es > max_size, error
        if file_size > max_size_per_zip:
            return None, f"❌ El archivo {file_item['name']} ({format_size(file_size)}) es demasiado grande. Máximo: {format_size(max_size_per_zip)}"
        
        # Si agregar este archivo supera el límite, crea un nuevo grupo
        if current_size + file_size > max_size_per_zip and current_group:
            groups.append(current_group)
            current_group = []
            current_size = 0
        
        current_group.append(file_item)
        current_size += file_size
    
    # Agrega el último grupo
    if current_group:
        groups.append(current_group)
    
    return groups, None

@bot.message_handler(commands=['start'])
def send_welcome(m):
    bot.reply_to(m, "🤖 ¡Bot multimedia seguro activo!\n\n1️⃣ Envía `/password <tu_clave>`\n2️⃣ Envía tus archivos (fotos, videos, documentos o notas circulares)\n3️⃣ Envía `/comprimir` para obtener tu ZIP protegido.", parse_mode="Markdown")

@bot.message_handler(commands=['password'])
def set_password(m):
    uid = m.from_user.id
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        return bot.reply_to(m, "❌ Indica la contraseña. Ejemplo: `/password mi_clave`", parse_mode="Markdown")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123", "state": "idle"}
    
    user_sessions[uid]["password"] = args[1]
    bot.reply_to(m, "🔒 Contraseña guardada correctamente.\n\n📥 *Ahora puedes enviar los archivos* que deseas comprimir (fotos, videos, documentos o notas circulares).", parse_mode="Markdown")

# --- MANEJO BLINDADO DE ARCHIVOS ---
@bot.message_handler(content_types=['document', 'photo', 'video', 'video_note'])
def handle_files(m):
    uid = m.from_user.id
    if uid not in user_sessions:
        user_sessions[uid] = {"files": [], "password": "DefaultPassword123", "state": "idle"}
    
    f_info = None
    original_name = None
    file_size = None
    
    if m.document:
        f_info = bot.get_file(m.document.file_id)
        original_name = m.document.file_name
        file_size = m.document.file_size
    elif m.photo:
        f_info = bot.get_file(m.photo[-1].file_id)
        original_name = f"foto_{m.photo[-1].file_unique_id}.jpg"
        file_size = m.photo[-1].file_size
    elif m.video:
        f_info = bot.get_file(m.video.file_id)
        original_name = m.video.file_name or f"video_{m.video.file_unique_id}.mp4"
        file_size = m.video.file_size
    elif m.video_note:
        f_info = bot.get_file(m.video_note.file_id)
        original_name = f"nota_circular_{m.video_note.file_unique_id}.mp4"
        file_size = m.video_note.file_size

    if f_info:
        if not original_name or not isinstance(original_name, str):
            original_name = f"archivo_{m.message_id}.bin"
            
        down = bot.download_file(f_info.file_path)
        path = f"temp_{uid}_{m.message_id}_{original_name}"
        
        with open(path, "wb") as f:
            f.write(down)
        
        actual_size = os.path.getsize(path)
        user_sessions[uid]["files"].append({"path": path, "name": original_name, "size": actual_size})
        
        size_display = format_size(actual_size) if file_size is None else format_size(file_size)
        bot.reply_to(m, f"✅ Archivo añadido: {original_name} ({size_display})\n\nCuando termines de enviar todos tus archivos, escribe /comprimir")

@bot.message_handler(commands=['listar'])
def list_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "📭 No hay archivos acumulados.")
    
    sess = user_sessions[uid]
    total_size = sum(f["size"] for f in sess["files"])
    
    # Calcula cuántos ZIPs se necesitan con la nueva lógica
    groups, error = divide_files_by_size(sess["files"], TELEGRAM_MAX_SIZE)
    num_zips = len(groups) if groups else 1
    
    msg = "📂 Archivos acumulados:\n\n"
    for i, file_item in enumerate(sess["files"], 1):
        msg += f"{i}. {file_item['name']} ({format_size(file_item['size'])})\n"
    
    msg += f"\nTamaño total: {format_size(total_size)}\n"
    msg += f"ZIPs necesarios: {num_zips}"
    bot.reply_to(m, msg)

@bot.message_handler(commands=['limpiar'])
def clear_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "📭 No hay archivos para limpiar.")
    
    sess = user_sessions[uid]
    for file_item in sess["files"]:
        if os.path.exists(file_item["path"]):
            os.remove(file_item["path"])
    sess["files"] = []
    bot.reply_to(m, "✅ Archivos limpios. Puedes comenzar de nuevo.")

@bot.message_handler(commands=['comprimir'])
def compress_files(m):
    uid = m.from_user.id
    if uid not in user_sessions or not user_sessions[uid]["files"]:
        return bot.reply_to(m, "⚠️ No hay archivos acumulados para comprimir. Envía algunos primero.")
    
    sess = user_sessions[uid]
    files_list = sess["files"]
    
    # Divide archivos por tamaño acumulativo
    groups, error = divide_files_by_size(files_list, TELEGRAM_MAX_SIZE)
    
    if error:
        return bot.reply_to(m, error)
    
    num_zips = len(groups)
    total_size = sum(f["size"] for f in files_list)
    
    # Marcar que estamos esperando el nombre del ZIP
    user_sessions[uid]["state"] = "waiting_for_zip_name"
    user_sessions[uid]["pending_compression"] = {
        "groups": groups,
        "password": sess["password"],
        "total_size": total_size,
        "num_zips": num_zips
    }
    
    if num_zips == 1:
        msg = f"📦 Se creará 1 ZIP ({format_size(total_size)})\n\n"
    else:
        msg = f"📦 Se crearán {num_zips} ZIPs de ~{format_size(TELEGRAM_MAX_SIZE)} cada uno\n\n"
    
    msg += "✍️ Escribe el nombre base para los ZIPs (sin .zip):\n\n"
    msg += "Ejemplo: `mis_archivos`\n\n"
    if num_zips > 1:
        msg += f"Se crearán: mis_archivos1.zip, mis_archivos2.zip, etc."
    else:
        msg += f"Se creará: mis_archivos.zip"
    
    bot.reply_to(m, msg)

@bot.message_handler(func=lambda m: user_sessions.get(m.from_user.id, {}).get("state") == "waiting_for_zip_name")
def get_zip_name(m):
    uid = m.from_user.id
    zip_base_name = m.text.strip()
    
    # Validar nombre
    if not zip_base_name or len(zip_base_name) > 50:
        return bot.reply_to(m, "❌ El nombre debe tener entre 1 y 50 caracteres.")
    
    if any(char in zip_base_name for char in ['/', '\\', '*', '?', '"', '<', '>', '|']):
        return bot.reply_to(m, "❌ El nombre contiene caracteres no permitidos.")
    
    sess = user_sessions[uid]
    pending = sess["pending_compression"]
    
    bot.reply_to(m, f"🗜️ Generando {pending['num_zips']} ZIP(s) protegido(s)...")
    
    try:
        pwd = pending["password"]
        groups = pending["groups"]
        num_zips = pending["num_zips"]
        
        # Crear cada ZIP
        for zip_num, group in enumerate(groups, 1):
            # Nombre del ZIP
            if num_zips == 1:
                zip_name = f"{zip_base_name}.zip"
            else:
                zip_name = f"{zip_base_name}{zip_num}.zip"
            
            # Crear el ZIP
            with pyzipper.AESZipFile(zip_name, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                zf.setpassword(pwd.encode("utf-8"))
                zf.setencryption(pyzipper.WZ_AES, nbits=256)
                for file_item in group:
                    c_path = str(file_item["path"])
                    c_name = str(file_item["name"])
                    if os.path.exists(c_path):
                        zf.write(c_path, arcname=c_name)
            
            # Validar tamaño FINAL del ZIP
            zip_size = os.path.getsize(zip_name)
            if zip_size > TELEGRAM_MAX_SIZE:
                os.remove(zip_name)
                
                # Limpiar y avisar
                for file_item in sum(groups, []):
                    if os.path.exists(file_item["path"]):
                        os.remove(file_item["path"])
                
                bot.reply_to(m, 
                    f"❌ Error inesperado: {zip_name} es demasiado grande ({format_size(zip_size)}).\n\n"
                    f"Esto no debería ocurrir. Intenta /limpiar y de nuevo con menos archivos."
                )
                sess["state"] = "idle"
                sess["pending_compression"] = None
                return
            
            # Enviar ZIP
            with open(zip_name, "rb") as zf:
                caption = f"🎉 ZIP {zip_num}/{num_zips}\n\n"
                caption += f"📦 Archivo: {zip_name}\n"
                caption += f"📏 Tamaño: {format_size(zip_size)}\n"
                caption += f"🔒 Contraseña: {pwd}"
                
                bot.send_document(
                    m.chat.id,
                    zf,
                    caption=caption
                )
            
            os.remove(zip_name)
        
        # Limpiar archivos temporales
        for file_item in sum(groups, []):
            if os.path.exists(file_item["path"]):
                os.remove(file_item["path"])
        
        # Resetear sesión
        sess["files"] = []
        sess["state"] = "idle"
        sess["pending_compression"] = None
        
        bot.send_message(m.chat.id, "✅ ¡Todos los ZIPs se han enviado correctamente!\n\n📥 Puedes comenzar de nuevo con /start")
    
    except Exception as e:
        bot.reply_to(m, f"❌ Error durante la compresión: {e}")
        sess["state"] = "idle"
        sess["pending_compression"] = None
        
        # Limpiar archivos temporales
        try:
            for file_item in sum(pending["groups"], []):
                if os.path.exists(file_item["path"]):
                    os.remove(file_item["path"])
        except:
            pass

@bot.message_handler(func=lambda m: True)
def handle_other_messages(m):
    """Captura cualquier otro mensaje cuando estamos esperando el nombre del ZIP"""
    uid = m.from_user.id
    if user_sessions.get(uid, {}).get("state") == "waiting_for_zip_name":
        # El mensaje se procesa en get_zip_name
        pass

if __name__ == "__main__":
    print("🤖 Bot iniciado correctamente en la nube...")
    bot.infinity_polling()
