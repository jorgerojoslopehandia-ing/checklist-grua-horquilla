import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import hashlib
import os
from PIL import Image
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# --- CONFIGURACIÓN DE BASE DE DATOS ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "checklist_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# --- CONFIGURACIÓN DE EMAIL ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "your_email@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_password")

# --- FUNCIONES DE BASE DE DATOS ---
def get_db_connection():
    """Establece conexión con PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except Exception as e:
        st.error(f"Error de conexión a BD: {e}")
        return None

def init_database():
    """Inicializa las tablas necesarias"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        
        # Tabla de usuarios
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                nombre_completo VARCHAR(100),
                email VARCHAR(100),
                rol VARCHAR(20),
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla de checklists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS checklists (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id),
                nombre_operador VARCHAR(100) NOT NULL,
                numero_equipo VARCHAR(50) NOT NULL,
                fecha DATE NOT NULL,
                hora TIME DEFAULT CURRENT_TIME,
                turno VARCHAR(20),
                datos_inspeccion JSONB,
                falla_critica BOOLEAN DEFAULT FALSE,
                guardado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla de fotos
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fotos_checklist (
                id SERIAL PRIMARY KEY,
                checklist_id INTEGER REFERENCES checklists(id),
                item_nombre VARCHAR(100),
                foto BYTEA,
                fecha_carga TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla de alertas críticas
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id SERIAL PRIMARY KEY,
                checklist_id INTEGER REFERENCES checklists(id),
                descripcion TEXT,
                severidad VARCHAR(20),
                fecha_alerta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resuelta BOOLEAN DEFAULT FALSE
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    return False

# --- FUNCIONES DE AUTENTICACIÓN ---
def hash_password(password):
    """Hashea la contraseña"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, password, nombre_completo, email, rol="operador"):
    """Crea un nuevo usuario"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        try:
            hashed_pw = hash_password(password)
            cur.execute("""
                INSERT INTO usuarios (username, password, nombre_completo, email, rol)
                VALUES (%s, %s, %s, %s, %s)
            """, (username, hashed_pw, nombre_completo, email, rol))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except psycopg2.IntegrityError:
            st.error("El usuario ya existe")
            return False
    return False

def authenticate_user(username, password):
    """Autentica un usuario"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        hashed_pw = hash_password(password)
        cur.execute("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, hashed_pw))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    return None

# --- FUNCIONES DE EMAIL ---
def send_alert_email(email_destinatario, numero_equipo, items_criticos):
    """Envía alerta por email de fallas críticas"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = email_destinatario
        msg['Subject'] = f"⚠️ ALERTA: Falla Crítica en Grúa {numero_equipo}"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>⚠️ ALERTA DE SEGURIDAD</h2>
                <p>Se ha detectado una falla crítica en el equipo:</p>
                <p><strong>Grúa N°: {numero_equipo}</strong></p>
                <p><strong>Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}</strong></p>
                <h3>Ítems Críticos con Problemas:</h3>
                <ul>
                    {''.join([f'<li>{item}</li>' for item in items_criticos])}
                </ul>
                <p style="color: red;"><strong>⛔ EQUIPO FUERA DE SERVICIO</strong></p>
                <p>Por favor, contacte mantenimiento inmediatamente.</p>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error enviando email: {e}")
        return False

# --- FUNCIONES DE ALMACENAMIENTO ---
def guardar_checklist(usuario_id, nombre_operador, numero_equipo, fecha, turno, respuestas, falla_critica, fotos=None):
    """Guarda el checklist en la base de datos"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        try:
            import json
            
            cur.execute("""
                INSERT INTO checklists 
                (usuario_id, nombre_operador, numero_equipo, fecha, turno, datos_inspeccion, falla_critica)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (usuario_id, nombre_operador, numero_equipo, fecha, turno, json.dumps(respuestas), falla_critica))
            
            checklist_id = cur.fetchone()[0]
            
            # Guardar fotos si existen
            if fotos:
                for item, foto_data in fotos.items():
                    cur.execute("""
                        INSERT INTO fotos_checklist (checklist_id, item_nombre, foto)
                        VALUES (%s, %s, %s)
                    """, (checklist_id, item, foto_data))
            
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"Error guardando checklist: {e}")
            return False
    return False

def registrar_alerta(checklist_id, descripcion, severidad):
    """Registra una alerta crítica"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO alertas (checklist_id, descripcion, severidad)
            VALUES (%s, %s, %s)
        """, (checklist_id, descripcion, severidad))
        conn.commit()
        cur.close()
        conn.close()
        return True
    return False

