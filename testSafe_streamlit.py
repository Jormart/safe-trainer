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
tiempo_total = timedelta(minutes=90)
TOP_K_ADAPTATIVO = 50

# =========================
# Saneado interno (usa *_CLEAN.xlsx)
# =========================
file_path = ORIGINAL_FILE
try:
    from fix_excel import ensure_clean
    file_path = ensure_clean(ORIGINAL_FILE) or ORIGINAL_FILE
except Exception:
    file_path = ORIGINAL_FILE

# =========================
# Utilidades
# =========================
def normaliza(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    s = re.sub(r"[.;:]+$", "", s)
    return s

def split_respuestas(texto: str) -> list[str]:
    return [x.strip() for x in str(texto or "").split(";") if x.strip()]

def map_respuestas_a_opciones(opciones_texto: str, respuestas: list[str]) -> list[str]:
    ops = [o.strip() for o in str(opciones_texto or "").split("\n") if o.strip()]
    if not ops or not respuestas:
        return []
    on = {normaliza(o): o for o in ops}
    can = []
    for r in respuestas:
        rn = normaliza(r)
        if rn in on:
            can.append(on[rn])
            continue
        cands = [(o, len(o)) for o in ops if (normaliza(o) in rn) or (rn in normaliza(o))]
        if cands:
            best = sorted(cands, key=lambda t: t[1], reverse=True)[0][0]
            can.append(best)
        else:
            can.append(r)
    return can

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
    df['Respuestas Correctas'] = df['Respuesta Correcta'].map(split_respuestas)
    df['Correctas Canonicas'] = df.apply(
        lambda r: map_respuestas_a_opciones(r['Opciones'], r['Respuestas Correctas']),
        axis=1
    )
    df['Es Multiple'] = df['Correctas Canonicas'].map(lambda xs: len(set(xs)) > 1)
    return df

df = cargar_datos()

# =========================
# Estado de sesión
# =========================
ss = st.session_state
if 'inicio' not in ss: ss.inicio = datetime.now()
if 'idx' not in ss: ss.idx = 0
if 'historial' not in ss: ss.historial = []
if 'preguntas' not in ss: ss.preguntas = None
if 'modo' not in ss: ss.modo = None
if 'opciones_mezcladas' not in ss: ss.opciones_mezcladas = {}
if 'respondida' not in ss: ss.respondida = False
if 'ultima_correcta' not in ss: ss.ultima_correcta = None

# =========================
# Lógica
# =========================
def preparar_preguntas(df_base, modo, n):
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

def cb_reiniciar(): ss.clear()

def cb_iniciar(modo_select):
    ss.modo = modo_select
    ss.preguntas = preparar_preguntas(df, modo_select, num_preguntas_por_sesion)
    ss.inicio = datetime.now()
    ss.idx = 0
    ss.respondida = False
    ss.ultima_correcta = None
    ss.opciones_mezcladas = {}

def cb_responder():
    idx = ss.idx
    pregunta = ss.preguntas.iloc[idx]
    correctas_canonicas = map_respuestas_a_opciones(pregunta['Opciones'], pregunta['Respuestas Correctas'])
    seleccion_key = f"seleccion_{idx}"
    if seleccion_key not in ss: return
    seleccion = ss[seleccion_key]
    if not isinstance(seleccion, list): seleccion = [seleccion]
    seleccion_norm = {normaliza(s) for s in seleccion}
    correctas_norm = {normaliza(c) for c in correctas_canonicas}
    es_correcta = (seleccion_norm == correctas_norm)
    registro = {
        'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Pregunta': pregunta['Pregunta'],
        'Respuesta Dada': seleccion,
        'Respuesta Correcta': "; ".join(correctas_canonicas),
        'Resultado': '✅' if es_correcta else '❌'
    }
    ss.historial.append(registro)
    try:
        historial_df = pd.DataFrame([registro])
        if os.path.exists(historial_path):
            historial_df.to_csv(historial_path, mode='a', header=False, index=False)
        else:
            historial_df.to_csv(historial_path, index=False)
    except: pass
    try:
        df_idx = ss.preguntas.loc[idx, 'df_index']
        df.at[df_idx, 'Veces Realizada'] += 1
        if es_correcta:
            if df.at[df_idx, 'Errores'] > 0: df.at[df_idx, 'Errores'] -= 1
            ss.ultima_correcta = True
        else:
            df.at[df_idx, 'Errores'] += 1
            ss.ultima_correcta = False
        df.to_excel(file_path, index=False)
    except: pass
    ss.respondida = True

def cb_siguiente():
    ss.idx += 1
    ss.respondida = False
    ss.ultima_correcta = None

# =========================
# UI
# =========================
st.title("🧠 Entrenador SAFe - Sesión de preguntas")
tiempo_restante = tiempo_total - (datetime.now() - ss.inicio)
if tiempo_restante.total_seconds() <= 0:
    st.error("⏰ ¡Tiempo agotado!")
    st.button("🔄 Reiniciar sesión", on_click=cb_reiniciar)
    st.stop()
else:
    st.markdown(f"⌛ Tiempo restante: **{tiempo_restante.seconds // 60} min**")

# Sidebar Buscador
st.sidebar.header("🔎 Buscador de preguntas")
buscar_text = st.sidebar.text_input("Palabras clave")
if st.sidebar.button("Buscar"):
    ss.search_results = df[df.apply(lambda r: buscar_text.lower() in str(r['Pregunta']).lower(), axis=1)]
if 'search_results' in ss and ss.search_results is not None:
    resultados = ss.search_results
    st.sidebar.write(f"Resultados: {len(resultados)}")
    for i, (_, row) in enumerate(resultados.head(30).iterrows()):
        with st.sidebar.expander(f"{i+1}. {row['Pregunta']}"):
            correctas_canonicas = map_respuestas_a_opciones(row['Opciones'], row['Respuestas Correctas'])
            correctas_norm = {normaliza(c) for c in correctas_canonicas}
            for opt in [o.strip() for o in row['Opciones'].split('\n') if o.strip()]:
                if normaliza(opt) in correctas_norm:
                    st.markdown(f"**✅ {opt}**")
                else:
                    st.write(opt)

# Flujo principal
if ss.modo is None:
    st.subheader("Selecciona el modo:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"])
    st.button("Iniciar sesión", on_click=cb_iniciar, args=(modo,))
