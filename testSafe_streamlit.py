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
# Callbacks (evitan doble clic)
# =========================
def cb_responder():
    """Callback del botón Responder: registra, actualiza métricas y muestra feedback."""
    idx = ss.idx
    pregunta = ss.preguntas.iloc[idx]
    enunciado = pregunta['Pregunta']
    correcta = pregunta['Respuesta Correcta']

    # Recuperar selección actual desde el radio (clave estable por pregunta)
    seleccion_key = f"radio_{idx}"
    if seleccion_key not in ss:
        # Si no hay selección (raro), no hacemos nada
        return
    seleccion = ss[seleccion_key]

    resultado = '✅' if seleccion == correcta else '❌'
    registro = {
        'Fecha': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Pregunta': enunciado,
        'Respuesta Dada': seleccion,
        'Respuesta Correcta': correcta,
        'Resultado': resultado
    }
    ss.historial.append(registro)

    # Guardar historial (append)
    historial_df = pd.DataFrame([registro])
    if os.path.exists(historial_path):
        historial_df.to_csv(historial_path, mode='a', header=False, index=False)
    else:
        historial_df.to_csv(historial_path, index=False)

    # Actualizar contadores en df ORIGINAL usando df_index
    df_idx = ss.preguntas.loc[idx, 'df_index']
    df.at[df_idx, 'Veces Realizada'] += 1
    if resultado == '✅':
        if df.at[df_idx, 'Errores'] > 0:
            df.at[df_idx, 'Errores'] -= 1
        ss.ultima_correcta = True
    else:
        df.at[df_idx, 'Errores'] += 1
        ss.ultima_correcta = False

    # Persistir inmediatamente para que el adaptativo evolucione
    try:
        df.to_excel(file_path, index=False)
    except Exception as e:
        st.warning(f"No se pudo guardar en Excel: {e}")

    # Señalar que la pregunta ya fue respondida (para mostrar feedback y habilitar Siguiente)
    ss.respondida = True
    # No hacemos st.rerun() aquí porque queremos que el feedback se muestre en esta misma ejecución

def cb_siguiente():
    """Callback del botón Siguiente: avanza de pregunta y rerender inmediato."""
    ss.idx += 1
    ss.respondida = False
    ss.ultima_correcta = None
    # Limpiamos la mezcla de opciones de la pregunta anterior (opcional)
    # ss.opciones_mezcladas.pop(ss.idx - 1, None)
    st.rerun()

def cb_iniciar(modo_select):
    """Callback del botón Iniciar sesión: prepara el set de preguntas y reinicia cronómetro."""
    ss.modo = modo_select
    ss.preguntas = preparar_preguntas(df, modo_select, num_preguntas_por_sesion)
    ss.inicio = datetime.now()
    # Reiniciar estado de control por si venimos de una sesión anterior
    ss.idx = 0
    ss.respondida = False
    ss.ultima_correcta = None
    ss.opciones_mezcladas = {}
    st.rerun()

# =========================
# Selección de preguntas
# =========================
def preparar_preguntas(df_base: pd.DataFrame, modo: str, n: int) -> pd.DataFrame:
    """Prepara DataFrame de preguntas preservando índice original en 'df_index'."""
    if modo == "Adaptativo":
        base = df_base.sort_values(by=['Errores', 'Veces Realizada'], ascending=[False, True])
        k = min(TOP_K_ADAPTATIVO, len(base))
        top_k = base.head(k).copy()
        top_k['df_index'] = top_k.index  # índice original
        seleccion = top_k.sample(n=min(n, len(top_k)), random_state=None).reset_index(drop=True)
        return seleccion
    else:  # Aleatorio puro
        aleatorias = df_base.sample(n=min(n, len(df_base)), random_state=None).copy()
        aleatorias['df_index'] = aleatorias.index
        return aleatorias.reset_index(drop=True)

# =========================
# Cabecera y cronómetro
# =========================
st.title("🧠 Entrenador SAFe - Sesión de preguntas")

tiempo_restante = tiempo_total - (datetime.now() - ss.inicio)
if tiempo_restante.total_seconds() <= 0:
    st.error("⏰ ¡Tiempo agotado! La sesión ha finalizado.")
    if st.button("🔄 Reiniciar sesión", key="btn_reiniciar_timeout"):
        for key in list(ss.keys()):
            del ss[key]
        st.rerun()
    st.stop()
else:
    st.markdown(f"⏳ Tiempo restante: **{tiempo_restante.seconds // 60} min**")

# =========================
# Flujo principal
# =========================
# 1) Selección de modo
if ss.modo is None:
    st.subheader("Selecciona el modo de preguntas:")
    modo = st.radio("Modo:", ["Adaptativo", "Aleatorio puro"], key="modo_selector")
    # Usamos on_click con args para evitar condiciones que requieran 2 clics
    st.button("Iniciar sesión", key="btn_iniciar", on_click=cb_iniciar, args=(modo,))
# 2) Preguntas (Opción B con callbacks)
elif ss.idx < len(ss.preguntas):
    fila = ss.preguntas.iloc[ss.idx]
    enunciado = fila['Pregunta']
    opciones = [op.strip() for op in fila['Opciones'].split('\n') if op.strip()]
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

    # Radio: clave única por pregunta, NO lo deshabilitamos al responder para no provocar rerender extraño
    # El estado de "respondida" lo controlamos con botones y feedback visibles, no con disabled.
    seleccion_key = f"radio_{ss.idx}"
    st.radio("Selecciona una opción:", mezcladas, key=seleccion_key)

    col1, col2 = st.columns([1, 1])

    # Botón Responder con callback (nunca requerirá doble clic)
    with col1:
        st.button(
            "Responder",
            key=f"btn_responder_{ss.idx}",
            on_click=cb_responder,
            disabled=ss.respondida  # deshabilitado después de responder, pero la acción ya ocurrió en este render
        )

    # Feedback + Botón Siguiente (con callback + rerun)
    if ss.respondida:
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

    st.button("🔄 Reiniciar sesión", key="btn_reiniciar_final", on_click=lambda: (ss.clear(), st.rerun()))