def obtener_historial_checklists(usuario_id=None, limite=30):
    """Obtiene el historial de checklists"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if usuario_id:
            cur.execute("""
                SELECT * FROM checklists 
                WHERE usuario_id = %s 
                ORDER BY guardado_en DESC 
                LIMIT %s
            """, (usuario_id, limite))
        else:
            cur.execute("""
                SELECT * FROM checklists 
                ORDER BY guardado_en DESC 
                LIMIT %s
            """, (limite,))
        
        resultados = cur.fetchall()
        cur.close()
        conn.close()
        return resultados
    return []

def obtener_kpis_mensuales():
    """Obtiene KPIs mensuales desde la BD"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Obtener datos del mes actual
        cur.execute("""
            SELECT datos_inspeccion 
            FROM checklists 
            WHERE DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        
        resultados = cur.fetchall()
        cur.close()
        conn.close()
        
        # Procesar resultados
        import json
        conteo = {'Bueno': 0, 'Regular': 0, 'Malo': 0}
        
        for row in resultados:
            datos = json.loads(row['datos_inspeccion'])
            for estado in datos.values():
                if estado in conteo:
                    conteo[estado] += 1
        
        return conteo
    return {'Bueno': 0, 'Regular': 0, 'Malo': 0}

def obtener_disponibilidad():
    """Calcula disponibilidad de equipos"""
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Total de checklists este mes
        cur.execute("""
            SELECT COUNT(*) as total FROM checklists 
            WHERE DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
        """)
        total = cur.fetchone()['total']
        
        # Checklists sin falla crítica
        cur.execute("""
            SELECT COUNT(*) as disponibles FROM checklists 
            WHERE DATE_TRUNC('month', fecha) = DATE_TRUNC('month', CURRENT_DATE)
            AND falla_critica = FALSE
        """)
        disponibles = cur.fetchone()['disponibles']
        
        cur.close()
        conn.close()
        
        if total > 0:
            return int((disponibles / total) * 100)
        return 0
    return 0

# --- FUNCIONES DE EXPORTACIÓN ---
def exportar_pdf_checklist(checklist_data):
    """Genera un PDF del checklist"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor='#1f77b4',
        spaceAfter=12
    )
    
    # Título
    elements.append(Paragraph("📋 Checklist Diario: Grúa Horquilla", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Datos generales
    general_data = [
        ['Operador:', checklist_data['nombre_operador']],
        ['N° Equipo:', checklist_data['numero_equipo']],
        ['Fecha:', str(checklist_data['fecha'])],
        ['Turno:', checklist_data['turno']]
    ]
    
    general_table = Table(general_data, colWidths=[2*inch, 2*inch])
    general_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), '#E8E8E8'),
        ('TEXTCOLOR', (0, 0), (-1, -1), '#000000'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, '#CCCCCC')
    ]))
    
    elements.append(general_table)
    elements.append(Spacer(1, 0.3*inch))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

def exportar_csv_historial(historial):
    """Genera CSV del historial"""
    df = pd.DataFrame(historial)
    return df.to_csv(index=False).encode('utf-8')

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Checklist Grúa Horquilla", layout="wide", initial_sidebar_state="expanded")

# Inicializar base de datos
if 'db_initialized' not in st.session_state:
    init_database()
    st.session_state.db_initialized = True

# --- SISTEMA DE AUTENTICACIÓN ---
if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 Acceso al Sistema")
    
    tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])
    
    with tab1:
        st.subheader("Iniciar Sesión")
        username = st.text_input("Usuario", key="login_user")
        password = st.text_input("Contraseña", type="password", key="login_pass")
        
        if st.button("Entrar"):
            user = authenticate_user(username, password)
            if user:
                st.session_state.user = user
                st.success("¡Sesión iniciada!")
                st.rerun()
            else:
                st.error("Usuario o contraseña inválidos")
    
    with tab2:
        st.subheader("Crear Nueva Cuenta")
        new_username = st.text_input("Nuevo Usuario", key="reg_user")
        new_password = st.text_input("Contraseña", type="password", key="reg_pass")
        new_email = st.text_input("Email", key="reg_email")
        new_nombre = st.text_input("Nombre Completo", key="reg_nombre")
        
        if st.button("Registrarse"):
            if create_user(new_username, new_password, new_nombre, new_email):
                st.success("¡Cuenta creada! Inicia sesión ahora.")
            else:
                st.error("Error al crear la cuenta")
