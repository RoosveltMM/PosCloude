import uuid, os, base64, io
import time
from datetime import date
from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify

import psycopg2
import psycopg2.extras
import cloudinary
import cloudinary.uploader
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configurar Cloudinary
cloudinary.config(
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.environ.get("CLOUDINARY_API_KEY"),
    api_secret = os.environ.get("CLOUDINARY_API_SECRET"),
    secure     = True
)

# Lee la URL de la BD desde variable de entorno (seguro para Railway)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
print(f"[DEBUG] Usando host: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'NO CONFIGURADA'}")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("Falta la variable de entorno SECRET_KEY")
# y Activar esta línea de abajo para desarrollo local:
#socketio = SocketIO(app, cors_allowed_origins="*")
EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "gif", "avif"}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de base de datos
# ─────────────────────────────────────────────────────────────────────────────

def nueva_conexion():
    """Crea siempre una conexión fresca directamente a Supabase."""
    return psycopg2.connect(DATABASE_URL)

def query(sql, params=(), one=False, conn=None):
    """
    Ejecuta una consulta SELECT.
    Si se pasa 'conn', reutiliza esa conexión y NO la cierra (la maneja quien la creó).
    Si no se pasa 'conn', abre y cierra una conexión propia (comportamiento original).
    """
    conn_propia = conn is None
    if conn_propia:
        conn = nueva_conexion()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        result = cur.fetchone() if one else cur.fetchall()
        cur.close()
        return result
    finally:
        if conn_propia:
            conn.close()

def execute(sql, params=(), conn=None):
    """
    Ejecuta un INSERT/UPDATE/DELETE.
    Si se pasa 'conn', reutiliza esa conexión y NO la cierra.
    Si no se pasa 'conn', abre y cierra una conexión propia (comportamiento original).
    """
    conn_propia = conn is None
    if conn_propia:
        conn = nueva_conexion()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    finally:
        if conn_propia:
            conn.close()

def get_config(clave, default=None, conn=None):
    row = query("SELECT valor FROM configuracion WHERE clave=%s", (clave,), one=True, conn=conn)
    return row["valor"] if row else default

def contar_alertas(conn=None):
    dias_global = int(get_config("dias_alerta_precio", "30", conn=conn))
    t_query = time.time()
    productos = query(
        "SELECT fecha_ultimo_precio, dias_alerta FROM productos WHERE fecha_ultimo_precio IS NOT NULL",
        conn=conn
    )
    print(f"[TIMING] alertas -> query: {time.time()-t_query:.2f}s | filas: {len(productos)}")
    t_loop = time.time()
    hoy = date.today()
    count = 0
    for p in productos:
        dias = int(p["dias_alerta"]) if p["dias_alerta"] is not None else dias_global
        if (hoy - date.fromisoformat(p["fecha_ultimo_precio"])).days >= dias:
            count += 1
    print(f"[TIMING] alertas -> loop: {time.time()-t_loop:.2f}s")
    return count

def extension_permitida(f):
    return "." in f and f.rsplit(".", 1)[1].lower() in EXTENSIONES_PERMITIDAS

