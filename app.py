import io
import os
import random
import string
from datetime import datetime, timedelta
import pymysql
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = Flask(__name__)
app.secret_key = "clave_secreta_para_sesiones"

# -------------------------------
# CONFIGURACIÓN DE LA BASE DE DATOS
# -------------------------------
def get_db_connection():
    try:
        conn = pymysql.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'root'),
            password=os.environ.get('DB_PASSWORD', ''),
            database=os.environ.get('DB_NAME', 'spacewash_db'),
            port=int(os.environ.get('DB_PORT', 3306)),
            autocommit=True,
            connect_timeout=5  # Evita que la app se quede colgada infinitamente si no conecta
        )
        return conn
    except Exception as e:
        print(f"❌ Error crítico de conexión a la base de datos: {e}")
        return None

# -------------------------------
# RUTA DE PRUEBA
# -------------------------------
@app.route("/")
def index():
    return render_template("login.html")

# login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario_form = request.form["usuario"]
        password_form = request.form["password"]

        conn = get_db_connection()
        if not conn:
            return "Error del sistema: No se pudo establecer conexión con la base de datos."

        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            # Buscamos al usuario, sin validar todavía si está activo
            cursor.execute("SELECT * FROM usuarios WHERE usuario=%s AND password=%s",
                           (usuario_form, password_form))
            user = cursor.fetchone()
        finally:
            conn.close()

        if not user:
            return "Usuario o contraseña incorrectos"

        # 🚫 Usuario encontrado pero INACTIVO
        if user["activo"] == 0:
            return "Este usuario ha sido dado de baja y no puede iniciar sesión."

        # ✔ Usuario válido y activo
        session.clear()
        session["id"] = user["id"]
        session["usuario"] = user["usuario"]
        session["nombre"] = user["nombre"]
        session["rol"] = user["rol"]

        # Redirección según rol
        if user["rol"] == "administrador":
            return redirect("/admin")
        elif user["rol"] == "jefe":
            return redirect("/jefe")
        else:
            return redirect("/operativo")

    return render_template("login.html")


# paneles
@app.route("/admin")
def admin_panel():
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")
    return render_template("admin_panel.html", nombre=session["nombre"])

@app.route("/jefe")
def jefe_panel():
    if "rol" not in session or session["rol"] != "jefe":
        return redirect("/")
    return render_template("jefe_panel.html", nombre=session["nombre"])

@app.route("/operativo")
def operativo_panel():
    if "rol" not in session or session["rol"] != "operativo":
        return redirect("/")
    return render_template("operativo_panel.html", nombre=session["nombre"])