elif ss.idx < len(ss.preguntas):
    fila = ss.preguntas.iloc[ss.idx]
    opciones = [o.strip() for o in fila['Opciones'].split('\n') if o.strip()]
    correctas_canonicas = map_respuestas_a_opciones(fila['Opciones'], fila['Respuestas Correctas'])
    if ss.idx not in ss.opciones_mezcladas:
        mezcladas = opciones.copy(); random.shuffle(mezcladas); ss.opciones_mezcladas[ss.idx] = mezcladas
    else:
        mezcladas = ss.opciones_mezcladas[ss.idx]
    st.subheader(f"Pregunta {ss.idx+1}/{len(ss.preguntas)}")
    st.write(fila['Pregunta'])
    es_multiple = len(set(correctas_canonicas)) > 1
    seleccion_key = f"seleccion_{ss.idx}"
    if seleccion_key not in ss:
        ss[seleccion_key] = [] if es_multiple else (mezcladas[0] if mezcladas else "")
    if es_multiple:
        seleccion = []
        for opcion in mezcladas:
            if st.checkbox(opcion, key=f"check_{ss.idx}_{opcion}"): seleccion.append(opcion)
        ss[seleccion_key] = seleccion
    else:
        ss[seleccion_key] = st.radio("Selecciona una opción:", mezcladas)
    col1, col2 = st.columns(2)
    with col1:
        st.button("Responder", on_click=cb_responder, disabled=ss.respondida)
        if ss.respondida:
            if ss.ultima_correcta: st.success("✅ ¡Correcto!")
            else: st.error(f"❌ Incorrecto. Correctas: {'; '.join(correctas_canonicas)}")
    with col2:
        st.button("Siguiente ➜", on_click=cb_siguiente)
else:
    st.subheader("📋 Resumen")
    total = len(ss.historial)
    aciertos = sum(1 for h in ss.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    st.write(f"Total: {total} | ✅ {aciertos} | ❌ {errores} | % {round((aciertos/total)*100,2) if total else 0}")
    st.dataframe(pd.DataFrame(ss.historial))
    st.button("🔄 Reiniciar sesión", on_click=cb_reiniciar)