import streamlit as st
from supabase import create_client
import pandas as pd
import datetime
import hashlib
import os
import base64
import zipfile
import io
import xml.etree.ElementTree as ET
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Control Financiero", page_icon="💼", layout="wide")

# Estilos CSS
st.markdown("""
    <style>
        .main { background-color: #f8f9fa; }
        .metric-card {
            background-color: #ffffff; border: 1px solid #e3e6f0;
            border-radius: 10px; padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02); margin-bottom: 15px;
        }
        .metric-title {
            font-size: 13px; font-weight: 600; color: #6c757d;
            text-transform: uppercase; margin-bottom: 5px;
        }
        .metric-value { font-size: 22px; font-weight: 700; color: #2e384d; }
        .metric-sub { font-size: 11px; color: #4e73df; margin-top: 5px; }
        .success-text { color: #1cc88a; font-weight: bold; }
        @media (max-width: 768px) { .login-container { margin-top: 20px !important; } }
    </style>
""", unsafe_allow_html=True)

# --- CONEXIÓN A SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Función para encriptar contraseñas
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Función para procesar y leer los XML (CFDIs) a prueba de balas
def procesar_cfdi(xml_content, rfc_activo):
    try:
        # Limpiar el BOM (Byte Order Mark) invisible del SAT
        if xml_content.startswith(b'\xef\xbb\xbf'):
            xml_content = xml_content[3:]
        
        root = ET.fromstring(xml_content)

        uuid = None
        emisor_rfc = ""
        receptor_rfc = ""
        subtotal = 0.0
        total = 0.0
        fecha_str = ""
        iva = 0.0

        fecha_str = root.attrib.get('Fecha', '')
        subtotal = float(root.attrib.get('SubTotal', 0) or 0)
        total = float(root.attrib.get('Total', 0) or 0)

        for el in root.iter():
            tag = el.tag.split('}')[-1].lower() 
            
            if tag == 'timbrefiscaldigital':
                uuid = el.attrib.get('UUID')
            elif tag == 'emisor' and not emisor_rfc:
                emisor_rfc = el.attrib.get('Rfc', '').upper().strip()
            elif tag == 'receptor' and not receptor_rfc:
                receptor_rfc = el.attrib.get('Rfc', '').upper().strip()
            elif tag == 'traslado':
                if el.attrib.get('Impuesto') == '002':
                    importe = el.attrib.get('Importe')
                    if importe: iva += float(importe)

        if not uuid: return None

        if emisor_rfc == rfc_activo: tipo = 'INGRESO'
        elif receptor_rfc == rfc_activo: tipo = 'GASTO'
        else: return None 

        return {
            "uuid_cfdi": uuid.lower(),
            "emisor_rfc": emisor_rfc,      
            "receptor_rfc": receptor_rfc,  
            "fecha_emision": fecha_str.split('T')[0] if 'T' in fecha_str else fecha_str,
            "tipo": tipo,
            "subtotal": subtotal,
            "impuestos": iva,
            "total": total
        }
    except Exception as e:
        print(f"Error procesando XML: {e}")
        return None

# --- SISTEMA DE INICIO DE SESIÓN Y REGISTRO ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['role'] = None
    st.session_state['email'] = None

if not st.session_state['logged_in']:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>💼 Portal Empresarial</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("<div class='metric-card login-container'>", unsafe_allow_html=True)
        
        tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])
        
        with tab_login:
            log_email = st.text_input("Correo Electrónico", key="log_email")
            log_pass = st.text_input("Contraseña", type="password", key="log_pass")
            if st.button("Ingresar", use_container_width=True, type="primary"):
                if log_email and log_pass:
                    res = supabase.table("usuarios").select("*").eq("email", log_email.lower()).execute()
                    if res.data:
                        user_db = res.data[0]
                        if user_db["password_hash"] == hash_password(log_pass):
                            if user_db["aprobado"]:
                                st.session_state['logged_in'] = True
                                st.session_state['role'] = user_db["rol"]
                                st.session_state['email'] = user_db["email"]
                                st.rerun()
                            else:
                                st.warning("⏳ Tu cuenta está pendiente de aprobación por el Administrador.")
                        else:
                            st.error("❌ Contraseña incorrecta.")
                    else:
                        st.error("❌ El usuario no existe.")
                else:
                    st.warning("Completa los campos.")

        with tab_registro:
            reg_email = st.text_input("Correo Electrónico", key="reg_email")
            reg_pass1 = st.text_input("Contraseña", type="password", key="reg_pass1")
            reg_pass2 = st.text_input("Confirmar Contraseña", type="password", key="reg_pass2")
            
            if st.button("Crear Cuenta", use_container_width=True):
                if reg_email and reg_pass1 and reg_pass2:
                    if reg_pass1 == reg_pass2:
                        check_exist = supabase.table("usuarios").select("id").eq("email", reg_email.lower()).execute()
                        if check_exist.data:
                            st.error("⚠️ Este correo ya está registrado.")
                        else:
                            total_users = supabase.table("usuarios").select("id").execute()
                            is_first_user = len(total_users.data) == 0
                            
                            nuevo_rol = "admin" if is_first_user else "socio"
                            nuevo_estatus = True if is_first_user else False
                            
                            supabase.table("usuarios").insert({
                                "email": reg_email.lower(),
                                "password_hash": hash_password(reg_pass1),
                                "rol": nuevo_rol,
                                "aprobado": nuevo_estatus
                            }).execute()
                            
                            if is_first_user:
                                st.success("✅ ¡Cuenta fundadora creada! Eres Administrador. Ya puedes iniciar sesión.")
                            else:
                                st.success("✅ ¡Cuenta creada! Espera a que el Administrador apruebe tu acceso.")
                    else:
                        st.error("❌ Las contraseñas no coinciden.")
                else:
                    st.warning("Completa todos los campos.")
                    
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop() 

is_admin = st.session_state['role'] == "admin"
user_role_lower = str(st.session_state.get('role', '')).lower()
puede_ver_sat = is_admin or ('contador' in user_role_lower)

# --- BARRA LATERAL Y SELECTOR DE ENTORNO ---
st.sidebar.markdown(f"👤 **{st.session_state['email']}**")
st.sidebar.markdown(f"🏷️ Rol: `{st.session_state['role'].upper()}`")
st.sidebar.button("🚪 Cerrar Sesión", on_click=lambda: st.session_state.update({'logged_in': False, 'role': None, 'email': None}), use_container_width=True)

st.sidebar.markdown("---")

if is_admin:
    st.sidebar.markdown("### 🏢 Cambiar de Entorno")
    perfil_activo = st.sidebar.radio("Selecciona el perfil de trabajo:", ["Operación Nicole", "Mis Finanzas (Carlos)"])
else:
    perfil_activo = "Operación Nicole"

if perfil_activo == "Operación Nicole":
    RFC_ACTIVO = "GAMN050420SZ1"
else:
    RFC_ACTIVO = "SAMC910720214"

# --- FUNCIONES DE CARGA DE DATOS ---
@st.cache_data(ttl=30)
def cargar_datos():
    response = supabase.table("facturas").select("*").execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame()

@st.cache_data(ttl=30)
def cargar_conceptos():
    try:
        response = supabase.table("conceptos").select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def cargar_insumos_guardados():
    try:
        response = supabase.table("registro_insumos").select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def cargar_prestamos():
    try:
        response = supabase.table("prestamos_banco").select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def cargar_retiros_mayorista():
    try:
        response = supabase.table("retiros_socio_mayorista").select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def cargar_configuracion():
    config = {
        "porcentaje_carlos_op": 0.75,
        "porcentaje_cesar_op": 0.25,
        "porcentaje_carlos_iva": 0.40,
        "porcentaje_cesar_iva": 0.60,
        "cuota_nicole": 2000.00
    }
    try:
        res = supabase.table("configuracion_global").select("*").execute()
        if res.data:
            for row in res.data:
                config[row["clave"]] = float(row["valor"])
    except Exception:
        pass
    return config

# --- PROCESAMIENTO GLOBAL ---
cfg = cargar_configuracion()
df_global = cargar_datos()

if df_global.empty:
    st.warning("⚠️ No hay facturas registradas en la base de datos todavía. Descarga desde el SAT para comenzar.")
    df_global = pd.DataFrame(columns=['id', 'uuid_cfdi', 'emisor_rfc', 'receptor_rfc', 'fecha_emision', 'tipo', 'subtotal', 'impuestos', 'total'])
