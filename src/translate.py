import os
import pandas as pd
from deep_translator import GoogleTranslator

# --- Configuration ---
SOURCE_COL = 'en'  # The column to translate

def safe_translate(text, translator):
    # Basic check for empty strings or purely whitespace
    try:
        return translator.translate(text)
    except Exception:
        # If any error occurs, return a placeholder
        return text

def translate_file(file_path, target_lang_code, translator):
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)

    print(f"translating {file_path} ", end="")
    # 1. Ensure the target column exists
    if target_lang_code not in df.columns:
        print(f"missing column {target_lang_code}")
        return

    # 2. Identify rows that need translation (Source exists AND Target is null)
    mask = (df[SOURCE_COL] != "") & (df[target_lang_code] == "")

    rows_to_translate = df[mask]

    if rows_to_translate.empty:
        print(f"is complete, not updated")
        return

    print(f"Translating {len(rows_to_translate)} rows...", end="")

    # Convert only the filtered rows to a list
    texts = rows_to_translate[SOURCE_COL].astype(str).tolist()

    # Translate batch
    translated_texts = [safe_translate(t, translator) for t in texts]

    # 3. Use .loc to update ONLY the specific rows that were null
    df.loc[mask, target_lang_code] = translated_texts

    # Save the updated CSV
    df.to_csv(file_path, index=False)
    print(f"Updated successfully.")

def add_reviewed_column(file_path):
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    if len(df.columns) == 3 and 'reviewed' not in df.columns:
        df['reviewed'] = False
        df.to_csv(file_path, index=False)

def lang_dir_walk(lang_root, desc_str, func):
    for root, _, files in os.walk(lang_root):
        for file in files:
            if not file.endswith('.csv'):
                continue
            file_path = os.path.join(root, file)
            try:
                func(file_path)
            except Exception as e:
                print(f"Error {desc_str} {file}: {e}")

def lang_dirs(root):
    dirs = set(os.listdir(root))
    langs = GoogleTranslator().get_supported_languages(as_dict=True).values()

    return dirs.intersection(langs).union({'zh-Hant'})

def proc(root):
    for dirstr in lang_dirs(root):
        if dirstr == 'zh-Hant':
            target_code = 'zh-TW'
        else:
            target_code = dirstr
        translator = GoogleTranslator(source=SOURCE_COL, target=target_code)
        lang_dir_walk(root + dirstr, 'translate', lambda x: translate_file(x, dirstr, translator))

if __name__ == "__main__":
    proc('../')