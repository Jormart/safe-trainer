# fix_excel.py
# -*- coding: utf-8 -*-
"""
Saneado robusto del Excel de preguntas:
 - Reagrupa opciones "palabra-por-línea" en frases (ventana 2..6).
 - Garantiza que la 'Respuesta Correcta' exista en 'Opciones':
     * Ajusta el texto de la respuesta a la opción real cuando hay
       diferencias menores (artículos/puntuación).
     * Si no existe, añade la opción faltante.
 - Devuelve la ruta del fichero *_CLEAN.xlsx a usar en la app.
"""
from __future__ import annotations
import os
import re
import unicodedata
from typing import List, Tuple
import pandas as pd


# ------------------ Utilidades de normalización ------------------ #

def _norm(s: str) -> str:
    """Normalización robusta para comparar textos."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    # quitar puntuación final frecuente
    s = re.sub(r"[.;:]+$", "", s)
    return s


def _split_answers(ans: str) -> List[str]:
    ans = str(ans or "").strip()
    return [a.strip() for a in ans.split(";") if a.strip()]


# ------------------ Re-agrupado de opciones ------------------ #

def _regroup_options_smart(raw_text: str, answers: List[str]) -> List[str]:
    """
    Reagrupa 'palabra-por-línea' a 'una opción por línea' intentando casar EXACTO
    cada respuesta con una ventana contigua de 2..6 términos. Repite hasta converger.
    """
    raw = [l.strip() for l in str(raw_text or "").split("\n") if l.strip()]
    if not raw:
        return []

    # si ya encaja tal cual, devuelve sin cambios
    if answers and {_norm(x) for x in answers}.issubset({_norm(o) for o in raw}):
        return raw

    changed = True
    max_win = 6
    while changed:
        changed = False
        for ans in answers:
            ansn = _norm(ans)
            if ansn in {_norm(x) for x in raw}:
                continue  # ya está
            found = False
            for start in range(len(raw)):
                for win in range(2, max_win + 1):
                    end = start + win
                    if end > len(raw):
                        break
                    cand = " ".join(raw[start:end]).replace(" - ", "-").replace("- ", "-")
                    if _norm(cand) == ansn:
                        # colapsa la ventana en una sola opción
                        raw = raw[:start] + [cand] + raw[end:]
                        changed = True
                        found = True
                        break
                if found:
                    break
        if not raw:
            break
    return raw


# ------------------ Correcciones semánticas ------------------ #

def _semantic_fix_row(options: List[str], answers: List[str]) -> Tuple[List[str], List[str], bool, int]:
    """
    Ajusta la respuesta para igualar una opción existente cuando hay variaciones menores.
    Si no existe una opción candidata, añade la respuesta como nueva opción.
    Devuelve: (opciones_actualizadas, respuestas_actualizadas, hubo_cambios_respuesta, opciones_anadidas)
    """
    on = {_norm(o) for o in options}
    new_answers = answers.copy()
    changed_answer = False
    added_options = 0

    for j, a in enumerate(answers):
        an = _norm(a)
        if an in on:
            continue
        # Buscar candidate por contención / cercanía textual
        candidates = [o for o in options if (_norm(o) in an) or (an in _norm(o))]
        if candidates:
            # Elige la opción más larga (suele ser la opción completa)
            best = max(candidates, key=len)
            new_answers[j] = best
            changed_answer = True
        else:
            # Como último recurso, añade la respuesta como opción
            if a not in options:
                options.append(a)
                on.add(an)
                added_options += 1
    return options, new_answers, changed_answer, added_options


# ------------------ Proceso principal ------------------ #

def _process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Asegurar columnas métricas
    for col in ("Veces Realizada", "Errores"):
        if col not in df.columns:
            df[col] = 0

    for i, row in df.iterrows():
        opts_txt = str(row.get("Opciones", ""))
        answers = _split_answers(row.get("Respuesta Correcta", ""))

        # 1) re-agrupado inteligente
        options = _regroup_options_smart(opts_txt, answers)
        # 2) corrección semántica
        options, answers_fixed, changed_ans, _ = _semantic_fix_row(options, answers)

        # persistir
        df.at[i, "Opciones"] = "\n".join(options)
        if changed_ans:
            df.at[i, "Respuesta Correcta"] = "; ".join(answers_fixed)

    return df


def ensure_clean(in_path: str, out_path: str | None = None, backup: bool = True) -> str:
    """
    Asegura que exista una versión *_CLEAN.xlsx* del Excel con opciones reagrupadas
    y respuestas consistentes con las opciones. Devuelve la ruta del fichero a usar.
    """
    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = f"{base}_CLEAN{ext}"

    backup_path = None
    if backup:
        base, ext = os.path.splitext(in_path)
        backup_path = f"{base}_backup{ext}"

    # Reutilizar si está actualizado
    if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(in_path):
        return out_path

    # Leer
    df = pd.read_excel(in_path, engine="openpyxl")

    # Backup una vez
    if backup and (not os.path.exists(backup_path)):
        df.to_excel(backup_path, index=False, engine="openpyxl")

    # Saneado completo
    df2 = _process_dataframe(df)
    df2.to_excel(out_path, index=False, engine="openpyxl")

    print(f"[fix_excel] CLEAN generado: {out_path}")
    return out_path


if __name__ == "__main__":
    # Ejecución autónoma (opcional)
    DEFAULT_FILE = "Agil - Copia de Preguntas_Examen.xlsx"
    result = ensure_clean(DEFAULT_FILE)
    print(f"[fix_excel] Fichero recomendado para la app: {result}")