else:
    df_global['fecha_emision'] = pd.to_datetime(df_global['fecha_emision'])
    df_global['Mes_Año'] = df_global['fecha_emision'].dt.to_period('M').astype(str)

st.sidebar.title("⚙️ Filtros de Fecha")
meses_disponibles = sorted(df_global['Mes_Año'].unique(), reverse=True) if 'Mes_Año' in df_global.columns else []
mes_seleccionado = st.sidebar.selectbox("Mes de Emisión", ["Todos los meses"] + meses_disponibles)

if mes_seleccionado != "Todos los meses":
    df_filtrado_fecha = df_global[df_global['Mes_Año'] == mes_seleccionado].copy()
else:
    df_filtrado_fecha = df_global.copy()

if 'emisor_rfc' not in df_filtrado_fecha.columns:
    df_filtrado_fecha['emisor_rfc'] = ''
if 'receptor_rfc' not in df_filtrado_fecha.columns:
    df_filtrado_fecha['receptor_rfc'] = ''

df_filtrado_fecha['emisor_rfc'] = df_filtrado_fecha['emisor_rfc'].fillna('').astype(str).str.strip().str.upper()
df_filtrado_fecha['receptor_rfc'] = df_filtrado_fecha['receptor_rfc'].fillna('').astype(str).str.strip().str.upper()

for col in ['subtotal', 'impuestos', 'total']:
    if col in df_filtrado_fecha.columns:
        df_filtrado_fecha[col] = pd.to_numeric(df_filtrado_fecha[col], errors='coerce').fillna(0.0)

# AISLAMIENTO SEGURO
if perfil_activo == "Mis Finanzas (Carlos)":
    df_entorno = df_filtrado_fecha[
        (df_filtrado_fecha['emisor_rfc'] == 'SAMC910720214') | 
        (df_filtrado_fecha['receptor_rfc'] == 'SAMC910720214')
    ].copy()
else:
    df_entorno = df_filtrado_fecha[
        (df_filtrado_fecha['emisor_rfc'] != 'SAMC910720214') & 
        (df_filtrado_fecha['receptor_rfc'] != 'SAMC910720214')
    ].copy()


