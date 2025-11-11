# testSafe_streamlit.py
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime, timedelta
import re
import unicodedata

# =========================
# Configuración
# =========================
ORIGINAL_FILE = 'Agil - Copia de Preguntas_Examen.xlsx'
historial_path = 'historial_sesiones.csv'
num_preguntas_por_sesion = 10
tiempo_total = timedelta(minutes=90)  # 1h 30min
TOP_K_ADAPTATIVO = 50  # pool prioritario para variedad en adaptativo

# =========================
# Saneado de Excel al arrancar (usa *_CLEAN.xlsx) - silencioso
# =========================
file_path = ORIGINAL_FILE
try:
    from fix_excel import ensure_clean
    file_path = ensure_clean(ORIGINAL_FILE) or ORIGINAL_FILE
except Exception:
    file_path = ORIGINAL_FILE  # silencioso

# =========================
# Normalización y utilidades
# =========================
def normaliza(s: str) -> str:
    """Normalización robusta para comparar textos (Unicode, NBSP, espacios, puntuación final)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    s = re.sub(r"[.;:]+$", "", s)
    return s


def split_respuestas(texto: str) -> list[str]:
    return [x.strip() for x in str(texto or "").split(";") if str(x).strip()]


def map_respuestas_a_opciones(opciones_texto: str, respuestas: list[str]) -> list[str]:
    """
    Devuelve la(s) opción(es) canónica(s) (tal como aparecen en 'Opciones') que
    corresponden a las 'Respuestas Correctas' dadas (tras normalizar).
    Regla:
      1) match por igualdad normalizada
      2) si no, por contención (elige la opción más larga)
      3) si no, devuelve la respuesta tal cual (último recurso)
    """
    ops = [o.strip() for o in str(opciones_texto or "").split("\n") if o.strip()]
    if not ops or not respuestas:
        return []
    on = {normaliza(o): o for o in ops}  # norm -> original opción
    can = []
    for r in respuestas:
        rn = normaliza(r)
        if rn in on:
            can.append(on[rn])
            continue
        # contención
        cands = [(o, len(o)) for o in ops if (normaliza(o) in rn) or (rn in normaliza(o))]
        if cands:
            best = sorted(cands, key=lambda t: t[1], reverse=True)[0][0]
            can.append(best)
        else:
            can.append(r)  # fallback
    return can

# =========================
# Carga de datos (con cache invalidable por ruta + mtime)
# =========================
@st.cache_data(show_spinner=False)
def cargar_datos(path: str, mtime: float):
    # mtime se usa para invalidar la cache cuando cambia el archivo
    df = pd.read_excel(path, engine='openpyxl')
    # Asegurar métricas
    if 'Veces Realizada' not in df.columns:
        df['Veces Realizada'] = 0
    if 'Errores' not in df.columns:
        df['Errores'] = 0
    # Limpiar nulos básicos
    df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta']).reset_index(drop=True)
    # Respuestas (lista) y Correctas Canónicas (opciones exactas)
    df['Respuestas Correctas'] = df['Respuesta Correcta'].map(split_respuestas)
    df['Correctas Canonicas'] = df.apply(
        lambda r: map_respuestas_a_opciones(r['Opciones'], r['Respuestas Correctas']),
        axis=1
    )
    # Detección MULTIPLE basada SOLO en datos coherentes (opciones ↔ respuestas)
    df['Es Multiple'] = df['Correctas Canonicas'].map(lambda xs: len(set(xs)) > 1)
    return df

df = cargar_datos(file_path, os.path.getmtime(file_path))  # ← invalida si cambia el CLEAN
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
# Lógica de preguntas
# =========================
def preparar_preguntas(df_base: pd.DataFrame, modo: str, n: int) -> pd.DataFrame:
    if modo == "Adaptativo":
        base = df_base.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
        k = min(TOP_K_ADAPTATIVO, len(base))
        top_k = base.head(k).copy()
        top_k['df_index'] = top_k.index
        return top_k.sample(n=min(n, len(top_k)), random_state=None).reset_index(drop=True)
    else:
        aleatorias = df_base.sample(n=min(n, len(df_base)), random_state=None).copy()
        aleatorias['df_index'] = aleatorias.index
        return aleatorias.reset_index(drop=True)


def cb_reiniciar():
    ss.clear()


def cb_iniciar(modo_select, n_pregs):
    ss.modo = modo_select
    ss.preguntas = preparar_preguntas(df, modo_select, n_pregs)
    ss.inicio = datetime.now()
    ss.idx = 0
    ss.respondida = False
    ss.ultima_correcta = None
    ss.opciones_mezcladas = {}


def cb_responder():
    idx = ss.idx
    pregunta = ss.preguntas.iloc[idx]
    enunciado = pregunta['Pregunta']
    # Recalcular canónicas con las opciones que se muestran (por máxima coherencia)
    correctas_canonicas = map_respuestas_a_opciones(
        pregunta['Opciones'], pregunta['Respuestas Correctas']
    )

    seleccion_key = f"seleccion_{idx}"
    if seleccion_key not in ss:
        return
    seleccion = ss[seleccion_key]
    if not isinstance(seleccion, list):
        seleccion = [seleccion]

    # Comparar contra Correctas Canónicas (normalizadas)
    seleccion_norm = {normaliza(s) for s in seleccion}
    correctas_norm = {normaliza(c) for c in correctas_canonicas}
    es_correcta = (seleccion_norm == correctas_norm)
    resultado = '✅' if es_correcta else '❌'

    registro = {
        'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Pregunta': enunciado,
        'Respuesta Dada': seleccion,
        'Respuesta Correcta': "; ".join(correctas_canonicas),
        'Resultado': resultado
    }
    ss.historial.append(registro)

    # Guardar historial y métricas (silencioso)
    try:
        historial_df = pd.DataFrame([registro])
        if os.path.exists(historial_path):
            historial_df.to_csv(historial_path, mode='a', header=False, index=False)
        else:
            historial_df.to_csv(historial_path, index=False)
    except Exception:
        pass

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
        # Persistir sobre el CLEAN
        df.to_excel(file_path, index=False)
    except Exception:
        pass

    ss.respondida = True


def cb_siguiente():
    ss.idx += 1
    ss.respondida = False
    ss.ultima_correcta = None

# =========================
# UI - Cabecera
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
# Sidebar - Buscador
# =========================
def buscar_preguntas(query: str, df_base: pd.DataFrame) -> pd.DataFrame:
    if not query or str(query).strip() == "":
        return pd.DataFrame(columns=df_base.columns)
    qn = str(query).strip().lower()

    def fila_coincide(row):
        texto_pregunta = str(row.get('Pregunta', '')).lower()
        texto_opciones = str(row.get('Opciones', '')).lower()
        texto_respuesta = str(row.get('Respuesta Correcta', '')).lower()
        texto_numero = str(row.get('Nº', row.get('N\u00ba', ''))).lower()
        return (qn in texto_pregunta or qn in texto_opciones or qn in texto_respuesta or qn == texto_numero)

    try:
        return df_base[df_base.apply(fila_coincide, axis=1)].copy()
    except Exception:
        return pd.DataFrame(columns=df_base.columns)

st.sidebar.header("🔎 Buscador de preguntas")
buscar_text = st.sidebar.text_input("Palabras clave")
if st.sidebar.button("Buscar"):
    ss.search_results = buscar_preguntas(buscar_text, df)

if 'search_results' in ss and ss.search_results is not None:
    resultados = ss.search_results
    st.sidebar.write(f"Resultados: {len(resultados)}")
    max_show = 30
    for i, (_, row) in enumerate(resultados.head(max_show).iterrows()):
        titulo = row.get('Pregunta', '')
        with st.sidebar.expander(f"{i+1}. {str(titulo)}"):
            st.write(row.get('Pregunta', ''))
            # Mapear canónicas para marcar TODAS las correctas con ✅
            correctas_canonicas = map_respuestas_a_opciones(
                row.get('Opciones', ''), split_respuestas(row.get('Respuesta Correcta', ''))
            )
            correctas_norm = {normaliza(c) for c in correctas_canonicas}
            opciones = [op.strip() for op in str(row.get('Opciones', '')).split('\n') if op.strip()]
            for opt in opciones:
                if normaliza(opt) in correctas_norm:
                    st.markdown(f"**✅ {opt}**")
                else:
                    st.write(opt)

# =========================
# Flujo principal
# =========================
if ss.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    cols = st.columns([1, 1])
    with cols[0]:
        modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"], key="modo_selector")
    with cols[1]:
        n_pregs = st.number_input("Nº preguntas", min_value=1, max_value=50, value=num_preguntas_por_sesion, step=1)
    st.button("Iniciar sesión", key="btn_iniciar", on_click=cb_iniciar, args=(modo, n_pregs))
elif ss.idx < len(ss.preguntas):
    fila = ss.preguntas.iloc[ss.idx]
    enunciado = fila['Pregunta']

    # Opciones tal cual (CLEAN) y canónicas (por coherencia total)
    opciones = [op.strip() for op in str(fila['Opciones']).split('\n') if op.strip()]
    correctas_canonicas = map_respuestas_a_opciones(fila['Opciones'], fila['Respuestas Correctas'])

    # Mezclar opciones solo una vez
    if ss.idx not in ss.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        ss.opciones_mezcladas[ss.idx] = mezcladas
    else:
        mezcladas = ss.opciones_mezcladas[ss.idx]

    st.subheader(f"Pregunta {ss.idx + 1} / {len(ss.preguntas)}")
    st.write(enunciado)

    es_multiple = len(set(correctas_canonicas)) > 1
    seleccion_key = f"seleccion_{ss.idx}"
    if seleccion_key not in ss:
        ss[seleccion_key] = [] if es_multiple else (mezcladas[0] if len(mezcladas) > 0 else "")

    if es_multiple:
        # Pregunta múltiple -> checkboxes (sin mensajes redundantes)
        seleccion = []
        for opcion in mezcladas:
            if st.checkbox(opcion, key=f"check_{ss.idx}_{opcion}"):
                seleccion.append(opcion)
        ss[seleccion_key] = seleccion
    else:
        # Respuesta única -> radio
        ss[seleccion_key] = st.radio("Selecciona una opción:", mezcladas, key=f"radio_{ss.idx}")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.button(
            "Responder",
            key=f"btn_responder_{ss.idx}",
            on_click=cb_responder,
            disabled=ss.respondida
        )
    with col2:
        st.button(
            "Siguiente ➜",
            key=f"btn_siguiente_{ss.idx}",
            on_click=cb_siguiente
        )
    with col3:
        # Descarga rápida del historial de la sesión en curso
        if ss.historial:
            hist_df = pd.DataFrame(ss.historial)
            st.download_button(
                "⬇️ Descargar sesión (CSV)",
                data=hist_df.to_csv(index=False).encode("utf-8"),
                file_name=f"historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

    if ss.respondida:
        if ss.ultima_correcta:
            st.success("✅ ¡Correcto!")
        else:
            st.error(f"❌ Incorrecto. La(s) respuesta(s) correcta(s): {'; '.join(correctas_canonicas)}")

else:
    st.subheader("📋 Resumen de la sesión")
    total = len(ss.historial)
    aciertos = sum(1 for h in ss.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2) if total else 0.0
    st.write(f"- Total: {total}\n✅ Aciertos: {aciertos}\n❌ Errores: {errores}\n%: {porcentaje}%")
    st.write("Historial:")
    if total:
        st.dataframe(pd.DataFrame(ss.historial))
    else:
        st.info("No hay registros en esta sesión.")
    try:
        df.to_excel(file_path, index=False)
    except Exception:
        pass
    st.button("🔄 Reiniciar sesión", key="btn_reiniciar_final", on_click=cb_reiniciar)