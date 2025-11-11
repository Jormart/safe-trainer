import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime, timedelta
import re
import unicodedata
from difflib import SequenceMatcher

# =========================
# Configuración
# =========================
file_path = 'Agil - Copia de Preguntas_Examen.xlsx'
historial_path = 'historial_sesiones.csv'
num_preguntas_por_sesion = 10
tiempo_total = timedelta(minutes=90)  # 1h 30min
TOP_K_ADAPTATIVO = 50  # pool prioritario para variedad en adaptativo

# =========================
# Carga de datos
# =========================
@st.cache_data
def cargar_datos():
    df = pd.read_excel(file_path, engine='openpyxl')
    if 'Veces Realizada' not in df.columns:
        df['Veces Realizada'] = 0
    if 'Errores' not in df.columns:
        df['Errores'] = 0
    df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta']).reset_index(drop=True)
    df['Pregunta'] = df['Pregunta'].astype(str).str.strip()
    df['Respuesta Correcta'] = df['Respuesta Correcta'].astype(str).str.strip()
    
    # Detectar preguntas múltiples por:
    # 1. Separadores en la respuesta (;,)
    # 2. Texto en la pregunta que indica selección múltiple
    def es_pregunta_multiple(row):
        # Detectar preguntas múltiples SÓLO si contienen la palabra "two" (case-insensitive)
        pregunta = str(row.get('Pregunta', '')).lower()
        return 'two' in pregunta
    
    # Marcar preguntas múltiples
    df['Es Multiple'] = df.apply(es_pregunta_multiple, axis=1)
    
    # Convertir respuestas a lista (sean múltiples o no)
    def obtener_respuestas(row):
        resp = str(row['Respuesta Correcta'])
        if row['Es Multiple']:
            # Si es múltiple, buscar separador ';' (si existe, dividir; si no, asumir respuesta única)
            if ';' in resp:
                return [r.strip() for r in resp.split(';')]
        return [resp.strip()]
    
    df['Respuestas Correctas'] = df.apply(obtener_respuestas, axis=1)
    return df

df = cargar_datos()

# =========================
# Estado de sesión
# =========================
ss = st.session_state
if 'inicio' not in ss:
    ss.inicio = datetime.now()
if 'idx' not in ss:
    ss.idx = 0
if 'historial' not in ss:
    ss.historial = []
if 'preguntas' not in ss:
    ss.preguntas = None
if 'modo' not in ss:
    ss.modo = None
if 'opciones_mezcladas' not in ss:
    ss.opciones_mezcladas = {}
if 'respondida' not in ss:
    ss.respondida = False
if 'ultima_correcta' not in ss:
    ss.ultima_correcta = None

# =========================
# Normalización robusta
# =========================
def normaliza(s: str) -> str:
    """Limpia diferencias invisibles: NBSP, espacios de ancho cero, CR/TAB,
    colapsa espacios, normaliza Unicode y hace casefold."""
    if s is None:
        return ""
    s = str(s)
    # Unicode canonical/compatibility normalization
    s = unicodedata.normalize("NFKC", s)
    # Sustituir NBSP y espacios finos por espacio normal
    s = (
        s.replace("\u00A0", " ")  # NBSP
         .replace("\u2009", " ")  # thin space
         .replace("\u2007", " ")
         .replace("\u202F", " ")
    )
    # Quitar espacios de ancho cero / BOM
    s = (
        s.replace("\u200B", "")
         .replace("\u200C", "")
         .replace("\u200D", "")
         .replace("\uFEFF", "")
    )
    # Normalizar CR/TAB a espacios
    s = s.replace("\r", " ").replace("\t", " ")
    # Colapsar múltiple whitespace
    s = re.sub(r"\s+", " ", s)
    # Strip y casefold (mejor que lower para Unicode)
    s = s.strip().casefold()
    # (Opcional) quitar bullets/numeraciones iniciales tipo "A) ", "1. ", "• "
    s = re.sub(r"^(?:[A-Za-z]\)|\d+\.)\s*", "", s).replace("•", "")
    # (Opcional) quitar puntuación final repetida (p. ej., "Hours." vs "Hours")
    s = re.sub(r"[.·…]+$", "", s)
    return s

# =========================
# Utilidades y callbacks
# =========================
def preparar_preguntas(df_base: pd.DataFrame, modo: str, n: int) -> pd.DataFrame:
    """Prepara DataFrame de preguntas preservando índice original en 'df_index'."""
    if modo == "Adaptativo":
        base = df_base.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
        k = min(TOP_K_ADAPTATIVO, len(base))
        top_k = base.head(k).copy()
        top_k['df_index'] = top_k.index  # índice original del df
        seleccion = top_k.sample(n=min(n, len(top_k)), random_state=None).reset_index(drop=True)
        return seleccion
    else:  # Aleatorio puro
        aleatorias = df_base.sample(n=min(n, len(df_base)), random_state=None).copy()
        aleatorias['df_index'] = aleatorias.index
        return aleatorias.reset_index(drop=True)

