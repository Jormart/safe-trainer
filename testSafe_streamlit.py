import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime

# Configuración
file_path = 'Agil - Copia de Preguntas_Examen.xlsx'
historial_path = 'historial_sesiones.csv'
num_preguntas_por_sesion = 10

# Cargar el archivo
df = pd.read_excel(file_path, engine='openpyxl')

# Añadir columnas si no existen
if 'Veces Realizada' not in df.columns:
    df['Veces Realizada'] = 0
if 'Errores' not in df.columns:
    df['Errores'] = 0

# Limpiar y preparar
df = df.dropna(subset=['Pregunta', 'Opciones', 'Respuesta Correcta'])
df = df.reset_index(drop=True)

# Ordenar preguntas según criterios
def ordenar_preguntas(df):
    df_ordenadas = df.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
    df_random = df.sample(frac=0.1)
    df_final = pd.concat([df_ordenadas, df_random]).drop_duplicates().reset_index(drop=True)
    return df_final.head(num_preguntas_por_sesion)

# Inicializar estado de sesión
if 'indice' not in st.session_state:
    st.session_state.indice = 0
if 'df_ordenada' not in st.session_state:
    st.session_state.df_ordenada = ordenar_preguntas(df)
if 'historial' not in st.session_state:
    st.session_state.historial = []

st.title("🧠 Sesión SAFe interactiva")
st.markdown("Yet another Python Script from Capt.Python&The6ThMan based upon Ruben Sastre Excel")

# Mostrar pregunta actual
if st.session_state.indice < len(st.session_state.df_ordenada):
    pregunta = st.session_state.df_ordenada.iloc[st.session_state.indice]
    enunciado = pregunta['Pregunta']
    opciones = pregunta['Opciones'].split('\n') if isinstance(pregunta['Opciones'], str) else []
    opciones = [op.strip() for op in opciones if op.strip()]
    random.shuffle(opciones)

    st.subheader(f"Pregunta {st.session_state.indice + 1}")
    st.write(enunciado)
    seleccion = st.radio("Selecciona una opción:", opciones)

    if st.button("Responder"):
        idx = st.session_state.df_ordenada.index[st.session_state.indice]
        respuesta_correcta = pregunta['Respuesta Correcta'].strip()
        df.at[idx, 'Veces Realizada'] += 1
        resultado = '✅' if seleccion == respuesta_correcta else '❌'

        if resultado == '✅':
            st.success("✅ ¡Correcto!")
            if df.at[idx, 'Errores'] > 0:
                df.at[idx, 'Errores'] -= 1
        else:
            st.error(f"❌ Incorrecto. La respuesta correcta era: {respuesta_correcta}")
            df.at[idx, 'Errores'] += 1

        st.session_state.historial.append({
            'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Pregunta': enunciado,
            'Respuesta Dada': seleccion,
            'Respuesta Correcta': respuesta_correcta,
            'Resultado': resultado
        })

        st.session_state.indice += 1
        st.experimental_rerun()

else:
    st.success("✅ ¡Has completado la sesión!")

    # Guardar progreso
    df.to_excel(file_path, index=False)

    # Guardar historial
    historial_df = pd.DataFrame(st.session_state.historial)
    if os.path.exists(historial_path):
        historial_df.to_csv(historial_path, mode='a', header=False, index=False)
    else:
        historial_df.to_csv(historial_path, index=False)

    # Resumen
    total = len(st.session_state.historial)
    aciertos = sum(1 for h in st.session_state.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2)

    st.subheader("📋 Resumen de la sesión")
    st.write(f"- Total de preguntas: {total}")
    st.write(f"- Aciertos: {aciertos}")
    st.write(f"- Errores: {errores}")
    st.write(f"- Porcentaje de aciertos: {porcentaje}%")

    fallos = [h['Pregunta'] for h in st.session_state.historial if h['Resultado'] == '❌']
    if fallos:
        st.subheader("🔁 Preguntas que deberías repasar:")
        for i, pregunta in enumerate(fallos[:3], 1):
            st.write(f"{i}. {pregunta}")
    else:
        st.subheader("🎉 ¡No has fallado ninguna pregunta en esta sesión!")

    st.info("✅ Progreso guardado. ¡Sigue así!")
    st.success("📊 Sesión finalizada. Progreso y respuestas guardadas.")