# cerrar sesion
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# formulario de cobros
@app.route("/admin/cobro")
def admin_cobro():
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tv.id, tv.tipo, pv.precio, pv.precio_promocion, pv.dias_promocion
            FROM tipos_vehiculo tv
            LEFT JOIN precios_vehiculo pv ON tv.id = pv.tipo_id
        """)
        tipos = cursor.fetchall()
    finally:
        conn.close()

    # Traducir el día actual
    hoy_en = datetime.now().strftime("%A").lower()
    
    dias_traducidos = {
        "monday": "lunes",
        "tuesday": "martes",
        "wednesday": "miercoles",
        "thursday": "jueves",
        "friday": "viernes",
        "saturday": "sabado",
        "sunday": "domingo"
    }
    
    hoy = dias_traducidos[hoy_en]   # ← ahora coincide con tus días en la BD
    print("Hoy es:", hoy)

    # Aplicación de promoción
    for t in tipos:
        dias = (t["dias_promocion"] or "").lower().replace(" ", "")
        if hoy in dias:
            t["precio_final"] = t["precio_promocion"]
            t["promo_activa"] = True
        else:
            t["precio_final"] = t["precio"]
            t["promo_activa"] = False

    return render_template("admin_cobro.html", tipos=tipos)

##
@app.route("/admin/cobro", methods=["POST"])
def admin_cobro_post():
    tipo_id = int(request.form["tipo"])

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # Traer precio y promociones
        cursor.execute("""
            SELECT tv.*, pv.precio AS precio_general, pv.precio_promocion, pv.dias_promocion
            FROM tipos_vehiculo tv
            LEFT JOIN precios_vehiculo pv ON tv.id = pv.tipo_id
            WHERE tv.id=%s
        """, (tipo_id,))
        tipo = cursor.fetchone()
    finally:
        conn.close()

    # calcular precio final según promoción
    hoy = datetime.now().strftime('%A').lower()
    precio_final = tipo['precio_general']
    if tipo['precio_promocion'] and tipo['dias_promocion']:
        dias = [d.strip().lower() for d in tipo['dias_promocion'].split(',')]
        if hoy in dias:
            precio_final = tipo['precio_promocion']

    # guardar en session para pasar al registro
    session['registro_tipo_id'] = tipo_id
    session['registro_precio'] = float(precio_final)  # convertir Decimal a float

    return redirect(f"/admin/cobro/pago/{tipo_id}")
##

# ruta nueva tipo de pago
@app.route("/admin/cobro/pago/<int:tipo_id>")
def admin_cobro_pago(tipo_id):
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    return render_template("admin_pago.html", tipo_id=tipo_id)


@app.route("/admin/cobro/pago/<int:tipo_id>", methods=["POST"])
def admin_cobro_pago_post(tipo_id):
    pago = request.form["pago"]

    # si es tarjeta, simulamos falla aleatoria
    if pago == "tarjeta":
        if random.random() < 0.2:  # 20% falla
            flash("❌ El pago con tarjeta fue rechazado.")
            return redirect(f"/admin/cobro/pago/{tipo_id}")

    return redirect(f"/admin/registrar/{tipo_id}")


# GET: Formulario de registro
@app.route("/admin/registrar/<int:tipo_id>")
def admin_registrar(tipo_id):
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Traer datos del tipo de vehículo con precios desde precios_vehiculo
        cursor.execute("""
            SELECT pv.id, pv.tipo_id, pv.precio, pv.precio_promocion, pv.dias_promocion
            FROM precios_vehiculo pv
            WHERE pv.tipo_id = %s
        """, (tipo_id,))
        tipo_precio = cursor.fetchone()

        # Traer nombre del tipo de vehículo desde tipos_vehiculo
        cursor.execute("SELECT tipo FROM tipos_vehiculo WHERE id=%s", (tipo_id,))
        tipo_nombre = cursor.fetchone()["tipo"]

        # Obtener prioridad
        cursor.execute("SELECT COUNT(*) AS total FROM vehiculos")
        prioridad = cursor.fetchone()["total"] + 1
    finally:
        conn.close()

    # Día de la semana en español
    dias_semana = {
        "Monday": "lunes",
        "Tuesday": "martes",
        "Wednesday": "miercoles",
        "Thursday": "jueves",
        "Friday": "viernes",
        "Saturday": "sabado",
        "Sunday": "domingo"
    }
    hoy = dias_semana[datetime.now().strftime("%A")]

    # Determinar precio final y si hay promoción
    precio_final = tipo_precio['precio']
    promocion_hoy = False
    if tipo_precio['dias_promocion']:
        dias = [d.strip().lower() for d in tipo_precio['dias_promocion'].split(',')]
        if hoy in dias and tipo_precio['precio_promocion']:
            precio_final = tipo_precio['precio_promocion']
            promocion_hoy = True

    return render_template(
        "admin_registrar.html",
        tipo_id=tipo_id,
        tipo_nombre=tipo_nombre,
        tipo_precio=tipo_precio,
        prioridad=prioridad,
        precio_final=precio_final,
        promocion_hoy=promocion_hoy
    )

# POST: Guardar registro y generar ticket
@app.route("/admin/registrar/<int:tipo_id>", methods=["POST"])
def admin_registrar_post(tipo_id):
    propietario = request.form["propietario"]
    curp = request.form["curp"]
    placas = request.form["placas"]
    modelo = request.form["modelo"]

    # Validaciones
    if len(curp) != 18:
        flash("❌ La CURP debe tener 18 caracteres.")
        return redirect(f"/admin/registrar/{tipo_id}")
    if len(placas) < 6 or len(placas) > 10:
        flash("❌ Las placas no tienen longitud válida.")
        return redirect(f"/admin/registrar/{tipo_id}")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Obtener prioridad
        cursor.execute("SELECT COUNT(*) AS total FROM vehiculos")
        prioridad = cursor.fetchone()["total"] + 1

        fecha = datetime.now()

        # Obtener precio aplicado hoy y tipo desde la BD
        cursor.execute("""
            SELECT pv.precio, pv.precio_promocion, pv.dias_promocion, t.tipo
            FROM precios_vehiculo pv
            JOIN tipos_vehiculo t ON pv.tipo_id = t.id
            WHERE pv.tipo_id=%s
        """, (tipo_id,))
        tipo_precio = cursor.fetchone()

        # Día de la semana en español
        dias_semana = {
            "Monday": "lunes",
            "Tuesday": "martes",
            "Wednesday": "miercoles",
            "Thursday": "jueves",
            "Friday": "viernes",
            "Saturday": "sabado",
            "Sunday": "domingo"
        }
        hoy = dias_semana[datetime.now().strftime("%A")]

        # Calcular precio final
        precio_final = tipo_precio['precio']
        if tipo_precio['dias_promocion']:
            dias = [d.strip().lower() for d in tipo_precio['dias_promocion'].split(',')]
            if hoy in dias and tipo_precio['precio_promocion']:
                precio_final = tipo_precio['precio_promocion']

        # Insertar vehículo en la tabla
        cursor.execute("""
            INSERT INTO vehiculos (propietario, curp, placas, modelo, tipo_id, prioridad, fecha_ingreso)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (propietario, curp, placas, modelo, tipo_id, prioridad, fecha))
        conn.commit()
    finally:
        conn.close()

    # Generar ticket como archivo .txt
    admin_nombre = session.get('nombre', 'Administrador')
    ticket_text = f"""
-------SpaceWash----------
--- Ticket de registro ---
Fecha/Hora: {fecha.strftime('%Y-%m-%d %H:%M:%S')}
Administrador: {admin_nombre}

Vehículo: {tipo_precio['tipo']}
Propietario: {propietario}
CURP: {curp}
Placas: {placas}
Modelo: {modelo}
Prioridad: {prioridad}
Precio aplicado: ${precio_final}
---------------------------
"""

    # Crear carpeta tickets si no existe
    tickets_dir = os.path.join(os.getcwd(), "tickets")
    if not os.path.exists(tickets_dir):
        os.makedirs(tickets_dir)

    # Guardar archivo con nombre único por fecha y placas
    filename = f"{fecha.strftime('%Y%m%d_%H%M%S')}_{placas}.txt"
    with open(os.path.join(tickets_dir, filename), "w", encoding="utf-8") as f:
        f.write(ticket_text)

    flash(f"✅ Vehículo registrado correctamente. Ticket guardado como {filename}.")
    return redirect("/admin/vehiculos")