def cb_reiniciar():
    """Reinicia por completo la sesión; Streamlit rerenderiza automáticamente al terminar el callback."""
    ss.clear()
    # No llamar a st.rerun() dentro de callbacks: Streamlit re-ejecuta tras el callback

def cb_iniciar(modo_select):
    """Inicia una nueva sesión con el modo seleccionado."""
    ss.modo = modo_select
    ss.preguntas = preparar_preguntas(df, modo_select, num_preguntas_por_sesion)
    ss.inicio = datetime.now()
    ss.idx = 0
    ss.respondida = False
    ss.ultima_correcta = None
    ss.opciones_mezcladas = {}
    # Sin st.rerun() aquí (no-op dentro de callbacks)

def cb_responder():
    """Registra la respuesta, actualiza métricas y muestra feedback (sin requerir segundo clic)."""
    idx = ss.idx
    pregunta = ss.preguntas.iloc[idx]
    enunciado = pregunta['Pregunta']
    es_multiple = pregunta['Es Multiple']
    respuestas_correctas = pregunta['Respuestas Correctas']

    seleccion_key = f"seleccion_{idx}"
    if seleccion_key not in ss:
        return
    
    seleccion = ss[seleccion_key]
    if not isinstance(seleccion, list):
        seleccion = [seleccion]

    # Normalizar todas las respuestas para comparación
    seleccion_norm = {normaliza(s) for s in seleccion}
    correctas_norm = {normaliza(c) for c in respuestas_correctas}

    # Comparación de conjuntos para respuestas múltiples
    es_correcta = seleccion_norm == correctas_norm
    resultado = '✅' if es_correcta else '❌'

    registro = {
        'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Pregunta': enunciado,
        'Respuesta Dada': seleccion,
        'Respuesta Correcta': correcta,
        'Resultado': resultado
    }
    ss.historial.append(registro)

    # Guardar historial (append)
    try:
        historial_df = pd.DataFrame([registro])
        if os.path.exists(historial_path):
            historial_df.to_csv(historial_path, mode='a', header=False, index=False)
        else:
            historial_df.to_csv(historial_path, index=False)
    except Exception as e:
        st.warning(f"No se pudo guardar el historial: {e}")

    # Actualizar contadores en df original usando df_index
    try:
        df_idx = ss.preguntas.loc[idx, 'df_index']
        df.at[df_idx, 'Veces Realizada'] += 1
        if es_correcta:
            if df.at[df_idx, 'Errores'] > 0:
                df.at[df_idx, 'Errores'] -= 1
            ss.ultima_correcta = True
        else:
            df.at[df_idx, 'Errores'] += 1
            ss.ultima_correcta = False
        df.to_excel(file_path, index=False)  # persistencia inmediata
    except Exception as e:
        st.warning(f"No se pudo actualizar/persistir métricas: {e}")

    # Marcar como respondida; al terminar el callback, Streamlit hará rerun y se verá el feedback
    ss.respondida = True

def cb_siguiente():
    """Avanza a la siguiente pregunta; tras el callback, Streamlit rerenderiza automáticamente."""
    ss.idx += 1
    ss.respondida = False
    ss.ultima_correcta = None
    # Sin st.rerun() aquí (no-op dentro de callbacks)

# =========================
# Cabecera y cronómetro
# =========================
st.title("🧠 Entrenador SAFe - Sesión de preguntas")

tiempo_restante = tiempo_total - (datetime.now() - ss.inicio)
if tiempo_restante.total_seconds() <= 0:
    st.error("⏰ ¡Tiempo agotado! La sesión ha finalizado.")
    st.button("🔄 Reiniciar sesión", key="btn_reiniciar_timeout", on_click=cb_reiniciar)
    st.stop()
else:
    st.markdown(f"⏳ Tiempo restante: **{tiempo_restante.seconds // 60} min**")

    # =========================
    # Buscador de preguntas (barra lateral)
    # =========================
    def buscar_preguntas(query: str, df_base: pd.DataFrame) -> pd.DataFrame:
        """Busca coincidencias parciales en Pregunta, Opciones, Respuesta Correcta y Nº."""
        if not query or str(query).strip() == "":
            return pd.DataFrame(columns=df_base.columns)

        # Limpiar comillas y espacios
        query = str(query).strip().replace('"', '').replace("'", "")
        qn = query.lower()  # Usamos lower para coincidencia simple

        def fila_coincide(row):
            # Convertir cada campo a minúsculas para comparación
            texto_pregunta = str(row.get('Pregunta', '')).lower()
            texto_opciones = str(row.get('Opciones', '')).lower()
            texto_respuesta = str(row.get('Respuesta Correcta', '')).lower()
            texto_numero = str(row.get('Nº', '')).lower()

            # Coincidencia parcial
            return (
                qn in texto_pregunta
                or qn in texto_opciones
                or qn in texto_respuesta
                or qn == texto_numero
            )

        try:
            resultados = df_base[df_base.apply(fila_coincide, axis=1)].copy()
        except Exception:
            resultados = pd.DataFrame(columns=df_base.columns)
        return resultados

    st.sidebar.header("🔎 Buscador de preguntas")
    buscar_text = st.sidebar.text_input("Palabras clave")
    if st.sidebar.button("Buscar"):
        ss.search_results = buscar_preguntas(buscar_text, df)
    # Mostrar resultados previos si existen
    if 'search_results' in ss and ss.search_results is not None:
        resultados = ss.search_results
        st.sidebar.write(f"Resultados: {len(resultados)}")
        # limitar la vista para no sobrecargar la sidebar
        max_show = 30
        for i, (_, row) in enumerate(resultados.head(max_show).iterrows()):
            titulo = row.get('Pregunta', '')
            with st.sidebar.expander(f"{i+1}. {str(titulo)}"):
                st.write(row.get('Pregunta', ''))
                opciones = [op.strip() for op in str(row.get('Opciones', '')).split('\n') if op.strip()]

                # Obtener respuesta correcta normalizada
                respuesta_correcta = str(row.get('Respuesta Correcta', '')).strip()
                resp_norm = normaliza(respuesta_correcta)

                # Mostrar opciones con coincidencia exacta (normalizada)
                for opt in opciones:
                    opt_norm = normaliza(opt)
                    if opt_norm == resp_norm:
                        st.markdown(f"**✅ {opt}**")
                    else:
                        st.write(opt)

                if row.get('Es Multiple', False):
                    st.info("💡 Esta pregunta requiere seleccionar todas las respuestas correctas")
            # Botón de 'Usar esta pregunta en sesión' eliminado (no aportaba).

