import streamlit as st
import pandas as pd
import random
import os
from datetime import datetime, timedelta

# =========================
# Configuración
# =========================
file_path = 'Agil - Copia de Preguntas_Examen.xlsx'
historial_path = 'historial_sesiones.csv'
num_preguntas_por_sesion = 10
tiempo_total = timedelta(minutes=90)  # 1h 30min
TOP_K_ADAPTATIVO = 50  # tamaño del "pool" prioritario para variedad en modo adaptativo

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
    # Normalizamos textos clave
    df['Pregunta'] = df['Pregunta'].astype(str).str.strip()
    df['Respuesta Correcta'] = df['Respuesta Correcta'].astype(str).str.strip()
    return df

df = cargar_datos()

# =========================
# Estado de sesión
# =========================
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
if 'ultima_correcta' not in st.session_state:
    st.session_state.ultima_correcta = None

# =========================
# Cabecera y cronómetro
# =========================
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

# =========================
# Selección de preguntas
# =========================
def preparar_preguntas(df_base: pd.DataFrame, modo: str, n: int) -> pd.DataFrame:
    """
    Devuelve un DataFrame con 'n' preguntas según el modo.
    - Adaptativo: prioriza por (Errores desc, Veces Realizada asc), toma un Top-K y samplea dentro.
    - Aleatorio puro: sample directo de df_base.
    Siempre preserva el índice original en columna 'df_index' para actualizar contadores correctamente.
    """
    if modo == "Adaptativo":
        base = df_base.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
        k = min(TOP_K_ADAPTATIVO, len(base))
        top_k = base.head(k).copy()
        top_k['df_index'] = top_k.index  # índice del df original
        seleccion = top_k.sample(n=min(n, len(top_k)), random_state=None).reset_index(drop=True)
        return seleccion
    else:  # Aleatorio puro
        aleatorias = df_base.sample(n=min(n, len(df_base)), random_state=None).copy()
        aleatorias['df_index'] = aleatorias.index
        return aleatorias.reset_index(drop=True)

# =========================
# Flujo principal
# =========================
# 1) Selección de modo y preparación de sesión
if st.session_state.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"])
    if st.button("Iniciar sesión"):
        st.session_state.modo = modo
        st.session_state.preguntas = preparar_preguntas(df, modo, num_preguntas_por_sesion)
        st.session_state.inicio = datetime.now()

# 2) Mostrar preguntas (Opción B: Responder -> feedback -> Siguiente)
elif st.session_state.idx < len(st.session_state.preguntas):
    pregunta = st.session_state.preguntas.iloc[st.session_state.idx]
    enunciado = pregunta['Pregunta']
    opciones = [op.strip() for op in pregunta['Opciones'].split('\n') if op.strip()]
    correcta = pregunta['Respuesta Correcta'].strip()

    # Mezclar opciones una sola vez por índice de pregunta en la sesión
    if st.session_state.idx not in st.session_state.opciones_mezcladas:
        mezcladas = opciones.copy()
        random.shuffle(mezcladas)
        st.session_state.opciones_mezcladas[st.session_state.idx] = mezcladas
    else:
        mezcladas = st.session_state.opciones_mezcladas[st.session_state.idx]

    st.subheader(f"Pregunta {st.session_state.idx + 1}")
    st.write(enunciado)

    # Radio con clave única por pregunta de la sesión
    seleccion = st.radio(
        "Selecciona una opción:",
        mezcladas,
        key=f"radio_{st.session_state.idx}",
        disabled=st.session_state.respondida
    )

    col1, col2 = st.columns([1, 1])

    # --- Botón Responder ---
    with col1:
        if st.button("Responder", disabled=st.session_state.respondida):
            resultado = '✅' if seleccion == correcta else '❌'

            # Registrar en historial in-memory y en CSV
            registro = {
                'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Pregunta': enunciado,
                'Respuesta Dada': seleccion,
                'Respuesta Correcta': correcta,
                'Resultado': resultado
            }
            st.session_state.historial.append(registro)

            historial_df = pd.DataFrame([registro])
            if os.path.exists(historial_path):
                historial_df.to_csv(historial_path, mode='a', header=False, index=False)
            else:
                historial_df.to_csv(historial_path, index=False)

            # Actualizar contadores en el df ORIGINAL usando df_index
            df_idx = st.session_state.preguntas.loc[st.session_state.idx, 'df_index']
            df.at[df_idx, 'Veces Realizada'] += 1
            if resultado == '✅':
                if df.at[df_idx, 'Errores'] > 0:
                    df.at[df_idx, 'Errores'] -= 1
                st.session_state.ultima_correcta = True
            else:
                df.at[df_idx, 'Errores'] += 1
                st.session_state.ultima_correcta = False

            # Persistir inmediatamente los cambios del ranking adaptativo
            df.to_excel(file_path, index=False)

            # Mostrar feedback y habilitar "Siguiente"
            st.session_state.respondida = True

    # --- Feedback y botón Siguiente ---
    if st.session_state.respondida:
        if st.session_state.ultima_correcta:
            st.success("✅ ¡Correcto!")
        else:
            st.error(f"❌ Incorrecto. La respuesta correcta era: {correcta}")

        with col2:
            if st.button("Siguiente ➜"):
                st.session_state.idx += 1
                st.session_state.respondida = False
                st.session_state.ultima_correcta = None
                st.rerun()

# 3) Resumen final
else:
    st.subheader("📋 Resumen de la sesión")
    total = len(st.session_state.historial)
    aciertos = sum(1 for h in st.session_state.historial if h['Resultado'] == '✅')
    errores = total - aciertos
    porcentaje = round((aciertos / total) * 100, 2) if total else 0.0
    st.write(f"- Total: {total} \n✅ Aciertos: {aciertos} \n❌ Errores: {errores} \n%: {porcentaje}%")
    st.write("Historial:")
    st.dataframe(pd.DataFrame(st.session_state.historial))

    # Persistir df por seguridad también al final
    df.to_excel(file_path, index=False)

    if st.button("🔄 Reiniciar sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]