# fin reigistro y cobro

# lista de vehiculos
@app.route("/admin/vehiculos")
def admin_lista_vehiculos():
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # Solo mostrar vehículos que no estén entregados
        cursor.execute("""
            SELECT v.*, t.tipo 
            FROM vehiculos v
            JOIN tipos_vehiculo t ON v.tipo_id = t.id
            WHERE v.estatus != 'entregado'
            ORDER BY prioridad ASC
        """)
        vehiculos = cursor.fetchall()
    finally:
        conn.close()

    return render_template("admin_lista_vehiculos.html", vehiculos=vehiculos)


# vehiculos listos para entregar
@app.route("/admin/entregas")
def admin_entregas():
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, v.propietario, v.placas, v.modelo, t.tipo
            FROM vehiculos v
            JOIN tipos_vehiculo t ON v.tipo_id = t.id
            WHERE v.estatus = 'listo para entregar'
        """)
        vehiculos = cursor.fetchall()
    finally:
        conn.close()

    return render_template("admin_entregas.html", vehiculos=vehiculos)

# entregar y borrar datos del vehiculo
@app.route("/admin/entregar/<int:vehiculo_id>", methods=["POST"])
def admin_entregar_vehiculo(vehiculo_id):
    if "rol" not in session or session["rol"] != "administrador":
        return redirect("/")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        # obtener tipo del vehículo para estadística futura
        cursor.execute("""
            SELECT t.tipo 
            FROM vehiculos v
            JOIN tipos_vehiculo t ON v.tipo_id = t.id
            WHERE v.id=%s
        """, (vehiculo_id,))
        result = cursor.fetchone()
        tipo = result["tipo"]

        fecha = datetime.now()

        # guardar en tabla de entregas
        cursor.execute("""
            INSERT INTO entregas (tipo_vehiculo, fecha_entrega)
            VALUES (%s, %s)
        """, (tipo, fecha))

        # actualizar vehículo: limpiar datos y marcar entregado
        cursor.execute("""
            UPDATE vehiculos
            SET propietario='ENTREGADO', curp='ENTREGADO', placas='ENTREGADO', estatus='entregado'
            WHERE id=%s
        """, (vehiculo_id,))
        conn.commit()
    finally:
        conn.close()

    return redirect("/admin/entregas")


# formulario de registro de empleados (jefe)
@app.route('/jefe/registro_empleado')
def registro_empleado():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')
    return render_template('registro_empleado.html')

# registrar empleados
@app.route('/jefe/registro_empleado', methods=['POST'])
def registro_empleado_post():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    nombre = request.form['nombre']
    curp = request.form['curp']
    rol = request.form['rol']

    # Generar usuario automático (primeras 3 letras del nombre + número random)
    usuario = nombre[:3].lower() + str(random.randint(100, 999))

    # Generar contraseña aleatoria (8 caracteres)
    caracteres = string.ascii_letters + string.digits
    password = ''.join(random.choice(caracteres) for _ in range(8))

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usuarios (nombre, usuario, password, rol)
            VALUES (%s, %s, %s, %s)
        """, (nombre, usuario, password, rol))
        conn.commit()
    finally:
        conn.close()

    return f"Empleado registrado exitosamente! Usuario: {usuario} | Contraseña: {password}"


