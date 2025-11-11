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
TOP_K_ADAPTATIVO = 50

# =========================
# Saneado de Excel al arrancar (usa *_CLEAN.xlsx)
# =========================
try:
    from fix_excel import ensure_clean
    file_path = ensure_clean(ORIGINAL_FILE)  # p.ej. "Agil - Copia de Preguntas_Examen_CLEAN.xlsx"
except Exception as e:
    st.warning(f"No se pudo ejecutar el saneado de Excel: {e}")
    file_path = ORIGINAL_FILE  # fallback

# =========================
# Normalización y utilidades
# =========================
def normaliza(s: str) -> str:
    """Normalización robusta para comparar textos."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    s = re.sub(r"[.;:]+$", "", s)
    return s

def es_pregunta_multiple(row) -> bool:
    pregunta = str(row.get('Pregunta', '')).lower()
    respuesta = str(row.get('Respuesta Correcta', '')).strip()
    hints = ['select two', 'select all', 'selecciona dos', 'selecciona todas']
    return (';' in respuesta) or any(h in pregunta for h in hints)

def obtener_respuestas(row):
    r = str(row.get('Respuesta Correcta', '')).strip()
    return [x.strip() for x in r.split(';') if x.strip()]

def reagrupa_opciones_crudas(texto_opciones: str, respuestas_correctas: list[str]) -> list[str]:
    """
    Reagrupado ligero en tiempo de ejecución (protección extra).
    Si ya encaja, devuelve tal cual; si no, intenta con ventanas 2..3.
    """
    raw = [op.strip() for op in str(texto_opciones or "").split('\n') if op.strip()]
    if not raw:
        return []
    on = {normaliza(x) for x in raw}
    rn = {normaliza(x) for x in respuestas_correctas}
    if rn & on:
        return raw

    def agrupa(sz):
        res, i = [], 0
        while i < len(raw):
            chunk = raw[i:i + sz]
            if len(chunk) == sz:
                cand = " ".join(chunk).replace(" - ", "-").replace("- ", "-")
                res.append(cand)
                i += sz
            else:
                res.append(" ".join(raw[i:]))
                break
        return res

    for sz in (2, 3):
        cand = agrupa(sz)
        if {normaliza(x) for x in cand} & rn:
            return cand
    return raw

# =========================
# Carga de datos
# =========================
@st.cache_data
def cargar_datos():
    df = pd.read_excel(file_path, engine='openpyxl')

    # Asegurar métricas
    if 'Veces Realizada' not in df.columns:
        df['Veces Realizada'] = 0
    if 'Errores' not in df.columns:
        df['Errores'] = 0

    # Limpiar nulos básicos
    df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta']).reset_index(drop=True)

    # Marcar múltiple y respuestas como lista
    df['Es Multiple'] = df.apply(es_pregunta_multiple, axis=1)
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
    enunciado = pregunta['Pregunta']
    respuestas_correctas = pregunta['Respuestas Correctas']
    correcta = '; '.join(respuestas_correctas)  # <-- Fijado bug

    seleccion_key = f"seleccion_{idx}"
    if seleccion_key not in ss:
        return
    seleccion = ss[seleccion_key]
    if not isinstance(seleccion, list):
        seleccion = [seleccion]

    seleccion_norm = {normaliza(s) for s in seleccion}
    correctas_norm = {normaliza(c) for c in respuestas_correctas}
    es_correcta = (seleccion_norm == correctas_norm)
    resultado = '✅' if es_correcta else '❌'

    registro = {
        'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Pregunta': enunciado,
        'Respuesta Dada': seleccion,
        'Respuesta Correcta': correcta,
        'Resultado': resultado
    }
    ss.historial.append(registro)

    # Guardar historial
    try:
        historial_df = pd.DataFrame([registro])
        if os.path.exists(historial_path):
            historial_df.to_csv(historial_path, mode='a', header=False, index=False)
        else:
            historial_df.to_csv(historial_path, index=False)
    except Exception as e:
        st.warning(f"No se pudo guardar el historial: {e}")

    # Actualizar métricas y persistir
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
        df.to_excel(file_path, index=False)
    except Exception as e:
        st.warning(f"No se pudo actualizar/persistir métricas: {e}")

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
    st.markdown(f"⌛ Tiempo restante: **{tiempo_restante.seconds // 60} min**")

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
        texto_numero = str(row.get('Nº', '')).lower()
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
            opciones = reagrupa_opciones_crudas(row.get('Opciones', ''), obtener_respuestas(row))
            resp_correcta = str(row.get('Respuesta Correcta', '')).strip()
            resp_norm = normaliza(resp_correcta)
            for opt in opciones:
                opt_norm = normaliza(opt)
                if opt_norm == resp_norm:
                    st.markdown(f"**✅ {opt}**")
                else:
                    st.write(opt)
            if row.get('Es Multiple', False):
                st.info("💡 Esta pregunta requiere seleccionar todas las respuestas correctas")

# ==============================
# Sidebar - VALIDACIÓN DEL ARCHIVO
# ==============================
st.sidebar.subheader("✅ Validar archivo")
if st.sidebar.button("Validar formato"):
    inconsistencias = []
    for idx, row in df.iterrows():
        numero = row.get("Nº", "")
        respuestas = obtener_respuestas(row)
        opciones = reagrupa_opciones_crudas(str(row.get("Opciones", "")), respuestas)

        on = {normaliza(o) for o in opciones}
        rn = {normaliza(r) for r in respuestas}
        if respuestas and not rn.issubset(on):
            faltan = [r for r in respuestas if normaliza(r) not in on]
            inconsistencias.append(
                f"Fila {idx+2} (Nº {numero}): Respuesta(s) fuera de opciones -> {faltan}"
            )
        df.at[idx, "Opciones"] = "\n".join(opciones)

    # Asegurar métricas
    for col in ("Veces Realizada", "Errores"):
        if col not in df.columns:
            df[col] = 0

    output_file = "Preguntas_Examen_Completas_Validado.xlsx"
    try:
        df.to_excel(output_file, index=False)
        st.sidebar.success(f"Archivo validado y guardado como {output_file}")
    except Exception as e:
        st.sidebar.error(f"No se pudo guardar el archivo validado: {e}")

    if inconsistencias:
        st.sidebar.write("Inconsistencias encontradas:")
        for inc in inconsistencias:
            st.sidebar.write(f"- {inc}")
    else:
        st.sidebar.write("✅ Todas las filas cumplen el formato correcto.")

# =========================
# Flujo principal
# =========================
if ss.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"], key="modo_selector")
    st.button("Iniciar sesión", key="btn_iniciar", on_click=cb_iniciar, args=(modo,))

elif ss.idx < len(ss.preguntas):
    fila = ss.preguntas.iloc[ss.idx]
    enunciado = fila['Pregunta']

    # Reagrupa opciones (protección extra)
    opciones = reagrupa_opciones_crudas(fila['Opciones'], fila['Respuestas Correctas'])
    correcta_texto = "; ".join(fila['Respuestas Correctas'])

    # Mezclar opciones solo una vez
    if ss.idx not in ss.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        ss.opciones_mezcladas[ss.idx] = mezcladas
    else:
        mezcladas = ss.opciones_mezcladas[ss.idx]

    st.subheader(f"Pregunta {ss.idx + 1} / {len(ss.preguntas)}")
    st.write(enunciado)

    es_multiple = fila['Es Multiple']
    seleccion_key = f"seleccion_{ss.idx}"
    if seleccion_key not in ss:
        ss[seleccion_key] = [] if es_multiple else (mezcladas[0] if len(mezcladas) > 0 else "")

    if es_multiple:
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
            if ss.ultima_correcta:
                st.success("✅ ¡Correcto!")
            else:
                st.error(f"❌ Incorrecto. La respuesta correcta era: {correcta_texto}")
    with col2:
        st.button(
            "Siguiente ➜",
            key=f"btn_siguiente_{ss.idx}",
            on_click=cb_siguiente
        )

else:
    # Resumen final
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
    except Exception as e:
        st.warning(f"No se pudo guardar en Excel: {e}")
    st.button("🔄 Reiniciar sesión", key="btn_reiniciar_final", on_click=cb_reiniciar)