import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "MiPos.db")

conexion = sqlite3.connect(DB_PATH)
cursor = conexion.cursor()

# -------------------------
# TABLA CATEGORIAS
# -------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL
)
""")

# -------------------------
# TABLA PRODUCTOS
# -------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    precio_venta REAL NOT NULL,
    precio_compra REAL,
    stock INTEGER DEFAULT 0,
    categoria_id INTEGER,
    imagen TEXT,
    FOREIGN KEY(categoria_id) REFERENCES categorias(id)
)
""")

# -------------------------
# TABLA CONFIGURACION (para PINs)
# -------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
)
""")

# -------------------------
# TABLA VENTAS (para modulo futuro)
# -------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    rol_cajero TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS detalles_ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_venta INTEGER NOT NULL,
    id_producto INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY(id_venta) REFERENCES ventas(id),
    FOREIGN KEY(id_producto) REFERENCES productos(id)
)
""")

# -------------------------
# DATOS INICIALES
# -------------------------
# PINs por defecto
cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('pin_admin', '1234')")
cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('pin_empleado', '0000')")

# Categorias
categorias = [
    (1, 'Panes'),
    (2, 'Leches'),
    (3, 'Embutidos'),
    (4, 'Lacteos'),
    (5, 'Cafes'),
    (6, 'Mantequillas'),
    (7, 'Papeles'),
    (8, 'Abarrotes'),
]
for cat in categorias:
    cursor.execute("INSERT OR IGNORE INTO categorias (id, nombre) VALUES (?, ?)", cat)

# Productos de ejemplo
productos_ejemplo = [
    ('Pan de molde Bimbo', 4.50, 3.80, 10, 1, None),
    ('Gloria tarro azul 390gr', 4.20, 3.50, 15, 2, None),
    ('Jamonada San Fernando 250gr', 5.50, 4.20, 8, 3, None),
    ('Yogurt Gloria fresa 1kg', 6.80, 5.50, 12, 4, None),
    ('Nescafe clasico 50gr', 7.90, 6.50, 20, 5, None),
    ('Mantequilla Gloria 100gr', 3.20, 2.50, 18, 6, None),
    ('Papel higienico Suave doble hoja x4', 5.90, 4.80, 25, 7, None),
    ('Arroz Costeño 1kg', 3.50, 2.90, 30, 8, None),
]
for p in productos_ejemplo:
    cursor.execute("""
        INSERT OR IGNORE INTO productos (nombre, precio_venta, precio_compra, stock, categoria_id, imagen)
        VALUES (?, ?, ?, ?, ?, ?)
    """, p)

conexion.commit()
conexion.close()
print("Base de datos creada correctamente.")
print(f"Ubicacion: {DB_PATH}")
