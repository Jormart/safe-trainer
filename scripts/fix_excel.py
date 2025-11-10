import pandas as pd
import os

def fix_excel_format():
    file_path = '../Agil - Copia de Preguntas_Examen.xlsx'
    df = pd.read_excel(file_path)
    
    # Función para limpiar el texto
    def clean_text(text):
        if not isinstance(text, str):
            return str(text).strip()
        # Reemplazar varios tipos de comillas
        text = text.replace('"', '"').replace('"', '"')
        # Normalizar saltos de línea
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        return text.strip()
    
    # Limpiar todas las columnas relevantes
    df['Pregunta'] = df['Pregunta'].apply(clean_text)
    df['Opciones'] = df['Opciones'].apply(clean_text)
    df['Respuesta Correcta'] = df['Respuesta Correcta'].apply(clean_text)
    
    # Guardar backup
    backup_path = file_path.replace('.xlsx', '_backup.xlsx')
    if not os.path.exists(backup_path):
        df_original = pd.read_excel(file_path)
        df_original.to_excel(backup_path, index=False)
    
    # Guardar archivo corregido
    df.to_excel(file_path, index=False)
    print("Excel file has been fixed. A backup was created as '_backup.xlsx'")

if __name__ == '__main__':
    fix_excel_format()