def guardar_imagen(request_files, request_form):
    """Recibe URL ya subida a Cloudinary desde el frontend, o acepta URL directa."""
    # 1. URL de Cloudinary ya procesada desde el frontend (crop o archivo)
    url = request_form.get("imagen_url", "").strip()
    if url and url.startswith("http"):
        return url
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/catalogo")
def catalogo():
    if not session.get("rol"):
        return redirect(url_for("acceso"))
    cat = request.args.get("categoria", "todas")
    base = """
        SELECT p.id, p.nombre, p.precio_venta, p.precio_compra,
               p.stock, p.imagen, p.es_favorito, p.fecha_ultimo_precio,
               p.dias_alerta, p.categoria_id,p.updated_at,
               c.nombre AS categoria_nombre
        FROM productos p LEFT JOIN categorias c ON p.categoria_id = c.id
    """

    conn = nueva_conexion()  # UNA sola conexión para todo el request
    try:
        t0 = time.time()
        if cat == "favoritos":
            productos = query(base + " WHERE p.es_favorito=1 ORDER BY p.nombre", conn=conn)
        elif cat == "todas":
            productos = query(base + " ORDER BY c.nombre, p.nombre", conn=conn)
        else:
            productos = query(base + " WHERE p.categoria_id=%s ORDER BY p.nombre", (cat,), conn=conn)
        print(f"[TIMING] productos: {time.time()-t0:.2f}s")

        # --- NUEVA LÓGICA: Calculamos las etiquetas aquí de forma segura ---
        t1 = time.time()
        ahora = datetime.now(timezone.utc)
        for p in productos:
            if not p.get("updated_at"):
                p["texto_edicion"] = "No revisado"
                p["clase_edicion"] = "status-pendiente"
            else:
                fecha_mod = p["updated_at"]
                if fecha_mod.tzinfo is None:
                    fecha_mod = fecha_mod.replace(tzinfo=timezone.utc)

                dias = (ahora - fecha_mod).days
                p["clase_edicion"] = "status-ok"

                if dias < 1:
                    p["texto_edicion"] = "Hoy"
                elif dias == 1:
                    p["texto_edicion"] = "Ayer"
                else:
                    p["texto_edicion"] = f"Hace {dias}d"
        print(f"[TIMING] etiquetas: {time.time()-t1:.2f}s")
        # -----------------------------------------------------------------

        t2 = time.time()
        categorias = query("SELECT id, nombre FROM categorias ORDER BY nombre", conn=conn)
        print(f"[TIMING] categorias: {time.time()-t2:.2f}s")

        t3 = time.time()
        n_fav_row = query("SELECT COUNT(*) AS n FROM productos WHERE es_favorito=1", one=True, conn=conn)
        n_favoritos = n_fav_row["n"] if n_fav_row else 0
        print(f"[TIMING] n_favoritos: {time.time()-t3:.2f}s")

        t4 = time.time()
        alertas = contar_alertas(conn=conn) if session.get("rol") == "admin" else 0
        print(f"[TIMING] alertas: {time.time()-t4:.2f}s")
    finally:
        conn.close()

    t5 = time.time()
    resultado = render_template("catalogo.html", productos=productos, categorias=categorias,
                           categoria_activa=cat, n_favoritos=n_favoritos,
                           alertas_precio=alertas)
    print(f"[TIMING] render: {time.time()-t5:.2f}s")
    print(f"[TIMING] TOTAL: {time.time()-t0:.2f}s")

    return resultado


@app.route("/verificar_producto/<int:producto_id>", methods=["POST"])
def verificar_producto(producto_id):
    # Verificación de seguridad básica (mismo control que en tu catálogo)
    if not session.get("rol"):
        return jsonify({"success": False, "error": "No autorizado"}), 403

    try:
        # CORRECCIÓN VITAL: Cambiamos 'query' por 'execute' para que haga el Commit en Supabase
        execute("UPDATE productos SET updated_at = NOW() WHERE id = %s", (producto_id,))
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error en verificación directa: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/acceso", methods=["GET", "POST"])#acá se asigna los valores para session 
def acceso():
    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        if pin == get_config("pin_admin"):
            session["rol"] = "admin"; return redirect(url_for("catalogo"))
        elif pin == get_config("pin_empleado"):
            session["rol"] = "empleado"; return redirect(url_for("catalogo"))
        flash("PIN incorrecto.", "error")
        return redirect(url_for("acceso"))
    return render_template("acceso.html")

@app.route("/salir")
def salir():
    session.clear(); return redirect(url_for("index"))

@app.route("/producto/favorito/<int:id_prod>", methods=["POST"])
def toggle_favorito(id_prod):
    if session.get("rol") != "admin": return jsonify({"ok": False}), 403
    prod = query("SELECT es_favorito FROM productos WHERE id=%s", (id_prod,), one=True)
    nuevo = 0 if prod["es_favorito"] else 1
    execute("UPDATE productos SET es_favorito=%s WHERE id=%s", (nuevo, id_prod))
    return jsonify({"ok": True, "es_favorito": nuevo})