# Horarios
@app.route('/jefe/horarios')
def horarios():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, rol 
            FROM usuarios 
            WHERE activo=1 AND rol NOT IN ('jefe')
        """)
        empleados = cursor.fetchall()
    finally:
        conn.close()

    return render_template('horarios.html', empleados=empleados)

@app.route('/jefe/horarios/<int:empleado_id>')
def editar_horario(empleado_id):
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE id=%s AND activo=1", (empleado_id,))
        empleado = cursor.fetchone()

        if not empleado:
            return "Empleado no encontrado"

        cursor.execute("SELECT * FROM horarios_empleados WHERE usuario_id=%s", (empleado_id,))
        horario = cursor.fetchone()
    finally:
        conn.close()

    return render_template('editar_horario.html', empleado=empleado, horario=horario)

@app.route('/jefe/horarios/guardar', methods=['POST'])
def guardar_horario():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    usuario_id = int(request.form['usuario_id'])
    hora_entrada = request.form['hora_entrada']
    hora_salida = request.form['hora_salida']
    hora_comida = request.form['hora_comida']
    dia_descanso = request.form['dia_descanso']

    # VALIDACIÓN: comida dentro del horario
    if not (hora_entrada <= hora_comida <= hora_salida):
        return "Error: La hora de comida debe estar dentro del horario laboral."

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM horarios_empleados WHERE usuario_id=%s", (usuario_id,))
        existe = cursor.fetchone()

        if existe:
            cursor.execute("""
                UPDATE horarios_empleados
                SET hora_entrada=%s, hora_salida=%s, hora_comida=%s, dias_descanso=%s
                WHERE usuario_id=%s
            """, (hora_entrada, hora_salida, hora_comida, dia_descanso, usuario_id))
        else:
            cursor.execute("""
                INSERT INTO horarios_empleados (usuario_id, hora_entrada, hora_salida, hora_comida, dias_descanso)
                VALUES (%s, %s, %s, %s, %s)
            """, (usuario_id, hora_entrada, hora_salida, hora_comida, dia_descanso))
        conn.commit()
    finally:
        conn.close()

    return redirect('/jefe/horarios')

# Fin horarios

# listar empleados activos
@app.route('/jefe/empleados')
def listar_empleados():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        # Empleados activos
        cursor.execute("""
            SELECT 
                u.id,
                u.nombre,
                u.rol,
                u.usuario,
                u.password,
                h.hora_entrada,
                h.hora_salida,
                h.hora_comida,
                h.dias_descanso
            FROM usuarios u
            LEFT JOIN horarios_empleados h ON u.id = h.usuario_id
            WHERE u.activo = 1 AND u.rol NOT IN ('jefe')
        """)
        empleados = cursor.fetchall()

        # 🔽 empleados dados de baja
        cursor.execute("""
            SELECT id, nombre, usuario, rol
            FROM usuarios
            WHERE activo = 0
        """)
        empleados_baja = cursor.fetchall()
    finally:
        conn.close()

    return render_template(
        'empleados.html',
        empleados=empleados,
        empleados_baja=empleados_baja
    )


# dar de baja a los empleados 
@app.route('/jefe/dar_baja/<int:id>') 
def dar_baja_empleado(id): 
    if 'rol' not in session or session['rol'] != 'jefe': 
        return redirect('/login') 
    
    conn = get_db_connection() 
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor() 
        # Baja lógica: se marca como inactivo 
        cursor.execute("UPDATE usuarios SET activo=0 WHERE id=%s", (id,)) 
        conn.commit() 
    finally:
        conn.close() 
    return redirect('/jefe/empleados')

# reactivar empleados
@app.route('/jefe/reactivar/<int:id>')
def reactivar_empleado(id):
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET activo=1 WHERE id=%s", (id,))
        conn.commit()
    finally:
        conn.close()

    return redirect('/jefe/empleados')

# estadisticas de vehiculos
@app.route('/jefe/historial')
def historial():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # Conteo por tipo
        cursor.execute("""
            SELECT tv.id, tv.tipo, COUNT(v.id) AS total
            FROM tipos_vehiculo tv
            LEFT JOIN vehiculos v ON v.tipo_id = tv.id
            GROUP BY tv.id, tv.tipo
        """)
        tipos = cursor.fetchall()
    finally:
        conn.close()

    if all(t['total'] == 0 for t in tipos):
        mensaje = "Historial vacío"
    else:
        mensaje = None

    return render_template("historial_tipos.html", tipos=tipos, mensaje=mensaje)

# ver una semana diferente
@app.route('/jefe/historial/vehiculo/<int:tipo_id>')
def historial_semana(tipo_id):
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    # Obtener semana solicitada o usar la actual
    week_str = request.args.get("week")
    if week_str:
        start_week = datetime.strptime(week_str, "%Y-%m-%d")
    else:
        today = datetime.today()
        start_week = today - timedelta(days=today.weekday())  # lunes

    end_week = start_week + timedelta(days=6)

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Obtener nombre del tipo de vehículo
        cursor.execute("SELECT tipo FROM tipos_vehiculo WHERE id=%s", (tipo_id,))
        tipo = cursor.fetchone()

        # Obtener conteo por día
        cursor.execute("""
            SELECT DATE(fecha_ingreso) AS fecha, COUNT(id) AS total
            FROM vehiculos
            WHERE tipo_id=%s
            AND fecha_ingreso BETWEEN %s AND %s
            GROUP BY fecha
        """, (tipo_id, start_week, end_week))

        dias = cursor.fetchall()
    finally:
        conn.close()

    # Convertir a diccionario para mapear días vacíos
    dias_dict = {d['fecha'].strftime("%Y-%m-%d"): d['total'] for d in dias}

    semana = []
    for i in range(7):
        dia = start_week + timedelta(days=i)
        fecha_str = dia.strftime("%Y-%m-%d")
        semana.append({
            "dia": dia.strftime("%A"),
            "fecha": fecha_str,
            "total": dias_dict.get(fecha_str, 0)
        })

    # Navegación entre semanas
    prev_week = (start_week - timedelta(days=7)).strftime("%Y-%m-%d")
    next_week = (start_week + timedelta(days=7)).strftime("%Y-%m-%d")

    return render_template(
        "historial_semana.html",
        tipo=tipo,
        semana=semana,
        start_week=start_week.strftime("%Y-%m-%d"),
        prev_week=prev_week,
        next_week=next_week,
        tipo_id=tipo_id
    )


# ver y registrar/modificar precios
@app.route('/jefe/precios')
def ver_precios():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT tv.id AS tipo_id, tv.tipo,
                   IFNULL(pv.precio, tv.precio_base) AS precio_general,
                   IFNULL(pv.precio_promocion, 0) AS precio_promocion,
                   IFNULL(pv.dias_promocion, '') AS dias_promocion
            FROM tipos_vehiculo tv
            LEFT JOIN precios_vehiculo pv ON tv.id = pv.tipo_id
        """)
        precios = cursor.fetchall()
    finally:
        conn.close()

    return render_template('precios.html', precios=precios)


