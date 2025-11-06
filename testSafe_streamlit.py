import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime, timedelta

# Configuración
file_path = 'Agil - Copia de Preguntas_Examen.xlsx'
historial_path = 'historial_sesiones.csv'
num_preguntas_por_sesion = 10
tiempo_total = timedelta(minutes=90)  # 1h 30min

# Cargar datos
@st.cache_data
def cargar_datos():
    df = pd.read_excel(file_path, engine='openpyxl')
    if 'Veces Realizada' not in df.columns:
        df['Veces Realizada'] = 0
    if 'Errores' not in df.columns:
        df['Errores'] = 0
    df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta']).reset_index(drop=True)
    return df

df = cargar_datos()

# Inicializar estado
if 'inicio' not in st.session_state:
    st.session_state.inicio = datetime.now()
if 'idx' not in st.session_state:
    st.session_state.idx = 0
if 'historial' not in st.session_state:
    st.session_state.historial = []
if 'preguntas' not in st.session_state:
    st.session_state.preguntas = None
if 'modo' not in st.session_state:
    st.session_state.modo = None
if 'opciones_mezcladas' not in st.session_state:
    st.session_state.opciones_mezcladas = {}
if 'respondida' not in st.session_state:
    st.session_state.respondida = False

# Título y cronómetro
st.title("🧠 Entrenador SAFe - Sesión de preguntas")
tiempo_restante = tiempo_total - (datetime.now() - st.session_state.inicio)
if tiempo_restante.total_seconds() <= 0:
    st.error("⏰ ¡Tiempo agotado! La sesión ha finalizado.")
    if st.button("🔄 Reiniciar sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
    st.stop()
else:
    st.markdown(f"⏳ Tiempo restante: **{tiempo_restante.seconds//60} min**")

# Selección de modo
if st.session_state.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"])
    if st.button("Iniciar sesión"):
        st.session_state.modo = modo
        if modo == "Adaptativo":
            df_ordenadas = df.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
            df_random = df.sample(frac=0.1)
            st.session_state.preguntas = pd.concat([df_ordenadas, df_random]).drop_duplicates().reset_index(drop=True).head(num_preguntas_por_sesion)
        else:
            st.session_state.preguntas = df.sample(n=num_preguntas_por_sesion).reset_index(drop=True)
        st.session_state.inicio = datetime.now()

# Mostrar preguntas
elif st.session_state.idx < len(st.session_state.preguntas):
    pregunta = st.session_state.preguntas.iloc[st.session_state.idx]
    enunciado = pregunta['Pregunta']
    opciones = [op.strip() for op in pregunta['Opciones'].split('\n') if op.strip()]
    correcta = pregunta['Respuesta Correcta'].strip()

    # Mezclar opciones una sola vez
    if st.session_state.idx not in st.session_state.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        st.session_state.opciones_mezcladas[st.session_state.idx] = mezcladas
    else:
        mezcladas = st.session_state.opciones_mezcladas[st.session_state.idx]

    st.subheader(f"Pregunta {st.session_state.idx + 1}")
    st.write(enunciado)
    seleccion = st.radio("Selecciona una opción:", mezcladas, key=f"radio_{st.session_state.idx}")

    if st.button("Responder") and not st.session_state.respondida:
        resultado = '✅' if seleccion == correcta else '❌'
        st.session_state.historial.append({
            'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Pregunta': enunciado,
            'Respuesta Dada': seleccion,
            'Respuesta Correcta': correcta,
            'Resultado': resultado
        })
        df_idx = st.session_state.preguntas.index[st.session_state.idx]
        df.at[df_idx, 'Veces Realizada'] += 1
        if resultado == '✅':
            if df.at[df_idx, 'Errores'] > 0:
                df.at[df_idx, 'Errores'] -= 1
            st.success("✅ ¡Correcto!")
        else:
            df.at[df_idx, 'Errores'] += 1
            st.error(f"❌ Incorrecto. La respuesta correcta era: {correcta}")
        st.session_state.respondida = True

    if st.session_state.respondida:
        if st.button("Siguiente pregunta"):
            st.session_state.idx += 1
            st.session_state.respondida = False

# Resumen final
else:
    st.subheader("📋 Resumen de la sesión")
    total = len(st.session_state.historial)
    aciertos = sum(1 for h in st.session_state.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2)
    st.write(f"- Total: {total} | ✅ Aciertos: {aciertos} | ❌ Errores: {errores} | %: {porcentaje}%")

    st.write("Historial:")
    st.dataframe(pd.DataFrame(st.session_state.historial))

    df.to_excel(file_path, index=False)
    historial_df = pd.DataFrame(st.session_state.historial)
    if os.path.exists(historial_path):
        historial_df.to_csv(historial_path, mode='a', header=False, index=False)
    else:
        historial_df.to_csv(historial_path, index=False)

    if st.button("🔄 Reiniciar sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]