# ==============================================================================
# ENTORNO 1: OPERACIÓN NICOLE
# ==============================================================================
if perfil_activo == "Operación Nicole":

    ingresos_df = df_entorno[df_entorno['tipo'] == 'INGRESO'].copy()
    gastos_df = df_entorno[df_entorno['tipo'] == 'GASTO'].copy()

    subtotal_ingresos = float(ingresos_df['subtotal'].sum()) if not ingresos_df.empty else 0.0
    t_ingresos = float(ingresos_df['total'].sum()) if not ingresos_df.empty else 0.0
    t_gastos = float(gastos_df['total'].sum()) if not gastos_df.empty else 0.0
    t_iva_ingresos = float(ingresos_df['impuestos'].sum()) if not ingresos_df.empty else 0.0
    t_iva_gastos = float(gastos_df['impuestos'].sum()) if not gastos_df.empty else 0.0
    iva_por_pagar = t_iva_ingresos - t_iva_gastos
    
    def calcular_isr_resico(subtotal):
        if subtotal <= 25000: return subtotal * 0.01, "1.0%"
        elif subtotal <= 50000: return subtotal * 0.011, "1.1%"
        elif subtotal <= 83333.33: return subtotal * 0.015, "1.5%"
        elif subtotal <= 208333.33: return subtotal * 0.02, "2.0%"
        else: return subtotal * 0.025, "2.5%"

    monto_isr, tasa_isr = calcular_isr_resico(subtotal_ingresos)
    balance_neto = t_ingresos - t_gastos

    tab_names = ["📊 Dashboard Fiscal", "💰 Ingresos", "💸 Egresos", "🤝 Cierre de Socios", "💵 Retiros Mayorista"]
    if is_admin:
        tab_names.insert(3, "🛒 Registro Insumos")
        tab_names.append("🔐 Mi Panel Privado")
        tab_names.append("👥 Gestión Usuarios")

    if puede_ver_sat:
        tab_names.append("📥 Conexión SAT")

    tabs = st.tabs(tab_names)
    def get_tab(name): return tabs[tab_names.index(name)]

    with get_tab("📊 Dashboard Fiscal"):
        st.title(f"💼 Dashboard Fiscal RESICO ({'CEO' if is_admin else 'Socio'})")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #e74a3b;"><div class="metric-title">IVA Neto a Pagar</div><div class="metric-value" style="color: #e74a3b;">${iva_por_pagar:,.2f}</div></div>""", unsafe_allow_html=True)
        with c2: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #f6c23e;"><div class="metric-title">ISR Estimado (RESICO)</div><div class="metric-value" style="color: #f4b619;">${monto_isr:,.2f}</div></div>""", unsafe_allow_html=True)
        with c3: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #1cc88a;"><div class="metric-title">Subtotal Facturado</div><div class="metric-value" style="color: #1cc88a;">${subtotal_ingresos:,.2f}</div></div>""", unsafe_allow_html=True)
        with c4: st.markdown(f"""<div class="metric-card"><div class="metric-title">Balance Operativo</div><div class="metric-value">${balance_neto:,.2f}</div></div>""", unsafe_allow_html=True)

    with get_tab("💰 Ingresos"):
        st.title("💰 Ingresos Emitidos")
        if not ingresos_df.empty: st.dataframe(ingresos_df, use_container_width=True)

    with get_tab("💸 Egresos"):
        st.title("💸 Egresos (Gastos Deducibles)")
        if not gastos_df.empty: st.dataframe(gastos_df, use_container_width=True)

    if is_admin:
        with get_tab("🛒 Registro Insumos"):
            st.title("🛒 Registro de Insumos")
            lista_ids_ingresos = ingresos_df['id'].astype(str).tolist() if ('id' in ingresos_df.columns and not ingresos_df.empty) else []

            st.markdown("### ⚡ 1. Cargar desde Base de Datos")
            c_id, c_btn = st.columns([3, 1])
            with c_id:
                id_auto = st.selectbox("ID de Factura de Ingreso", [""] + lista_ids_ingresos, key="auto_id")
            with c_btn:
                st.write("") 
                if st.button("📥 Autocompletar Filas", use_container_width=True):
                    if id_auto != "":
                        fila_ingreso = ingresos_df[ingresos_df['id'].astype(str) == id_auto].iloc[0]
                        uuid_factura = str(fila_ingreso['uuid_cfdi']).strip().lower()
                        fecha_factura = fila_ingreso['fecha_emision'].strftime('%d/%m/%Y')
                        
                        df_conceptos = cargar_conceptos()
                        
                        if not df_conceptos.empty and 'uuid_cfdi' in df_conceptos.columns:
                            df_conceptos['uuid_cfdi_lower'] = df_conceptos['uuid_cfdi'].astype(str).str.strip().str.lower()
                            conceptos_factura = df_conceptos[df_conceptos['uuid_cfdi_lower'] == uuid_factura]
                            
                            if not conceptos_factura.empty:
                                nuevas_filas = []
                                for _, c in conceptos_factura.iterrows():
                                    cant = float(c['cantidad']) if pd.notnull(c['cantidad']) else 1.0
                                    vu = float(c['valor_unitario']) if pd.notnull(c['valor_unitario']) else 0.0
                                    tot = cant * vu
                                    
                                    nuevas_filas.append({
                                        "Fecha": fecha_factura, "Factura (ID)": str(id_auto),
                                        "Cantidad": str(c['cantidad']), "Concepto": str(c['descripcion']),
                                        "P/U": vu, "Total": tot, "Link de Compra": "",
                                        "Ganancia .25": tot * 0.25, "Total_Final": tot * 1.25
                                    })
                                
                                df_nuevas = pd.DataFrame(nuevas_filas)
                                df_actual = st.session_state.df_insumos
                                df_actual = df_actual[df_actual['Factura (ID)'] != ""]
                                
                                st.session_state.df_insumos = pd.concat([df_actual, df_nuevas], ignore_index=True)
                                st.rerun()
                            else:
                                st.warning("⚠️ No se encontraron productos para esta factura.")
                        else:
                            st.warning("⚠️ La tabla de 'conceptos' no existe o está vacía.")
            
            st.divider()

            st.markdown("### 📝 2. Edición Manual")
            if 'df_insumos' not in st.session_state:
                st.session_state.df_insumos = pd.DataFrame({
                    "Fecha": [""] * 5, "Factura (ID)": [""] * 5, "Cantidad": [""] * 5,
                    "Concepto": [""] * 5, "P/U": [0.0] * 5, "Total": [0.0] * 5,
                    "Link de Compra": [""] * 5, "Ganancia .25": [0.0] * 5, "Total_Final": [0.0] * 5
                })

            edited_df = st.data_editor(
                st.session_state.df_insumos, num_rows="dynamic", use_container_width=True, hide_index=True,
                disabled=["Ganancia .25", "Total_Final"], 
                column_config={
                    "Factura (ID)": st.column_config.SelectboxColumn("Factura (ID)", options=lista_ids_ingresos, width="medium"),
                    "P/U": st.column_config.NumberColumn("P/U", format="$%.2f"),
                    "Total": st.column_config.NumberColumn("Total", format="$%.2f"),
                    "Ganancia .25": st.column_config.NumberColumn("Ganancia .25", format="$%.2f"),
                    "Total_Final": st.column_config.NumberColumn("Total_Final", format="$%.2f")
                }
            )

            edited_df['Total'] = pd.to_numeric(edited_df['Total'], errors='coerce').fillna(0)
            edited_df['Ganancia .25'] = edited_df['Total'] * 0.25
            edited_df['Total_Final'] = edited_df['Total'] + edited_df['Ganancia .25']

            if not edited_df[['Fecha', 'Factura (ID)', 'Cantidad', 'Concepto', 'P/U', 'Total', 'Link de Compra']].equals(
                st.session_state.df_insumos[['Fecha', 'Factura (ID)', 'Cantidad', 'Concepto', 'P/U', 'Total', 'Link de Compra']]
            ):
                st.session_state.df_insumos = edited_df
                st.rerun()

            st.divider()
            
            st.markdown("### 💾 3. Guardar en Base de Datos")
            if st.button("Guardar Insumos Definitivos", type="primary", use_container_width=True):
                filas_validas = edited_df[edited_df['Factura (ID)'] != ""].dropna(subset=['Factura (ID)'])
                if not filas_validas.empty:
                    ids_a_guardar = filas_validas['Factura (ID)'].unique().tolist()
                    for fid in ids_a_guardar:
                        supabase.table("registro_insumos").delete().eq("factura_id", str(fid)).execute()
                    
                    datos_insertar = []
                    for _, row in filas_validas.iterrows():
                        datos_insertar.append({
                            "fecha": str(row['Fecha']), "factura_id": str(row['Factura (ID)']),
                            "cantidad": str(row['Cantidad']), "concepto": str(row['Concepto']),
                            "precio_unitario": float(row['P/U']), "total": float(row['Total']),
                            "link_compra": str(row['Link de Compra']) if pd.notna(row['Link de Compra']) else "",
                            "ganancia": float(row['Ganancia .25']), "total_final": float(row['Total_Final'])
                        })
                    
                    supabase.table("registro_insumos").insert(datos_insertar).execute()
                    st.cache_data.clear()
                    st.session_state.df_insumos = pd.DataFrame({
                        "Fecha": [""] * 5, "Factura (ID)": [""] * 5, "Cantidad": [""] * 5,
                        "Concepto": [""] * 5, "P/U": [0.0] * 5, "Total": [0.0] * 5,
                        "Link de Compra": [""] * 5, "Ganancia .25": [0.0] * 5, "Total_Final": [0.0] * 5
                    })
                    st.success("✅ ¡Insumos guardados de forma permanente!")
                    st.rerun()
                else:
                    st.warning("No hay datos llenos para guardar.")

            with st.expander("Ver histórico de insumos guardados (Solo lectura)"):
                st.dataframe(cargar_insumos_guardados(), use_container_width=True)

    # --- PROCESAMIENTO CENTRAL DE NICOLE ---
    df_insumos_db = cargar_insumos_guardados()
    
    datos_socios_publico = []
    datos_socios_privado = []
    bolsa_10_acumulada = 0
    carlos_inversion_real = 0
    carlos_ganancia_insumos = 0
    carlos_total_recuperado = 0

    if not ingresos_df.empty:
        def calcular_pago_lunes(fecha_emision):
            fecha_base = fecha_emision + pd.Timedelta(days=15)
            dias_para_lunes = (0 - fecha_base.weekday()) % 7
            return fecha_base + pd.Timedelta(days=dias_para_lunes)

        for idx, row in ingresos_df.iterrows():
            id_factura = str(row['id']) if 'id' in row else ""
            subtotal = row['subtotal']
            iva = row['impuestos']
            total_factura_banco = subtotal + iva  
            fecha_pago_real = calcular_pago_lunes(row['fecha_emision'])
            
            costo_insumos_carlos, inversion_neta, ganancia_neta_25 = 0, 0, 0
            
            if not df_insumos_db.empty and 'factura_id' in df_insumos_db.columns:
                insumos = df_insumos_db[df_insumos_db['factura_id'].astype(str) == id_factura]
                if not insumos.empty:
                    inversion_neta = pd.to_numeric(insumos['total']).sum()
                    ganancia_neta_25 = pd.to_numeric(insumos['ganancia']).sum()
                    costo_insumos_carlos = pd.to_numeric(insumos['total_final']).sum() 
                    
                    carlos_inversion_real += inversion_neta
                    carlos_ganancia_insumos += ganancia_neta_25
                    carlos_total_recuperado += costo_insumos_carlos
            
            total_base = subtotal - costo_insumos_carlos
            bolsa_factura_10 = total_base * 0.10
            entrega_mayorista = total_base - bolsa_factura_10
            
            bolsa_10_acumulada += bolsa_factura_10

            datos_socios_publico.append({
                "Cobro (Lunes)": fecha_pago_real.strftime('%d/%m/%Y'),
                "Factura (ID)": id_factura,
                "Subtotal": subtotal, "IVA": iva,
                "Total Factura (Banco)": total_factura_banco, 
                "Base para Reparto": total_base,
                "(-).10 Socios": bolsa_factura_10,
                "Entrega Mayorista": entrega_mayorista
            })

            if is_admin:
                datos_socios_privado.append({
                    "Cobro (Lunes)": fecha_pago_real.strftime('%d/%m/%Y'),
                    "Factura (ID)": id_factura,
                    "Subtotal": subtotal, "IVA": iva,
                    "Total Factura (Banco)": total_factura_banco, 
                    "Pago Carlos (Insumos)": costo_insumos_carlos,
                    "Total (Base)": total_base,
                    "(-).10 Carlos/Cesar": bolsa_factura_10,
                    "Entrega Mayorista": entrega_mayorista
                })

        nicole_cuota = cfg["cuota_nicole"]
        sobrante_10 = max(0, bolsa_10_acumulada - nicole_cuota)
        
        carlos_op = sobrante_10 * cfg["porcentaje_carlos_op"]  
        cesar_op = sobrante_10 * cfg["porcentaje_cesar_op"]   

    with get_tab("🤝 Cierre de Socios"):
        st.title("🤝 Cierre de Socios y Fechas de Pago")
        st.markdown("Vista General Directiva (Operación y Estrategia Fiscal)")

        if not ingresos_df.empty:
            df_cierre_pub = pd.DataFrame(datos_socios_publico)
            st.markdown("### 🗓️ 1. Desglose Operativo por Factura")
            st.dataframe(df_cierre_pub, use_container_width=True, hide_index=True, column_config={
                "Subtotal": st.column_config.NumberColumn(format="$%.2f"), 
                "IVA": st.column_config.NumberColumn(format="$%.2f"),
                "Total Factura (Banco)": st.column_config.NumberColumn("Total Factura (Banco)", format="$%.2f"),
                "Base para Reparto": st.column_config.NumberColumn(format="$%.2f"),
                "(-).10 Socios": st.column_config.NumberColumn(format="$%.2f"),
                "Entrega Mayorista": st.column_config.NumberColumn(format="$%.2f")
            })
            
            st.divider()

            st.markdown("### 🏦 2. Estrategia de IVA (Bolsa Fiscal)")
            c1, c2 = st.columns(2)
            with c1: st.info(f"El IVA total cobrado en estas facturas fue de: **${t_iva_ingresos:,.2f}**")
            with c2:
                iva_pagado_sat_pub = st.number_input(
                    "¿Cuánto IVA se le pagó o se le pagará realmente al SAT este mes?", 
                    min_value=0.0, value=float(max(0, iva_por_pagar)), step=100.0, key="iva_pub",
                    disabled=(not is_admin)
                )
            
            iva_rescatado = max(0, t_iva_ingresos - iva_pagado_sat_pub)
            
            carlos_iva = iva_rescatado * cfg["porcentaje_carlos_iva"]  
            cesar_iva = iva_rescatado * cfg["porcentaje_cesar_iva"]   

            st.divider()

            st.markdown("### 📊 3. Resumen de Ganancias Socios")
            tabla_ganancias = pd.DataFrame([
                {"Concepto": "0.10 (Post-Nicole)", "Total": sobrante_10, f"César ({int(cfg['porcentaje_cesar_op']*100)}%)": cesar_op, f"Carlos ({int(cfg['porcentaje_carlos_op']*100)}%)": carlos_op},
                {"Concepto": "IVA Rescatado", "Total": iva_rescatado, f"César ({int(cfg['porcentaje_cesar_iva']*100)}%)": cesar_iva, f"Carlos ({int(cfg['porcentaje_carlos_iva']*100)}%)": carlos_iva}
            ])
            st.dataframe(tabla_ganancias, use_container_width=True, hide_index=True, column_config={
                "Total": st.column_config.NumberColumn(format="$%.2f")
            })

            st.write("")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("#### 👩 Nicole")
                st.metric("Cuota Fija a Transferir", f"${nicole_cuota:,.2f}")
            with col2:
                st.markdown("#### 🧑 César (Contador)")
                st.metric("Total a Transferir", f"${(cesar_op + cesar_iva):,.2f}")
            with col3:
                st.markdown("#### 👨 Carlos")
                st.metric("Total Ganancia Limpia", f"${(carlos_op + carlos_iva):,.2f}")
        else:
            st.info("No hay facturas de ingreso en este periodo.")

    with get_tab("💵 Retiros Mayorista"):
        st.title("💼 Control de Pagos y Retiros - Socio Mayorista")
        st.markdown("Gestión de entregas de capital por factura individual. Las facturas ya liquidadas se ocultan automáticamente de los pendientes.")

        if not ingresos_df.empty:
            df_historial_retiros = cargar_retiros_mayorista()
            ids_facturas_pagadas = []
            if not df_historial_retiros.empty and 'factura_id' in df_historial_retiros.columns:
                ids_facturas_pagadas = df_historial_retiros['factura_id'].astype(str).tolist()

            df_temp = ingresos_df.copy()
            df_temp['fecha_cobro_teorica'] = df_temp['fecha_emision'] + pd.Timedelta(days=15)
            
            def ajustar_a_lunes_exacto(fecha):
                dias_semana = fecha.dayofweek
                if dias_semana == 0:
                    return fecha
                else:
                    return fecha + pd.Timedelta(days=(7 - dias_semana))

            df_temp['fecha_cobro_real'] = df_temp['fecha_cobro_teorica'].apply(ajustar_a_lunes_exacto)
            
            lista_facturas_pendientes = []
            for _, r in df_temp.iterrows():
                fid = str(r['id']) if 'id' in r else ""
                
                if fid in ids_facturas_pagadas:
                    continue
                
                sub = r['subtotal']
                costo_ins = 0
                if not df_insumos_db.empty and 'factura_id' in df_insumos_db.columns:
                    ins = df_insumos_db[df_insumos_db['factura_id'].astype(str) == fid]
                    if not ins.empty:
                        costo_ins = pd.to_numeric(ins['total_final']).sum()
                
                base_rep = sub - costo_ins
                bolsa_10 = base_rep * 0.10
                monto_mayorista_factura = base_rep - bolsa_10
                
                lista_facturas_pendientes.append({
                    "id_factura": fid,
                    "fecha_emision": r['fecha_emision'].strftime('%d/%m/%Y'),
                    "fecha_cobro_lunes": df_temp.loc[_, 'fecha_cobro_real'].strftime('%d/%m/%Y'),
                    "monto_disponible": round(monto_mayorista_factura, 2)
                })
            
            df_pagos_visor = pd.DataFrame(lista_facturas_pendientes)

            st.markdown("### 🗓️ 1. Facturas Pendientes de Pago (Disponibles)")
            if not df_pagos_visor.empty:
                st.dataframe(df_pagos_visor, use_container_width=True, hide_index=True, column_config={
                    "monto_disponible": st.column_config.NumberColumn("Monto para Mayorista", format="$%.2f")
                })
            else:
                st.success("🎉 ¡Todas las facturas emitidas ya han sido liquidadas al socio mayorista!")

            st.divider()

            if is_admin and not df_pagos_visor.empty:
                st.markdown("### 💸 2. Registrar Desglose de Pago (Efectivo / Transferencia)")
                st.info("El sistema validará que la suma del efectivo y la transferencia coincida exactamente con el total asignado a la factura seleccionada.")

                factura_seleccionada_id = st.selectbox("Selecciona la Factura a Pagar", options=df_pagos_visor['id_factura'].tolist())
                
                fila_activa = df_pagos_visor[df_pagos_visor['id_factura'] == factura_seleccionada_id].iloc[0]
                monto_exacto_requerido = float(fila_activa['monto_disponible'])

                st.markdown(f"**Monto exacto requerido para esta factura:** `${monto_exacto_requerido:,.2f} MXN`")

                with st.form("form_retiro_por_factura"):
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        ret_efectivo = st.number_input("Monto en Efectivo ($)", min_value=0.0, max_value=float(monto_exacto_requerido), step=100.0, format="%.2f")
                    with rc2:
                        ret_transferencia = st.number_input("Monto por Transferencia - Bajo Perfil ($)", min_value=0.0, max_value=float(monto_exacto_requerido), step=100.0, format="%.2f")
                    
                    notas_retiro = st.text_area("Concepto / Referencia de Transferencia", placeholder="Ej. Pago factura / Viáticos...")
                    
                    total_capturado = ret_efectivo + ret_transferencia
                    st.write(f"**Suma capturada:** `${total_capturado:,.2f} MXN` / **Requerido:** `${monto_exacto_requerido:,.2f} MXN`")
                    
                    btn_enviar_retiro = st.form_submit_button("Guardar Pago de Factura", type="primary")
                    
                    if btn_enviar_retiro:
                        if abs(total_capturado - monto_exacto_requerido) > 0.05:
                            st.error(f"⚠️ La suma (${total_capturado:,.2f}) no coincide con el monto exacto de la factura (${monto_exacto_requerido:,.2f}). Debe cuadrar al 100%.")
                        else:
                            nuevo_registro_retiro = {
                                "factura_id": factura_seleccionada_id,
                                "mes_corte": datetime.datetime.strptime(fila_activa['fecha_cobro_lunes'], '%d/%m/%Y').month,
                                "anio_corte": datetime.datetime.strptime(fila_activa['fecha_cobro_lunes'], '%d/%m/%Y').year,
                                "monto_efectivo": ret_efectivo,
                                "monto_transferencia": ret_transferencia,
                                "notas": notas_retiro,
                                "registrado_por": st.session_state.get("email", "admin")
                            }
                            try:
                                supabase.table("retiros_socio_mayorista").insert(nuevo_registro_retiro).execute()
                                st.cache_data.clear()
                                st.success("✅ ¡Pago de factura registrado, ocultado de pendientes y validado con éxito!")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Error al guardar en Supabase: {ex}")
            elif not is_admin:
                st.warning("🔒 *Vista exclusiva de auditoría:* Tu cuenta de socio tiene permisos de consulta. Únicamente el Administrador puede registrar o modificar los pagos de caja.")

        else:
            st.info("No hay facturas de ingreso registradas para procesar pagos.")

        st.divider()
        st.markdown("### 📜 Historial de Pagos Registrados (Estatus: Pagado / Dinero Entregado)")
        
        df_historial_retiros = cargar_retiros_mayorista()
        if not df_historial_retiros.empty:
            df_historial_retiros['estatus'] = "✅ Pagado / Dinero Entregado"
            
            meses_hist = sorted(df_historial_retiros['mes_corte'].unique()) if 'mes_corte' in df_historial_retiros.columns else []
            if meses_hist:
                fil_col1, fil_col2 = st.columns(2)
                with fil_col1:
                    mes_filtro_hist = st.selectbox("Filtrar historial por Mes de Corte", options=["Todos"] + list(meses_hist), key="fil_mes_hist")
                
                if mes_filtro_hist != "Todos":
                    df_historial_filtrado = df_historial_retiros[df_historial_retiros['mes_corte'] == mes_filtro_hist]
                else:
                    df_historial_filtrado = df_historial_retiros
            else:
                df_historial_filtrado = df_historial_retiros

            st.dataframe(df_historial_filtrado, use_container_width=True)

            csv_data = df_historial_filtrado.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Descargar Reporte de Pagos en CSV",
                data=csv_data,
                file_name=f"reporte_pagos_mayorista_{datetime.date.today().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
                type="secondary"
            )
        else:
            st.info("No hay pagos registrados en la base de datos todavía.")

    if is_admin:
        with get_tab("🔐 Mi Panel Privado"):
            st.title("🔐 Mi Panel Privado (CEO)")
            st.markdown("Información confidencial de márgenes, compras, retornos y financiamiento.")

            if not ingresos_df.empty:
                df_prestamos = cargar_prestamos()
                monto_prestamo_actual = 0.0
                
                if not df_prestamos.empty and 'mes_anio' in df_prestamos.columns:
                    p_row = df_prestamos[df_prestamos['mes_anio'] == mes_seleccionado]
                    if not p_row.empty:
                        monto_prestamo_actual = float(p_row.iloc[0]['monto_prestamo'])

                st.markdown("### 🏦 1. Financiamiento y Préstamo Banco")
                nuevo_prestamo = st.number_input(
                    f"Préstamo Banco / Inyección de Capital para el periodo ({mes_seleccionado}):", 
                    min_value=0.0, value=monto_prestamo_actual, step=500.0, format="%.2f"
                )
                
                if st.button("💾 Guardar Monto de Préstamo"):
                    supabase.table("prestamos_banco").delete().eq("mes_anio", mes_seleccionado).execute()
                    supabase.table("prestamos_banco").insert({
                        "mes_anio": mes_seleccionado,
                        "monto_prestamo": nuevo_prestamo
                    }).execute()
                    st.cache_data.clear()
                    st.success("✅ ¡Préstamo actualizado correctamente!")
                    st.rerun()

                st.divider()

                st.markdown("### ⚙️ 2. Parámetros y Reglas de Negocio (Porcentajes)")
                with st.expander("🛠️ Modificar Porcentajes de Reparto y Cuotas"):
                    p_carlos_op_new = st.slider("Porcentaje Operativo Carlos (%)", 0, 100, int(cfg["porcentaje_carlos_op"]*100)) / 100.0
                    p_cesar_op_new = 1.0 - p_carlos_op_new
                    st.text(f"Equivalente César Operativo: {int(p_cesar_op_new*100)}%")
                    
                    p_carlos_iva_new = st.slider("Porcentaje IVA Carlos (%)", 0, 100, int(cfg["porcentaje_carlos_iva"]*100)) / 100.0
                    p_cesar_iva_new = 1.0 - p_carlos_iva_new
                    st.text(f"Equivalente César IVA: {int(p_cesar_iva_new*100)}%")
                    
                    nicole_cuota_new = st.number_input("Cuota Fija Nicole ($)", min_value=0.0, value=float(cfg["cuota_nicole"]), step=100.0)
                    
                    if st.button("💾 Guardar Nuevos Parámetros"):
                        def upsert_cfg(clave, valor):
                            supabase.table("configuracion_global").delete().eq("clave", clave).execute()
                            supabase.table("configuracion_global").insert({"clave": clave, "valor": valor}).execute()
                        
                        upsert_cfg("porcentaje_carlos_op", p_carlos_op_new)
                        upsert_cfg("porcentaje_cesar_op", p_cesar_op_new)
                        upsert_cfg("porcentaje_carlos_iva", p_carlos_iva_new)
                        upsert_cfg("porcentaje_cesar_iva", p_cesar_iva_new)
                        upsert_cfg("cuota_nicole", nicole_cuota_new)
                        
                        st.cache_data.clear()
                        st.success("✅ ¡Reglas de negocio actualizadas!")
                        st.rerun()

                st.divider()

                st.markdown("### 📦 3. Resumen de Insumos del Mes")
                m1, m2, m3, m4 = st.columns(4)
                with m1: st.markdown(f"""<div class="metric-card"><div class="metric-title">Inversión Física</div><div class="metric-value" style="color: #e74a3b;">${carlos_inversion_real:,.2f}</div></div>""", unsafe_allow_html=True)
                with m2: st.markdown(f"""<div class="metric-card"><div class="metric-title">Préstamo Banco</div><div class="metric-value" style="color: #f6c23e;">${nuevo_prestamo:,.2f}</div></div>""", unsafe_allow_html=True)
                with m3: st.markdown(f"""<div class="metric-card"><div class="metric-title">Ganancia Compras (+25%)</div><div class="metric-value" style="color: #1cc88a;">${carlos_ganancia_insumos:,.2f}</div></div>""", unsafe_allow_html=True)
                with m4: st.markdown(f"""<div class="metric-card"><div class="metric-title">Total a Recuperar</div><div class="metric-value" style="color: #4e73df;">${carlos_total_recuperado:,.2f}</div></div>""", unsafe_allow_html=True)

                st.divider()

                df_cierre_priv = pd.DataFrame(datos_socios_privado)
                st.markdown("### 🗓️ 4. Desglose Operativo Completo")
                st.dataframe(df_cierre_priv, use_container_width=True, hide_index=True, column_config={
                    "Subtotal": st.column_config.NumberColumn(format="$%.2f"), "IVA": st.column_config.NumberColumn(format="$%.2f"),
                    "Total Factura (Banco)": st.column_config.NumberColumn("Total Factura (Banco)", format="$%.2f"),
                    "Pago Carlos (Insumos)": st.column_config.NumberColumn(format="$%.2f"), "Total (Base)": st.column_config.NumberColumn(format="$%.2f"),
                    "(-).10 Carlos/Cesar": st.column_config.NumberColumn(format="$%.2f"), "Entrega Mayorista": st.column_config.NumberColumn(format="$%.2f")
                })

                st.divider()

                st.markdown("### 🏆 5. Tu Consolidado Financiero (Flujo Total)")
                
                ganancia_neta_total = carlos_ganancia_insumos + carlos_op + carlos_iva
                total_transferir_cuenta = carlos_inversion_real + ganancia_neta_total
                monto_libre_real = total_transferir_cuenta - nuevo_prestamo

                colA, colB = st.columns([1, 1])
                with colA:
                    st.markdown("#### 💰 Desglose de Ganancias Netas")
                    st.markdown(f"- Ganancia por Insumos (+25%): **${carlos_ganancia_insumos:,.2f}**")
                    st.markdown(f"- Ganancia Operativa ({int(cfg['porcentaje_carlos_op']*100)}% del .10): **${carlos_op:,.2f}**")
                    st.markdown(f"- Bono Fiscal IVA ({int(cfg['porcentaje_carlos_iva']*100)}%): **${carlos_iva:,.2f}**")
                    st.markdown("---")
                    st.markdown(f"**Ganancia Neta Total a la Bolsa:** <span style='font-size:22px; color:#1cc88a;'>**${ganancia_neta_total:,.2f}**</span>", unsafe_allow_html=True)
                with colB:
                    st.markdown("#### 🏦 Flujo a Recibir (Tu Depósito Real)")
                    st.markdown(f"- Recuperación Inversión Real: **${carlos_inversion_real:,.2f}**")
                    st.markdown(f"- Todas tus ganancias sumadas: **${ganancia_neta_total:,.2f}**")
                    st.markdown("---")
                    st.markdown(f"**Total a transferir a tu cuenta:** <span style='font-size:18px; color:#6c757d;'>**${total_transferir_cuenta:,.2f}**</span>", unsafe_allow_html=True)
                    st.markdown(f"*(Menos devolución de Préstamo Banco)*: <span style='color: #e74a3b;'>**-${nuevo_prestamo:,.2f}**</span>", unsafe_allow_html=True)
                    st.markdown(f"**Monto Libre Disponible (Real):** <span style='font-size:24px; color:#4e73df;'>**${monto_libre_real:,.2f}**</span>", unsafe_allow_html=True)
            else:
                st.info("No hay facturas de ingreso en este periodo.")
                
        with get_tab("👥 Gestión Usuarios"):
            st.title("👥 Gestión de Accesos al Sistema")
            st.markdown("Autoriza, modifica el rol o elimina usuarios registrados en la plataforma.")
            
            res_usuarios = supabase.table("usuarios").select("*").order("id").execute()
            if res_usuarios.data:
                df_users = pd.DataFrame(res_usuarios.data)
                
                edited_users = st.data_editor(
                    df_users[['id', 'email', 'rol', 'aprobado', 'fecha_registro']],
                    disabled=["id", "email", "fecha_registro"],
                    column_config={
                        "rol": st.column_config.SelectboxColumn("Rol del Usuario", options=["admin", "socio", "contador"]),
                        "aprobado": st.column_config.CheckboxColumn("¿Acceso Aprobado?")
                    },
                    use_container_width=True, hide_index=True
                )
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Guardar Cambios de Usuarios", type="primary", use_container_width=True):
                        for idx, row in edited_users.iterrows():
                            supabase.table("usuarios").update({
                                "rol": row["rol"],
                                "aprobado": row["aprobado"]
                            }).eq("id", row["id"]).execute()
                        st.success("✅ ¡Permisos actualizados correctamente!")
                        st.rerun()

                with col_btn2:
                    usuario_a_borrar = st.selectbox("Selecciona usuario a eliminar", options=[""] + df_users['email'].tolist(), key="del_user")
                    if st.button("🗑️ Eliminar Usuario Seleccionado", type="secondary", use_container_width=True):
                        if usuario_a_borrar:
                            if usuario_a_borrar.lower() == st.session_state['email'].lower():
                                st.error("⚠️ No puedes eliminar tu propia cuenta de Administrador.")
                            else:
                                supabase.table("usuarios").delete().eq("email", usuario_a_borrar).execute()
                                st.success(f"✅ Usuario {usuario_a_borrar} eliminado con éxito.")
                                st.rerun()
                        else:
                            st.warning("Selecciona un correo para eliminar.")

    if puede_ver_sat:
        with get_tab("📥 Conexión SAT"):
            st.title("📥 Sincronización Directa con el SAT (Nicole)")
            st.markdown(f"Módulo exclusivo para Administradores y Contadores.")

            st.markdown("### 🔐 Credenciales Fiscales (e.firma)")
            col_cer, col_key = st.columns(2)
            with col_cer:
                cer_file = st.file_uploader("Sube tu archivo .cer", type=['cer'])
            with col_key:
                key_file = st.file_uploader("Sube tu archivo .key", type=['key'])
            
            pass_sat = st.text_input("Contraseña de la Clave Privada", type="password", help="Contraseña de la e.firma")

            st.divider()

            st.markdown("### 1️⃣ Paso 1: Solicitar Paquete de XML al SAT")
            st.info("El SAT validará tu e.firma y te asignará un ID de ticket.")
            
            with st.form("form_solicitud_sat"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    fecha_inicio = st.date_input("Fecha Inicio")
                with c2:
                    fecha_fin = st.date_input("Fecha Fin")
                with c3:
                    tipo_descarga = st.selectbox("Tipo de Facturas", ["Emitidas", "Recibidas"])
                
                btn_solicitar = st.form_submit_button("Enviar Solicitud al SAT", type="primary")

                if btn_solicitar:
                    if not cer_file or not key_file or not pass_sat:
                        st.error("⚠️ Debes cargar tu .cer, .key y escribir la contraseña.")
                    else:
                        with st.spinner("🔄 Conectando directamente con los Web Services del SAT..."):
                            try:
                                cer_file.seek(0)
                                key_file.seek(0)
                                cer_der = cer_file.read()
                                key_der = key_file.read()
                                pass_limpia = pass_sat.strip() 

                                from cfdiclient import Fiel, Autenticacion, SolicitaDescargaEmitidos, SolicitaDescargaRecibidos

                                fiel = Fiel(cer_der, key_der, pass_limpia)
                                token = Autenticacion(fiel).obtener_token()
                                
                                f_ini = datetime.datetime.combine(fecha_inicio, datetime.time.min)
                                f_fin = datetime.datetime.combine(fecha_fin, datetime.time.max)

                                if tipo_descarga == "Emitidas":
                                    solicita = SolicitaDescargaEmitidos(fiel)
                                    respuesta = solicita.solicitar_descarga(
                                        token=token,
                                        rfc_solicitante=RFC_ACTIVO,
                                        fecha_inicial=f_ini,
                                        fecha_final=f_fin,
                                        rfc_emisor=RFC_ACTIVO,
                                        tipo_solicitud='CFDI'
                                    )
                                else:
                                    solicita = SolicitaDescargaRecibidos(fiel)
                                    respuesta = solicita.solicitar_descarga(
                                        token=token,
                                        rfc_solicitante=RFC_ACTIVO,
                                        fecha_inicial=f_ini,
                                        fecha_final=f_fin,
                                        rfc_receptor=RFC_ACTIVO,
                                        tipo_solicitud='CFDI'
                                    )

                                id_solicitud_generado = respuesta.get('id_solicitud')

                                if id_solicitud_generado:
                                    supabase.table("sat_solicitudes").insert({
                                        "id_solicitud_sat": id_solicitud_generado,
                                        "fecha_inicio": str(fecha_inicio),
                                        "fecha_fin": str(fecha_fin),
                                        "tipo_solicitud": tipo_descarga,
                                        "estatus": "Pendiente",
                                        "registrado_por": st.session_state.get("email", "admin/contador")
                                    }).execute()

                                    st.success(f"✅ ¡Solicitud enviada al SAT con éxito! ID: `{id_solicitud_generado}`.")
                                    st.rerun()
                                else:
                                    st.error(f"❌ El SAT rechazó la petición. (Asegúrate de que la e.firma corresponde al RFC activo). Respuesta SAT: {respuesta}")

                            except Exception as ex:
                                st.error(f"❌ Error al procesar las credenciales o conectar con el SAT: {ex}")

            st.divider()

            st.markdown("### 2️⃣ Paso 2: Verificar Solicitudes y Descargar Automáticamente")
            st.write("Consulta el estatus de los paquetes solicitados al SAT. Si están listos, la app extraerá y guardará tus facturas mágicamente en Supabase.")

            try:
                res_solicitudes = supabase.table("sat_solicitudes").select("*").order("fecha_creacion", desc=True).execute()
                df_solicitudes = pd.DataFrame(res_solicitudes.data) if res_solicitudes.data else pd.DataFrame()
            except Exception as e:
                df_solicitudes = pd.DataFrame()

            if not df_solicitudes.empty:
                for idx, fila in df_solicitudes.iterrows():
                    tipo_req = fila.get('tipo_solicitud') or fila.get('tipo_descarga', 'N/A')
                    with st.expander(f"Solicitud: {tipo_req} ({fila['fecha_inicio']} a {fila['fecha_fin']}) | Estatus: {fila['estatus']}"):
                        st.write(f"**ID SAT:** `{fila['id_solicitud_sat']}`")
                        
                        if fila['estatus'] in ['Pendiente', 'Completada', 'Completada (Vacía)']:
                            label_btn = "🔄 Verificar Estatus y Extraer Facturas" if fila['estatus'] == 'Pendiente' else "🔄 Forzar Re-descarga de XMLs"
                            if st.button(label_btn, key=f"btn_check_{fila['id_solicitud_sat']}"):
                                if not cer_file or not key_file or not pass_sat:
                                    st.error("⚠️ Sube las credenciales arriba para poder verificar este paquete.")
                                else:
                                    with st.spinner("Conectando con el SAT para revisión y descarga invisible..."):
                                        try:
                                            cer_file.seek(0)
                                            key_file.seek(0)
                                            cer_der = cer_file.read()
                                            key_der = key_file.read()
                                            pass_limpia = pass_sat.strip()
                                            
                                            from cfdiclient import Fiel, Autenticacion, VerificaSolicitudDescarga, DescargaMasiva
                                            
                                            fiel = Fiel(cer_der, key_der, pass_limpia)
                                            token = Autenticacion(fiel).obtener_token()
                                            
                                            verifica = VerificaSolicitudDescarga(fiel)
                                            res_verifica = verifica.verificar_descarga(
                                                token=token,
                                                rfc_solicitante=RFC_ACTIVO,
                                                id_solicitud=fila['id_solicitud_sat']
                                            )
                                            
                                            estado = str(res_verifica.get('estado_solicitud'))
                                            
                                            if estado == '3':
                                                paquetes = []
                                                for k, v in res_verifica.items():
                                                    if 'paquete' in k.lower():
                                                        if isinstance(v, list): paquetes.extend(v)
                                                        elif isinstance(v, str): paquetes.append(v)

                                                if not paquetes:
                                                    st.warning("El SAT indica que terminó, pero el paquete está vacío (0 facturas encontradas en ese rango de fechas).")
                                                    supabase.table("sat_solicitudes").update({"estatus": "Completada (Vacía)"}).eq("id", fila['id']).execute()
                                                    time.sleep(3)
                                                    st.rerun()
                                                else:
                                                    st.info(f"¡El SAT armó el paquete! Descomprimiendo y leyendo XMLs en memoria...")
                                                    descarga = DescargaMasiva(fiel)
                                                    facturas_extraidas = []
                                                    xml_encontrados = 0
                                                    
                                                    for id_paquete in paquetes:
                                                        res_paquete = descarga.descargar_paquete(token, RFC_ACTIVO, id_paquete)
                                                        b64_zip = res_paquete.get('paquete_b64')
                                                        if b64_zip:
                                                            zip_data = base64.b64decode(b64_zip)
                                                            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                                                                for file_name in z.namelist():
                                                                    if file_name.lower().endswith('.xml'):
                                                                        xml_encontrados += 1
                                                                        xml_bytes = z.read(file_name)
                                                                        datos_f = procesar_cfdi(xml_bytes, RFC_ACTIVO)
                                                                        if datos_f:
                                                                            facturas_extraidas.append(datos_f)
                                                    
                                                    if facturas_extraidas:
                                                        res_existentes = supabase.table("facturas").select("uuid_cfdi").execute()
                                                        uuids_existentes = [r['uuid_cfdi'].lower() for r in res_existentes.data] if res_existentes.data else []
                                                        
                                                        nuevas = [f for f in facturas_extraidas if f['uuid_cfdi'].lower() not in uuids_existentes]
                                                        
                                                        if nuevas:
                                                            supabase.table("facturas").insert(nuevas).execute()
                                                            st.cache_data.clear()
                                                            st.success(f"✅ ¡Éxito! Se escanearon {xml_encontrados} XMLs y se guardaron {len(nuevas)} facturas nuevas a tu base de datos.")
                                                        else:
                                                            st.success(f"✅ Paquete procesado. Se leyeron {xml_encontrados} XMLs, pero todos ya estaban guardados en tu base de datos.")
                                                    else:
                                                        st.warning(f"Se extrajeron {xml_encontrados} archivos XML del ZIP, pero el código no pudo encontrar el RFC {RFC_ACTIVO} adentro de ellos.")
                                                    
                                                    supabase.table("sat_solicitudes").update({"estatus": "Completada"}).eq("id", fila['id']).execute()
                                                    time.sleep(4)
                                                    st.rerun()
                                                    
                                            elif estado == '1' or estado == '2':
                                                st.warning("⏳ El SAT sigue empaquetando tu solicitud. Vuelve a hacer clic en unos minutos.")
                                                time.sleep(3)
                                            elif estado == '4' or estado == '5':
                                                st.error("❌ El SAT rechazó o falló al generar la solicitud internamente.")
                                                supabase.table("sat_solicitudes").update({"estatus": "Rechazada por SAT"}).eq("id", fila['id']).execute()
                                                time.sleep(3)
                                                st.rerun()
                                            elif estado == '6':
                                                st.error("❌ La solicitud caducó en los servidores del SAT (tienes hasta 3 días para descargarla). Vuelve a pedir el paquete en el Paso 1.")
                                                supabase.table("sat_solicitudes").update({"estatus": "Caducada"}).eq("id", fila['id']).execute()
                                                time.sleep(3)
                                                st.rerun()
                                            else:
                                                st.error(f"Respuesta inesperada del SAT: {res_verifica}")

                                        except Exception as ex:
                                            st.error(f"❌ Error al intentar extraer el archivo ZIP o comunicarse con el SAT: {ex}")
                        elif fila['estatus'] in ['Rechazada por SAT', 'Caducada']:
                            st.error(f"Esta solicitud tiene estatus: {fila['estatus']}.")
            else:
                st.info("No hay solicitudes pendientes registradas.")

# ==============================================================================
# ENTORNO 2: MIS FINANZAS (CARLOS)
# ==============================================================================
elif perfil_activo == "Mis Finanzas (Carlos)":

    ingresos_df_c = df_entorno[df_entorno['tipo'] == 'INGRESO'].copy()
    gastos_df_c = df_entorno[df_entorno['tipo'] == 'GASTO'].copy()

    t_ingresos_c = float(ingresos_df_c['total'].sum()) if not ingresos_df_c.empty else 0.0
    t_gastos_c = float(gastos_df_c['total'].sum()) if not gastos_df_c.empty else 0.0
    t_iva_ingresos_c = float(ingresos_df_c['impuestos'].sum()) if not ingresos_df_c.empty else 0.0
    t_iva_gastos_c = float(gastos_df_c['impuestos'].sum()) if not gastos_df_c.empty else 0.0
    iva_por_pagar_c = t_iva_ingresos_c - t_iva_gastos_c

    tabs_carlos = st.tabs(["📊 Mi Tablero Fiscal", "💰 Ingresos", "💸 Egresos", "📥 Conexión SAT"])
    
    with tabs_carlos[0]:
        st.title(f"📊 Dashboard Fiscal (Carlos Salazar)")
        st.markdown(f"**RFC Activo:** `{RFC_ACTIVO}` | Análisis general de ingresos y egresos aislados de la operación corporativa.")
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #e74a3b;"><div class="metric-title">IVA Neto a Pagar/Favor</div><div class="metric-value" style="color: #e74a3b;">${iva_por_pagar_c:,.2f}</div></div>""", unsafe_allow_html=True)
        with c2: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #f6c23e;"><div class="metric-title">IVA Facturado (Emitido)</div><div class="metric-value" style="color: #f4b619;">${t_iva_ingresos_c:,.2f}</div></div>""", unsafe_allow_html=True)
        with c3: st.markdown(f"""<div class="metric-card" style="border-left: 4px solid #1cc88a;"><div class="metric-title">Total Ingresos</div><div class="metric-value" style="color: #1cc88a;">${t_ingresos_c:,.2f}</div></div>""", unsafe_allow_html=True)
        with c4: st.markdown(f"""<div class="metric-card"><div class="metric-title">Total Egresos</div><div class="metric-value">${t_gastos_c:,.2f}</div></div>""", unsafe_allow_html=True)

    with tabs_carlos[1]:
        st.title("💰 Mis Ingresos Emitidos")
        if not ingresos_df_c.empty: st.dataframe(ingresos_df_c, use_container_width=True)
        else: st.info("No hay ingresos registrados con este RFC en la base de datos.")

    with tabs_carlos[2]:
        st.title("💸 Mis Gastos (Deducibles)")
        if not gastos_df_c.empty: st.dataframe(gastos_df_c, use_container_width=True)
        else: st.info("No hay egresos registrados con este RFC en la base de datos.")

    with tabs_carlos[3]:
        st.title("📥 Sincronización Directa con el SAT (Carlos)")
        st.markdown(f"Módulo configurado exclusivamente para descargar las facturas de **`{RFC_ACTIVO}`**.")

        col_cer, col_key = st.columns(2)
        with col_cer: cer_file = st.file_uploader("Sube tu archivo .cer", type=['cer'], key="cer_carlos")
        with col_key: key_file = st.file_uploader("Sube tu archivo .key", type=['key'], key="key_carlos")
        pass_sat = st.text_input("Contraseña de la Clave Privada", type="password", key="pass_carlos")

        st.divider()

        st.markdown("### 1️⃣ Paso 1: Solicitar Paquete de XML al SAT")
        
        with st.form("form_sat_carlos"):
            c1, c2, c3 = st.columns(3)
            with c1: fecha_inicio = st.date_input("Fecha Inicio")
            with c2: fecha_fin = st.date_input("Fecha Fin")
            with c3: tipo_descarga = st.selectbox("Tipo de Facturas", ["Emitidas", "Recibidas"])
            
            if st.form_submit_button("Enviar Solicitud al SAT", type="primary"):
                if not cer_file or not key_file or not pass_sat:
                    st.error("⚠️ Faltan credenciales.")
                else:
                    with st.spinner("🔄 Conectando directo al SAT con tu e.firma..."):
                        try:
                            cer_file.seek(0)
                            key_file.seek(0)
                            cer_der = cer_file.read()
                            key_der = key_file.read()
                            pass_limpia = pass_sat.strip()

                            from cfdiclient import Fiel, Autenticacion, SolicitaDescargaEmitidos, SolicitaDescargaRecibidos

                            fiel = Fiel(cer_der, key_der, pass_limpia)
                            token = Autenticacion(fiel).obtener_token()
                            
                            f_ini = datetime.datetime(fecha_inicio.year, fecha_inicio.month, fecha_inicio.day, 0, 0, 0)
                            f_fin = datetime.datetime(fecha_fin.year, fecha_fin.month, fecha_fin.day, 23, 59, 59)

                            if tipo_descarga == "Emitidas":
                                solicita = SolicitaDescargaEmitidos(fiel)
                                respuesta = solicita.solicitar_descarga(
                                    token=token, rfc_solicitante=RFC_ACTIVO,
                                    fecha_inicial=f_ini, fecha_final=f_fin,
                                    rfc_emisor=RFC_ACTIVO, tipo_solicitud='CFDI'
                                )
                            else:
                                solicita = SolicitaDescargaRecibidos(fiel)
                                respuesta = solicita.solicitar_descarga(
                                    token=token, rfc_solicitante=RFC_ACTIVO,
                                    fecha_inicial=f_ini, fecha_final=f_fin,
                                    rfc_receptor=RFC_ACTIVO, tipo_solicitud='CFDI'
                                )

                            id_solicitud = respuesta.get('id_solicitud')
                            if id_solicitud:
                                supabase.table("sat_solicitudes").insert({
                                    "id_solicitud_sat": id_solicitud, "fecha_inicio": str(fecha_inicio),
                                    "fecha_fin": str(fecha_fin), "tipo_solicitud": tipo_descarga,
                                    "estatus": "Pendiente", "registrado_por": st.session_state['email']
                                }).execute()
                                st.success(f"✅ ¡Solicitud exitosa para Carlos! ID: `{id_solicitud}`.")
                                st.rerun()
                            else:
                                st.error(f"❌ Rechazado por el SAT. Respuesta SAT: {respuesta}")
                        except Exception as ex:
                            st.error(f"❌ Error de llave o conexión: {ex}")

        st.divider()
        st.markdown("### 2️⃣ Paso 2: Verificar Solicitudes y Descargar Automáticamente")
        try:
            res_solicitudes = supabase.table("sat_solicitudes").select("*").eq("registrado_por", st.session_state['email']).order("fecha_creacion", desc=True).execute()
            df_solicitudes = pd.DataFrame(res_solicitudes.data) if res_solicitudes.data else pd.DataFrame()
        except Exception:
            df_solicitudes = pd.DataFrame()

        if not df_solicitudes.empty:
            for idx, fila in df_solicitudes.iterrows():
                tipo_req = fila.get('tipo_solicitud') or fila.get('tipo_descarga', 'N/A')
                with st.expander(f"Solicitud: {tipo_req} ({fila['fecha_inicio']} a {fila['fecha_fin']}) | Estatus: {fila['estatus']}"):
                    st.write(f"**ID SAT:** `{fila['id_solicitud_sat']}`")
                    if fila['estatus'] in ['Pendiente', 'Completada', 'Completada (Vacía)']:
                        label_btn = "🔄 Verificar Estatus y Extraer Facturas" if fila['estatus'] == 'Pendiente' else "🔄 Forzar Re-descarga de XMLs"
                        if st.button(label_btn, key=f"btn_check_carlos_{fila['id_solicitud_sat']}"):
                            if not cer_file or not key_file or not pass_sat:
                                st.error("⚠️ Sube tus credenciales arriba para poder verificar este paquete.")
                            else:
                                with st.spinner("Conectando con el SAT para revisión y descarga invisible..."):
                                    try:
                                        cer_file.seek(0)
                                        key_file.seek(0)
                                        cer_der = cer_file.read()
                                        key_der = key_file.read()
                                        pass_limpia = pass_sat.strip()
                                        
                                        from cfdiclient import Fiel, Autenticacion, VerificaSolicitudDescarga, DescargaMasiva
                                        
                                        fiel = Fiel(cer_der, key_der, pass_limpia)
                                        token = Autenticacion(fiel).obtener_token()
                                        
                                        verifica = VerificaSolicitudDescarga(fiel)
                                        res_verifica = verifica.verificar_descarga(
                                            token=token,
                                            rfc_solicitante=RFC_ACTIVO,
                                            id_solicitud=fila['id_solicitud_sat']
                                        )
                                        
                                        estado = str(res_verifica.get('estado_solicitud'))
                                        
                                        if estado == '3':
                                            paquetes = []
                                            for k, v in res_verifica.items():
                                                if 'paquete' in k.lower():
                                                    if isinstance(v, list): paquetes.extend(v)
                                                    elif isinstance(v, str): paquetes.append(v)

                                            if not paquetes:
                                                st.warning("El SAT indica que terminó, pero el paquete está vacío (0 facturas).")
                                                supabase.table("sat_solicitudes").update({"estatus": "Completada (Vacía)"}).eq("id", fila['id']).execute()
                                                time.sleep(3)
                                                st.rerun()
                                            else:
                                                st.info(f"¡El SAT armó el paquete! Descomprimiendo y leyendo XMLs en memoria...")
                                                descarga = DescargaMasiva(fiel)
                                                facturas_extraidas = []
                                                xml_encontrados = 0
                                                
                                                for id_paquete in paquetes:
                                                    res_paquete = descarga.descargar_paquete(token, RFC_ACTIVO, id_paquete)
                                                    b64_zip = res_paquete.get('paquete_b64')
                                                    if b64_zip:
                                                        zip_data = base64.b64decode(b64_zip)
                                                        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                                                            for file_name in z.namelist():
                                                                if file_name.lower().endswith('.xml'):
                                                                    xml_encontrados += 1
                                                                    xml_bytes = z.read(file_name)
                                                                    datos_f = procesar_cfdi(xml_bytes, RFC_ACTIVO)
                                                                    if datos_f:
                                                                        facturas_extraidas.append(datos_f)
                                                
                                                if facturas_extraidas:
                                                    res_existentes = supabase.table("facturas").select("uuid_cfdi").execute()
                                                    uuids_existentes = [r['uuid_cfdi'].lower() for r in res_existentes.data] if res_existentes.data else []
                                                    
                                                    nuevas = [f for f in facturas_extraidas if f['uuid_cfdi'].lower() not in uuids_existentes]
                                                    
                                                    if nuevas:
                                                        supabase.table("facturas").insert(nuevas).execute()
                                                        st.cache_data.clear()
                                                        st.success(f"✅ ¡Éxito! Se escanearon {xml_encontrados} XMLs y se guardaron {len(nuevas)} facturas nuevas a tu base de datos.")
                                                    else:
                                                        st.success(f"✅ Paquete procesado. Se leyeron {xml_encontrados} XMLs, pero todos ya estaban guardados en tu base de datos.")
                                                else:
                                                    if xml_encontrados == 0:
                                                        st.error(f"El SAT no envió el archivo ZIP o ya bloqueó este paquete por límite de descargas. Respuesta del SAT: {res_paquete}")
                                                    else:
                                                        st.warning(f"Se extrajeron {xml_encontrados} archivos XML del ZIP, pero el código no pudo encontrar el RFC {RFC_ACTIVO} adentro de ellos.")
                                                
                                                supabase.table("sat_solicitudes").update({"estatus": "Completada"}).eq("id", fila['id']).execute()
                                                time.sleep(4)
                                                st.rerun()
                                                
                                        elif estado == '1' or estado == '2':
                                            st.warning("⏳ El SAT sigue empaquetando tu solicitud. Vuelve a hacer clic en unos minutos.")
                                            time.sleep(3)
                                        elif estado == '4' or estado == '5':
                                            st.error("❌ El SAT rechazó o falló al generar la solicitud internamente.")
                                            supabase.table("sat_solicitudes").update({"estatus": "Rechazada por SAT"}).eq("id", fila['id']).execute()
                                            time.sleep(3)
                                            st.rerun()
                                        elif estado == '6':
                                            st.error("❌ La solicitud caducó en los servidores del SAT. Vuelve a pedir el paquete.")
                                            supabase.table("sat_solicitudes").update({"estatus": "Caducada"}).eq("id", fila['id']).execute()
                                            time.sleep(3)
                                            st.rerun()
                                        else:
                                            st.error(f"Respuesta inesperada del SAT: {res_verifica}")

                                    except Exception as ex:
                                        st.error(f"❌ Error al intentar extraer el archivo ZIP o comunicarse con el SAT: {ex}")
                        elif fila['estatus'] in ['Rechazada por SAT', 'Caducada']:
                            st.error(f"Esta solicitud tiene estatus: {fila['estatus']}.")
        else:
            st.info("No tienes solicitudes pendientes con el SAT.")