# guardar precios
@app.route('/jefe/precios', methods=['POST'])
def guardar_precios():
    if 'rol' not in session or session['rol'] != 'jefe':
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id FROM tipos_vehiculo")
        tipos = cursor.fetchall()

        for t in tipos:
            tipo_id = t["id"]

            precio_general = request.form.get(f'precio_general_{tipo_id}', None)
            precio_promocion = request.form.get(f'precio_promocion_{tipo_id}', None)
            dias = request.form.getlist(f'dias_{tipo_id}')  # lista
            dias_txt = ",".join(dias)

            # Validación del flujo alterno
            if dias_txt == "" and precio_promocion not in ("", None):
                flash("Advertencia: Debe seleccionar días para aplicar la promoción.", "warning")
                continue

            cursor.execute("SELECT * FROM precios_vehiculo WHERE tipo_id=%s", (tipo_id,))
            existe = cursor.fetchone()

            if existe:
                cursor.execute("""
                    UPDATE precios_vehiculo
                    SET precio=%s, precio_promocion=%s, dias_promocion=%s
                    WHERE tipo_id=%s
                """, (precio_general, precio_promocion, dias_txt, tipo_id))
            else:
                cursor.execute("""
                    INSERT INTO precios_vehiculo (tipo_id, precio, precio_promocion, dias_promocion)
                    VALUES (%s, %s, %s, %s)
                """, (tipo_id, precio_general, precio_promocion, dias_txt))
        conn.commit()
    finally:
        conn.close()
        
    return redirect('/jefe/precios')