@app.route("/producto/nuevo", methods=["POST"])
def nuevo_producto():
    if session.get("rol") != "admin": return redirect(url_for("catalogo"))
    nombre = request.form.get("nombre", "").strip()
    pv     = request.form.get("precio_venta", "0")
    pc     = request.form.get("precio_compra", "")
    stock  = request.form.get("stock", "0")
    cat_id = request.form.get("categoria_id")
    dias_a = request.form.get("dias_alerta", "").strip()

    if not nombre or not pv or not cat_id:
        flash("Completa los campos obligatorios.", "error")
        return redirect(url_for("catalogo"))

    imagen = guardar_imagen(request.files, request.form)
    # MODIFICACIÓN: Añadimos updated_at con NOW() al insertar
    execute("""
        INSERT INTO productos
            (nombre, precio_venta, precio_compra, stock, categoria_id,
             imagen, fecha_ultimo_precio, dias_alerta,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    """, (
        nombre, float(pv),
        float(pc) if pc else None,
        int(stock) if stock else 0,
        cat_id, imagen, str(date.today()),
        int(dias_a) if dias_a.isdigit() else None
    ))
    flash(f'"{nombre}" agregado.', "ok")
    return redirect(url_for("catalogo", categoria=cat_id))

@app.route("/producto/editar", methods=["POST"])
def editar_producto():
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403

    id_p   = request.form.get("id")
    nombre = request.form.get("nombre", "").strip()
    pv     = float(request.form.get("precio_venta", "0"))
    pc     = request.form.get("precio_compra", "")
    stock  = request.form.get("stock", "0")
    cat_id = request.form.get("categoria_id")
    dias_a = request.form.get("dias_alerta", "").strip()

    old = query("SELECT precio_venta FROM productos WHERE id=%s", (id_p,), one=True)
    cambio_precio = old and round(old["precio_venta"], 2) != round(pv, 2)

    nueva_img = guardar_imagen(request.files, request.form)

    # MODIFICACIÓN: Agregamos updated_at=NOW() por defecto en cada edición
    campos = "nombre=%s, precio_venta=%s, precio_compra=%s, stock=%s, categoria_id=%s, dias_alerta=%s, updated_at=NOW()"
    vals   = [nombre, pv, float(pc) if pc else None,
              int(stock) if stock else 0, cat_id,
              int(dias_a) if dias_a.isdigit() else None]

    if nueva_img:
        campos += ", imagen=%s"; vals.append(nueva_img)
    if cambio_precio:
        campos += ", fecha_ultimo_precio=%s"; vals.append(str(date.today()))

    vals.append(id_p)
    execute(f"UPDATE productos SET {campos} WHERE id=%s", vals)



    return jsonify({"ok": True})

@app.route("/producto/eliminar/<int:id_prod>", methods=["POST"])
def eliminar_producto(id_prod):
    if session.get("rol") != "admin": return jsonify({"ok": False}), 403
    execute("DELETE FROM productos WHERE id=%s", (id_prod,))
    return jsonify({"ok": True})

