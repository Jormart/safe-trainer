import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime

# Configuración
FILE_PATH = 'Agil - Copia de Preguntas_Examen.xlsx'
HISTORIAL_PATH = 'historial_sesiones.csv'
NUM_PREGUNTAS = 10

# Cargar preguntas
df = pd.read_excel(FILE_PATH, engine='openpyxl')
if 'Veces Realizada' not in df.columns:
    df['Veces Realizada'] = 0
if 'Errores' not in df.columns:
    df['Errores'] = 0
df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta']).reset_index(drop=True)

# Función para ordenar preguntas
def ordenar_preguntas(dataframe):
    ordenadas = dataframe.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
    aleatorias = dataframe.sample(frac=0.1)
    final = pd.concat([ordenadas, aleatorias]).drop_duplicates().reset_index(drop=True)
    return final.head(NUM_PREGUNTAS)

# Inicializar estado
if 'preguntas' not in st.session_state:
    st.session_state.preguntas = ordenar_preguntas(df)
    st.session_state.idx = 0
    st.session_state.historial = []
    st.session_state.opciones_mezcladas = {}
    st.session_state.mostrando_resultado = False
    st.session_state.terminado = False

# Título
st.title("🧠 Sesión SAFe interactiva")
st.caption("Yet another Python Script from Capt.Python&The6ThMan based upon Ruben Sastre Excel")

# Botón reinicio
if st.button("🔄 Reiniciar sesión"):
    st.session_state.clear()
    st.session_state.preguntas = ordenar_preguntas(df)
    st.session_state.idx = 0
    st.session_state.historial = []
    st.session_state.opciones_mezcladas = {}
    st.session_state.mostrando_resultado = False
    st.session_state.terminado = False

# Mostrar pregunta
def mostrar_pregunta():
    idx = st.session_state.idx
    pregunta = st.session_state.preguntas.iloc[idx]
    enunciado = pregunta['Pregunta']
    opciones = [op.strip() for op in pregunta['Opciones'].split('\n') if op.strip()]
    correcta = pregunta['Respuesta Correcta'].strip()

    # Mezclar opciones solo una vez
    if idx not in st.session_state.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        st.session_state.opciones_mezcladas[idx] = mezcladas
    else:
        mezcladas = st.session_state.opciones_mezcladas[idx]

    st.subheader(f"Pregunta {idx + 1}")
    st.write(enunciado)
    seleccion = st.radio("Selecciona una opción:", mezcladas, key=f"radio_{idx}")

    if st.button("Responder", key=f"btn_{idx}"):
        resultado = '✅' if seleccion == correcta else '❌'
        df_idx = st.session_state.preguntas.index[idx]
        df.at[df_idx, 'Veces Realizada'] += 1
        if resultado == '✅':
            if df.at[df_idx, 'Errores'] > 0:
                df.at[df_idx, 'Errores'] -= 1
        else:
            df.at[df_idx, 'Errores'] += 1

        st.session_state.historial.append({
            'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Pregunta': enunciado,
            'Respuesta Dada': seleccion,
            'Respuesta Correcta': correcta,
            'Resultado': resultado
        })
        st.session_state.mostrando_resultado = True

    if st.session_state.mostrando_resultado:
        ultimo = st.session_state.historial[-1]
        if ultimo['Resultado'] == '✅':
            st.success("✅ ¡Correcto!")
        else:
            st.error(f"❌ Incorrecto. La respuesta correcta era: {ultimo['Respuesta Correcta']}")
        if st.button("Siguiente pregunta"):
            st.session_state.idx += 1
            st.session_state.mostrando_resultado = False
            if st.session_state.idx >= len(st.session_state.preguntas):
                st.session_state.terminado = True

# Mostrar resumen
def mostrar_resumen():
    historial = st.session_state.historial
    total = len(historial)
    aciertos = sum(1 for h in historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2)

    st.markdown("## 📋 Resumen de la sesión")
    st.write(f"- Total de preguntas: {total}")
    st.write(f"- Aciertos: {aciertos}")
    st.write(f"- Errores: {errores}")
    st.write(f"- Porcentaje de aciertos: {porcentaje}%")

    fallos = [h['Pregunta'] for h in historial if h['Resultado'] == '❌']
    if fallos:
        st.markdown("### 🔁 Preguntas que deberías repasar:")
        for i, pregunta in enumerate(fallos[:3], 1):
            st.write(f"{i}. {pregunta}")
    else:
        st.success("🎉 ¡No has fallado ninguna pregunta!")

    # Guardar progreso
    df.to_excel(FILE_PATH, index=False)
    historial_df = pd.DataFrame(historial)
    if os.path.exists(HISTORIAL_PATH):
        historial_df.to_csv(HISTORIAL_PATH, mode='a', header=False, index=False)
    else:
        historial_df.to_csv(HISTORIAL_PATH, index=False)

    st.success("✅ Progreso guardado. ¡Sigue así!")

# Lógica principal
if not st.session_state.terminado:
    mostrar_pregunta()
else:
    mostrar_resumen()