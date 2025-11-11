# fix_excel.py
# -*- coding: utf-8 -*-
"""
Saneado robusto del Excel de preguntas:
 - Reagrupa opciones "palabra-por-línea" en frases (ventana contigua 2..6).
 - Garantiza que 'Respuesta Correcta' exista en 'Opciones':
     * Ajusta el texto de la respuesta a la opción real (variaciones menores).
     * Si no existe, añade la opción faltante.
 - Devuelve la ruta del fichero *_CLEAN.xlsx a usar en la app (silencioso).
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
    s = re.sub(r"[.;:]+$", "", s)  # quita puntuación final común
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

    if answers and {_norm(x) for x in answers}.issubset({_norm(o) for o in raw}):
        return raw  # ya encaja

    changed = True
    max_win = 6
    while changed:
        changed = False
        for ans in answers:
            ansn = _norm(ans)
            if ansn in {_norm(x) for x in raw}:
                continue  # ya está como una línea
            found = False
            for start in range(len(raw)):
                for win in range(2, max_win + 1):
                    end = start + win
                    if end > len(raw):
                        break
                    cand = " ".join(raw[start:end]).replace(" - ", "-").replace("- ", "-")
                    if _norm(cand) == ansn:
                        raw = raw[:start] + [cand] + raw[end:]  # colapsa la ventana
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
    Devuelve: (opciones_actualizadas, respuestas_actualizadas, hubo_cambio_en_respuesta, opciones_añadidas)
    """
    on = {_norm(o) for o in options}
    new_answers = answers.copy()
    changed_answer = False
    added_options = 0

    for j, a in enumerate(answers):
        an = _norm(a)
        if an in on:
            continue
        # Buscar candidata por contención / cercanía
        candidates = [o for o in options if (_norm(o) in an) or (an in _norm(o))]
        if candidates:
            best = max(candidates, key=len)  # suele ser la opción completa
            new_answers[j] = best
            changed_answer = True
        else:
            # Último recurso: añadir la respuesta como opción
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

        # 1) re-agrupado contiguo 2..6
        options = _regroup_options_smart(opts_txt, answers)
        # 2) corrección semántica (ajuste respuesta ↔ opción; alta de opción si falta)
        options, answers_fixed, changed_ans, _ = _semantic_fix_row(options, answers)

        df.at[i, "Opciones"] = "\n".join(options)
        if changed_ans:
            df.at[i, "Respuesta Correcta"] = "; ".join(answers_fixed)

    return df


def ensure_clean(in_path: str, out_path: str | None = None, backup: bool = True) -> str:
    """
    Genera (o reutiliza si está actualizado) una versión *_CLEAN.xlsx* con opciones reagrupadas
    y respuestas consistentes con las opciones. Devuelve la ruta del fichero a usar.
    (No muestra mensajes; pensado para uso interno desde Streamlit.)
    """
    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = f"{base}_CLEAN{ext}"

    backup_path = None
    if backup:
        base, ext = os.path.splitext(in_path)
        backup_path = f"{base}_backup{ext}"

    # Reutilizar si está actualizado
    try:
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(in_path):
            return out_path
    except Exception:
        # En casos raros (sistemas de ficheros), seguimos adelante y reescribimos
        pass

    # Leer
    df = pd.read_excel(in_path, engine="openpyxl")

    # Backup una vez
    try:
        if backup and (not os.path.exists(backup_path)):
            df.to_excel(backup_path, index=False, engine="openpyxl")
    except Exception:
        # Silencioso: no es crítico si falla el backup
        pass

    # Saneado completo
    df2 = _process_dataframe(df)
    df2.to_excel(out_path, index=False, engine="openpyxl")

    return out_path


if __name__ == "__main__":
    # Ejecución autónoma (opcional; sin prints para mantener silencio)
    DEFAULT_FILE = "Agil - Copia de Preguntas_Examen.xlsx"
    ensure_clean(DEFAULT_FILE)