@app.route("/configuracion", methods=["GET", "POST"])
def pagina_configuracion():
    if session.get("rol") != "admin": return redirect(url_for("index"))
    if request.method == "POST":
        for clave in ["pin_admin", "pin_empleado"]:
            val = request.form.get(clave, "").strip()
            if val:
                execute("UPDATE configuracion SET valor=%s WHERE clave=%s", (val, clave))
        dias = request.form.get("dias_alerta_precio", "").strip()
        if dias and dias.isdigit():
            execute(
                "INSERT INTO configuracion (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                ("dias_alerta_precio", dias)
            )
        flash("Configuración guardada.", "ok")
        return redirect(url_for("pagina_configuracion"))

    dias_global = int(get_config("dias_alerta_precio", "30"))
    categorias  = query("SELECT id, nombre FROM categorias ORDER BY nombre")
    hoy = date.today()
    todos = query("""
        SELECT p.id, p.nombre, p.precio_venta, p.fecha_ultimo_precio, p.dias_alerta,
               c.nombre AS categoria
        FROM productos p LEFT JOIN categorias c ON p.categoria_id = c.id
        WHERE p.fecha_ultimo_precio IS NOT NULL
        ORDER BY p.fecha_ultimo_precio ASC
    """)

    productos_alerta = []
    for p in todos:
        dias = int(p["dias_alerta"]) if p["dias_alerta"] is not None else dias_global
        diff = (hoy - date.fromisoformat(p["fecha_ultimo_precio"])).days
        if diff >= dias:
            productos_alerta.append({**dict(p), "dias_transcurridos": diff, "dias_limite": dias})

    return render_template("configuracion.html",
                           pin_admin=get_config("pin_admin"),
                           pin_empleado=get_config("pin_empleado"),
                           dias_alerta=str(dias_global),
                           categorias=categorias,
                           productos_alerta=productos_alerta)

@app.route("/producto/confirmar_precio/<int:id_prod>", methods=["POST"])
def confirmar_precio(id_prod):
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    execute("UPDATE productos SET fecha_ultimo_precio=%s WHERE id=%s",
            (str(date.today()), id_prod))
    return jsonify({"ok": True})

@app.route("/categoria/nueva", methods=["POST"])
def nueva_categoria():
    if session.get("rol") != "admin": return redirect(url_for("catalogo"))
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        execute("INSERT INTO categorias (nombre) VALUES (%s)", (nombre,))
        flash(f'Categoría "{nombre}" creada.', "ok")
    return redirect(url_for("pagina_configuracion"))

@app.route("/categoria/eliminar/<int:id_cat>")
def eliminar_categoria(id_cat):
    if session.get("rol") != "admin": return redirect(url_for("catalogo"))
    execute("DELETE FROM categorias WHERE id=%s", (id_cat,))
    flash("Categoría eliminada.", "ok")
    return redirect(url_for("pagina_configuracion"))

@app.route("/producto/editar_precio_rapido", methods=["POST"])
def editar_precio_rapido():
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    id_p  = request.form.get("id")
    precio = request.form.get("precio_venta")
    if not id_p or not precio:
        return jsonify({"ok": False})
    old = query("SELECT precio_venta FROM productos WHERE id=%s", (id_p,), one=True)
    execute("""
        UPDATE productos 
        SET precio_venta=%s, fecha_ultimo_precio=%s, updated_at= NOW() 
        WHERE id=%s
    """, (float(precio), str(date.today()), id_p))


    return jsonify({"ok": True})

# TODO Módulo 2 — Cobros y tickets

@app.route("/cambios")
def cambios():
    """Polling: devuelve precios actuales para sincronización en tiempo real."""
    productos = query("SELECT id, precio_venta FROM productos")
    return jsonify([dict(p) for p in productos])

@app.route("/producto/firma_cloudinary", methods=["POST"])
def firma_cloudinary():
    """Genera firma para upload directo desde el frontend usando la librería oficial de Cloudinary."""
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    import time
    modo = request.form.get("modo", "normal")
    timestamp = int(time.time())
    params = {"folder": "mipos/productos", "timestamp": timestamp}
    if modo == "sin_fondo":
        params["background_removal"] = "cloudinary_ai"
        params["format"] = "png"
    # Usar la librería oficial para generar la firma correctamente
    firma = cloudinary.utils.api_sign_request(params, os.environ.get("CLOUDINARY_API_SECRET", ""))
    return jsonify({
        "ok": True,
        "timestamp": timestamp,
        "signature": firma,
        "modo": modo,
        "api_key": os.environ.get("CLOUDINARY_API_KEY", ""),
        "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    })

if __name__ == "__main__":
    app.run(app, debug=True, host="0.0.0.0", port=5000)