# Listar vehículos para empleados operativos
@app.route('/operativo/vehiculos', methods=['GET'])
def listar_vehiculos_operativo():
    if 'rol' not in session or session['rol'] != 'operativo':
        return redirect('/login')
    if 'id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # Solo mostrar vehículos que todavía no estén listos para entregar ni entregados
        cursor.execute("""
            SELECT v.id, v.propietario, v.placas, v.modelo, v.estatus, tv.tipo AS tipo_vehiculo
            FROM vehiculos v
            JOIN tipos_vehiculo tv ON v.tipo_id = tv.id
            WHERE v.estatus IN ('en espera', 'en lavado')
            ORDER BY v.prioridad ASC
        """)
        vehiculos = cursor.fetchall()
    finally:
        conn.close()

    return render_template('vehiculos_operativo.html', vehiculos=vehiculos)


# Cambiar estatus y registrar movimientos
@app.route('/operativo/vehiculos/cambiar', methods=['POST'])
def cambiar_estatus():
    if 'rol' not in session or session['rol'] != 'operativo':
        return redirect('/login')
    if 'id' not in session:
        return redirect('/login')

    empleado_id = session['id']
    vehiculo_id = int(request.form['vehiculo_id'])
    nuevo_estatus = request.form['estatus']

    fecha_hora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor()
        # Actualizar estatus
        cursor.execute("""
            UPDATE vehiculos
            SET estatus=%s
            WHERE id=%s
        """, (nuevo_estatus, vehiculo_id))

        # Registrar movimiento en historial
        cursor.execute("""
            INSERT INTO historial_movimientos (vehiculo_id, empleado_id, estatus, fecha_hora)
            VALUES (%s, %s, %s, %s)
        """, (vehiculo_id, empleado_id, nuevo_estatus, fecha_hora))
        conn.commit()
    finally:
        conn.close()

    # Redirigir para que la lista se actualice automáticamente
    return redirect('/operativo/vehiculos')


