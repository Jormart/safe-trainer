# fix_excel.py
# -*- coding: utf-8 -*-
"""
Saneado robusto del Excel de preguntas:
 - Reagrupa opciones "palabra-por-línea" en frases (ventana contigua 2..6) SOLO cuando son tokens cortos.
 - Evita re-agrupado si las líneas ya son oraciones completas.
 - Si Opciones viene en una sola línea con varias oraciones, las divide en líneas (auto-split).
 - Para Nº 316..335, aplica el auto-split de forma preferente cuando detecta frases pegadas.
 - Garantiza que 'Respuesta Correcta' esté presente exactamente entre 'Opciones' (ajusta/añade si es preciso).
 - Devuelve la ruta del fichero *_CLEAN.xlsx a usar en la app (silencioso).
"""
from __future__ import annotations
import os, re, unicodedata
from typing import List, Tuple
import pandas as pd

# ------------------ Normalización ------------------ #
def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    s = re.sub(r"[.;:]+$", "", s)
    return s

def _split_answers(ans: str) -> List[str]:
    ans = str(ans or "").strip()
    return [a.strip() for a in ans.split(";") if a.strip()]

# ------------------ Detección de "frase" ------------------ #
def _is_sentence(line: str) -> bool:
    """Heurística: una 'frase' (no token suelto) si es >20 chars o >3 palabras, y suele acabar en .!?"""
    txt = (line or "").strip()
    if not txt:
        return False
    words = txt.split()
    return (len(txt) >= 20 or len(words) >= 4) or bool(re.search(r"[.!?]$", txt))

def _mostly_sentences(lines: List[str]) -> bool:
    if not lines:
        return False
    sents = sum(1 for l in lines if _is_sentence(l))
    return sents >= max(1, int(0.6 * len(lines)))  # mayoría

# ------------------ Auto-split de frases en una línea ------------------ #
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")  # punto/!/? + espacio + mayúscula

def _split_sentences_if_needed(options_text: str) -> List[str]:
    """
    Si 'Opciones' viene en 1 sola línea (o hay líneas que contienen varias oraciones),
    dividimos en frases conservando la puntuación.
    """
    raw_lines = [l.strip() for l in str(options_text or "").split("\n") if l.strip()]
    if not raw_lines:
        return []

    # Caso 1: todo en una única línea y contiene varias oraciones
    if len(raw_lines) == 1:
        line = raw_lines[0]
        # si hay al menos 2 límites de oración probables, split
        parts = [p.strip() for p in _SENT_SPLIT.split(line) if p.strip()]
        if len(parts) >= 2:
            return parts

    # Caso 2: alguna línea contiene varias frases largas -> split esa línea
    result: List[str] = []
    changed = False
    for l in raw_lines:
        parts = [p.strip() for p in _SENT_SPLIT.split(l) if p.strip()]
        if len(parts) >= 2:
            result.extend(parts)
            changed = True
        else:
            result.append(l)

    return result if changed else raw_lines

# ------------------ Re-agrupado "tokens cortos" ------------------ #
def _regroup_options_smart(raw_text: str, answers: List[str]) -> List[str]:
    """
    Reagrupa SOLO cuando las líneas parecen tokens cortos (no frases).
    Une ventanas contiguas 2..6 para casar EXACTO con la Respuesta.
    """
    raw = [l.strip() for l in str(raw_text or "").split("\n") if l.strip()]
    if not raw:
        return []

    # Si ya encaja, listo
    if answers and {_norm(x) for x in answers}.issubset({_norm(o) for o in raw}):
        return raw

    # Si la mayoría son frases, NO re-agrupes (evita unir oraciones en mega-opción)
    if _mostly_sentences(raw):
        return raw

    changed = True
    max_win = 6
    while changed:
        changed = False
        for ans in answers:
            ansn = _norm(ans)
            if ansn in {_norm(x) for x in raw}:
                continue
            found = False
            for start in range(len(raw)):
                for win in range(2, max_win + 1):
                    end = start + win
                    if end > len(raw):
                        break
                    cand = " ".join(raw[start:end]).replace(" - ", "-").replace("- ", "-")
                    if _norm(cand) == ansn:
                        raw = raw[:start] + [cand] + raw[end:]
                        changed, found = True, True
                        break
                if found:
                    break
        if not raw:
            break
    return raw

# ------------------ Correcciones semánticas ------------------ #
def _semantic_fix_row(options: List[str], answers: List[str]) -> Tuple[List[str], List[str], bool, int]:
    on = {_norm(o) for o in options}
    new_answers = answers.copy()
    changed_answer = False
    added_options = 0
    for j, a in enumerate(answers):
        an = _norm(a)
        if an in on:
            continue
        # contención (elige la opción más larga que contenga)
        candidates = [o for o in options if (_norm(o) in an) or (an in _norm(o))]
        if candidates:
            best = max(candidates, key=len)
            new_answers[j] = best
            changed_answer = True
        else:
            # último recurso: añadir como opción
            if a not in options:
                options.append(a)
                on.add(an)
                added_options += 1
    return options, new_answers, changed_answer, added_options

# ------------------ Proceso principal ------------------ #
def _process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("Veces Realizada", "Errores"):
        if col not in df.columns:
            df[col] = 0

    for i, row in df.iterrows():
        numero = row.get("Nº", "")
        opts_txt = str(row.get("Opciones", ""))
        answers = _split_answers(row.get("Respuesta Correcta", ""))

        # 1) Auto-split de frases cuando toca
        opts_split = _split_sentences_if_needed(opts_txt)

        # 2) Para las preguntas Nº 316..335, aplica el auto-split con prioridad
        if isinstance(numero, (int, float)) and 316 <= int(numero) <= 335:
            # Si tras el split sigue quedando "sospechoso" (1 línea larga), fuerza split
            if len(opts_split) == 1:
                opts_split = _split_sentences_if_needed(opts_split[0])

        # 3) Re-agrupado solo si son tokens cortos (nunca para frases)
        opciones = _regroup_options_smart("\n".join(opts_split), answers)

        # 4) Corrección semántica (ajustar respuesta ↔ opción; alta de opción si falta)
        opciones, answers_fixed, changed_ans, _ = _semantic_fix_row(opciones, answers)

        # Guardar
        df.at[i, "Opciones"] = "\n".join(opciones)
        if changed_ans:
            df.at[i, "Respuesta Correcta"] = "; ".join(answers_fixed)

    return df

def ensure_clean(in_path: str, out_path: str | None = None, backup: bool = True) -> str:
    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = f"{base}_CLEAN{ext}"
    backup_path = None
    if backup:
        base, ext = os.path.splitext(in_path)
        backup_path = f"{base}_backup{ext}"
    try:
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(in_path):
            return out_path
    except Exception:
        pass
    df = pd.read_excel(in_path, engine="openpyxl")
    try:
        if backup and (not os.path.exists(backup_path)):
            df.to_excel(backup_path, index=False, engine="openpyxl")
    except Exception:
        pass
    df2 = _process_dataframe(df)
    df2.to_excel(out_path, index=False, engine="openpyxl")
    return out_path

if __name__ == "__main__":
    DEFAULT_FILE = "Agil - Copia de Preguntas_Examen.xlsx"
    ensure_clean(DEFAULT_FILE)