else:
    # --- USUARIO AUTENTICADO ---
    
    # Sidebar
    with st.sidebar:
        st.write(f"👤 **{st.session_state.user['nombre_completo']}**")
        st.write(f"Rol: {st.session_state.user['rol'].upper()}")
        
        if st.button("Cerrar Sesión"):
            st.session_state.user = None
            st.rerun()
    
    st.title("📋 Checklist Diario: Grúa Horquilla")
    
    # --- SECCIÓN 1: DATOS GENERALES ---
    with st.expander("Datos del Operador y Equipo", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            nombre = st.text_input("Nombre del Operador", value=st.session_state.user['nombre_completo'])
            equipo = st.text_input("N° de Equipo / Grúa")
        with col2:
            fecha = st.date_input("Fecha", datetime.now())
            turno = st.selectbox("Turno", ["Día", "Tarde", "Noche"])
            hora = st.time_input("Hora de Inspección", datetime.now().time())
    
    # --- SECCIÓN 2: VERIFICACIÓN ---
    st.header("Evaluación de Estado")
    opciones = ["Bueno", "Regular", "Malo"]
    
    items_visual = [
        "Cabina", "Techo (ROPS)", "Espejos", "Extintor (Carga)", 
        "Parabrisas", "Batería", "Nivel Electrolito", "Neumáticos", "Horquillas"
    ]
    
    items_op = [
        "Frenos", "Dirección", "Bocina", "Alarma Retroceso", 
        "Luces", "Sistema Elevación", "Cinturón de Seguridad"
    ]
    
    respuestas = {}
    fotos = {}
    
    st.subheader("Verificación Visual y Operacional")
    cols = st.columns(2)
    
    for i, item in enumerate(items_visual + items_op):
        with cols[i % 2]:
            respuestas[item] = st.radio(f"{item}", opciones, horizontal=True, key=item)
            
            # Opción para cargar foto
            foto = st.file_uploader(f"Foto de {item} (opcional)", type=["jpg", "jpeg", "png"], key=f"foto_{item}")
            if foto:
                fotos[item] = foto.read()
    
    # --- LÓGICA DE SEGURIDAD ---
    items_criticos = ["Extintor (Carga)", "Frenos", "Dirección", "Cinturón de Seguridad"]
    items_criticos_malos = [critico for critico in items_criticos if respuestas[critico] == "Malo"]
    falla_critica = len(items_criticos_malos) > 0
    
    if falla_critica:
        st.error("⚠️ ¡ATENCIÓN! El equipo presenta fallas en ítems críticos. DEBE QUEDAR FUERA DE SERVICIO.")
        st.write("**Ítems críticos con problemas:**")
        for item in items_criticos_malos:
            st.write(f"- {item}")
    
    # --- BOTÓN DE GUARDADO ---
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("💾 Guardar Checklist"):
            if nombre and equipo:
                if guardar_checklist(
                    st.session_state.user['id'],
                    nombre,
                    equipo,
                    fecha,
                    turno,
                    respuestas,
                    falla_critica,
                    fotos if fotos else None
                ):
                    st.success("¡Datos guardados correctamente!")
                    
                    # Registrar alerta si hay falla crítica
                    if falla_critica:
                        registrar_alerta(
                            None,
                            f"Equipo {equipo} con fallas críticas: {', '.join(items_criticos_malos)}",
                            "CRITICA"
                        )
                        
                        # Enviar email de alerta
                        if st.session_state.user['email']:
                            send_alert_email(
                                st.session_state.user['email'],
                                equipo,
                                items_criticos_malos
                            )
                else:
                    st.error("Error al guardar el checklist")
            else:
                st.warning("Por favor completa nombre y número de equipo")
    
    with col_btn2:
        if st.button("📄 Exportar a PDF"):
            checklist_data = {
                'nombre_operador': nombre,
                'numero_equipo': equipo,
                'fecha': fecha,
                'turno': turno
            }
            pdf = exportar_pdf_checklist(checklist_data)
            st.download_button(
                label="Descargar PDF",
                data=pdf,
                file_name=f"checklist_{equipo}_{fecha}.pdf",
                mime="application/pdf"
            )
    
    # --- SECCIÓN 3: DASHBOARD Y KPIs ---
    st.divider()
    st.header("📊 Dashboard Mensual de KPIs")
    
    # Obtener KPIs reales desde BD
    kpis = obtener_kpis_mensuales()
    disponibilidad = obtener_disponibilidad()
    
    col_graf1, col_graf2 = st.columns(2)
    
    with col_graf1:
        df_kpi = pd.DataFrame({
            'Categoría': ['Bueno', 'Regular', 'Malo'],
            'Cantidad': [kpis['Bueno'], kpis['Regular'], kpis['Malo']]
        })
        
        if df_kpi['Cantidad'].sum() > 0:
            fig1 = px.pie(
                df_kpi, 
                values='Cantidad', 
                names='Categoría', 
                title="Estado General de la Flota (Mes)",
                color='Categoría', 
                color_discrete_map={'Bueno':'green', 'Regular':'orange', 'Malo':'red'}
            )
            st.plotly_chart(fig1)
        else:
            st.info("No hay datos disponibles aún")
    
    with col_graf2:
        st.metric(label="Disponibilidad de Equipos", value=f"{disponibilidad}%")
        
        # Ítems más frecuentes con problemas
        historial = obtener_historial_checklists(limite=100)
        if historial:
            st.write("*Datos actualizados desde la base de datos*")
    
    # --- SECCIÓN 4: HISTORIAL DE CHECKLISTS ---
    if st.session_state.user['rol'] == 'admin':
        st.divider()
        st.header("📋 Historial de Checklists")
        
        historial = obtener_historial_checklists()
        if historial:
            df_historial = pd.DataFrame(historial)
            st.dataframe(df_historial, use_container_width=True)
            
            # Botón para exportar historial
            csv = exportar_csv_historial(historial)
            st.download_button(
                label="Descargar Historial (CSV)",
                data=csv,
                file_name=f"historial_checklists_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No hay registros disponibles")