# reporte de movimientos
@app.route('/reportes/movimientos')
def reporte_movimientos():
    if 'rol' not in session or session['rol'] not in ['administrador','jefe']:
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # Solo mostrar movimientos de vehículos NO entregados y solo cambios válidos
        cursor.execute("""
            SELECT hm.id, v.propietario, v.placas, v.modelo, tv.tipo AS tipo_vehiculo,
                   u.nombre AS empleado, hm.estatus, hm.fecha_hora
            FROM historial_movimientos hm
            JOIN vehiculos v ON hm.vehiculo_id = v.id
            JOIN usuarios u ON hm.empleado_id = u.id
            JOIN tipos_vehiculo tv ON v.tipo_id = tv.id
            WHERE v.estatus != 'entregado'
            AND hm.estatus IN ('en espera','en lavado','listo para entregar')
            ORDER BY hm.fecha_hora DESC
        """)
        movimientos = cursor.fetchall()
    finally:
        conn.close()

    return render_template('reporte_movimientos.html', movimientos=movimientos)

# exportar pdf
@app.route('/reportes/movimientos/pdf')
def exportar_movimientos_pdf():
    if 'rol' not in session or session['rol'] not in ['administrador','jefe']:
        return redirect('/login')

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT hm.id, v.propietario, v.placas, v.modelo, tv.tipo AS tipo_vehiculo,
                   u.nombre AS empleado, hm.estatus, hm.fecha_hora
            FROM historial_movimientos hm
            JOIN vehiculos v ON hm.vehiculo_id = v.id
            JOIN usuarios u ON hm.empleado_id = u.id
            JOIN tipos_vehiculo tv ON v.tipo_id = tv.id
            WHERE v.estatus != 'entregado'
            AND hm.estatus IN ('en espera','en lavado','listo para entregar')
            ORDER BY hm.fecha_hora DESC
        """)
        movimientos = cursor.fetchall()
    finally:
        conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=20, rightMargin=20)

    styles = getSampleStyleSheet()
    elements = []

    # Título
    titulo = Paragraph("SpaceWash – Reporte de Movimientos", styles['Title'])
    elements.append(titulo)
    elements.append(Spacer(1, 12))

    # Fecha
    fecha_descarga = Paragraph(f"Fecha de descarga: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])
    elements.append(fecha_descarga)
    elements.append(Spacer(1, 12))

    # Tabla
    data = [["Propietario", "Placas", "Modelo", "Tipo", "Empleado", "Estatus", "Fecha/Hora"]]
    for m in movimientos:
        data.append([
            m["propietario"], m["placas"], m["modelo"],
            m["tipo_vehiculo"], m["empleado"], m["estatus"], str(m["fecha_hora"])
        ])

    # Ajustar ancho de columnas proporcionalmente
    col_widths = [80, 50, 50, 60, 80, 70, 100]  # en puntos
    table = Table(data, colWidths=col_widths, hAlign='CENTER')

    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('GRID',(0,0),(-1,-1),1,colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9)
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer,
                     as_attachment=True,
                     download_name="reporte_movimientos.pdf",
                     mimetype="application/pdf")


@app.route("/operativo/empleados_horarios")
def empleados_horarios():
    # Validar rol
    if "rol" not in session or session["rol"] != "operativo":
        return redirect("/login")

    conn = get_db_connection()
    if not conn:
        return "Error al conectar con la base de datos."

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        query = """
            SELECT 
                u.id,
                u.nombre,
                u.rol,
                h.hora_entrada,
                h.hora_salida,
                h.hora_comida,
                h.dias_descanso
            FROM usuarios u
            LEFT JOIN horarios_empleados h ON h.usuario_id = u.id
            ORDER BY u.nombre ASC
        """
        cursor.execute(query)
        empleados = cursor.fetchall()
    finally:
        conn.close()

    return render_template("empleados_horarios.html", empleados=empleados)

if __name__ == "__main__":
    # Configuración de puerto dinámica adaptada para entornos de producción en la nube (Azure)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