# =========================
# Flujo principal
# =========================
# 1) Selección de modo
if ss.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"], key="modo_selector")
    st.button("Iniciar sesión", key="btn_iniciar", on_click=cb_iniciar, args=(modo,))

# 2) Preguntas (Opción B: Responder -> feedback -> Siguiente)
elif ss.idx < len(ss.preguntas):
    fila = ss.preguntas.iloc[ss.idx]
    enunciado = fila['Pregunta']
    # Limpieza de NBSP en opciones ya desde el origen
    opciones = [op.replace("\u00A0", " ").strip() for op in fila['Opciones'].split('\n') if op.strip()]
    correcta = fila['Respuesta Correcta']

    # Mezclar opciones solo una vez por índice de pregunta
    if ss.idx not in ss.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        ss.opciones_mezcladas[ss.idx] = mezcladas
    else:
        mezcladas = ss.opciones_mezcladas[ss.idx]

    st.subheader(f"Pregunta {ss.idx + 1} / {len(ss.preguntas)}")
    st.write(enunciado)

    # Determinar si es pregunta de respuesta múltiple
    es_multiple = fila['Es Multiple']
    
    # Inicializar selección en el estado de la sesión
    seleccion_key = f"seleccion_{ss.idx}"
    if seleccion_key not in ss:
        if es_multiple:
            ss[seleccion_key] = []  # Lista vacía para checkboxes
        else:
            ss[seleccion_key] = mezcladas[0] if len(mezcladas) > 0 else ""

    # UI adaptativa según tipo de pregunta
    if es_multiple:
        st.write("**Selecciona todas las respuestas correctas:**")
        # Usar checkboxes para múltiples respuestas
        seleccion = []
        for opcion in mezcladas:
            if st.checkbox(opcion, key=f"check_{ss.idx}_{opcion}"):
                seleccion.append(opcion)
        ss[seleccion_key] = seleccion
    else:
        # Radio button para respuesta única
        if fila['Es Multiple']:
            st.write("**Selecciona todas las respuestas correctas:**")
            seleccion = []
            for opcion in mezcladas:
                if st.checkbox(opcion, key=f"check_{ss.idx}_{opcion}"):
                    seleccion.append(opcion)
            ss[seleccion_key] = seleccion
        else:
            ss[seleccion_key] = st.radio("Selecciona una opción:", mezcladas, key=f"radio_{ss.idx}")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.button(
            "Responder",
            key=f"btn_responder_{ss.idx}",
            on_click=cb_responder,
            disabled=ss.respondida
        )

    if ss.respondida:
        # Feedback usando el texto original 'correcta'
        if ss.ultima_correcta:
            st.success("✅ ¡Correcto!")
        else:
            st.error(f"❌ Incorrecto. La respuesta correcta era: {correcta}")

        with col2:
            st.button(
                "Siguiente ➜",
                key=f"btn_siguiente_{ss.idx}",
                on_click=cb_siguiente
            )

# 3) Resumen final
else:
    st.subheader("📋 Resumen de la sesión")
    total = len(ss.historial)
    aciertos = sum(1 for h in ss.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2) if total else 0.0
    st.write(f"- Total: {total} \n✅ Aciertos: {aciertos} \n❌ Errores: {errores} \n%: {porcentaje}%")

    st.write("Historial:")
    if total:
        st.dataframe(pd.DataFrame(ss.historial))
    else:
        st.info("No hay registros en esta sesión.")

    # Persistir df también al final por seguridad
    try:
        df.to_excel(file_path, index=False)
    except Exception as e:
        st.warning(f"No se pudo guardar en Excel: {e}")

    st.button("🔄 Reiniciar sesión", key="btn_reiniciar_final", on_click=cb_reiniciar)