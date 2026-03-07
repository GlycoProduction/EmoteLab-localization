import os
import pandas as pd
from deep_translator import GoogleTranslator
import iso639_1

# --- Configuration ---
SOURCE_COL = 'en'  # The column to translate

def proc_file(file_path, target_lang, translator):
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)

    # 1. Ensure the target column exists
    if target_lang not in df.columns:
        print(f"missing column {target_lang}")
        return

    # 2. Identify rows that need translation (Source exists AND Target is null)
    mask = (df[SOURCE_COL] != "") & (df[target_lang] == "")

    rows_to_translate = df[mask]

    if rows_to_translate.empty:
        print(f"is complete, not updated")
        return

    print(f"Translating {len(rows_to_translate)} rows...", end="")

    # Convert only the filtered rows to a list
    texts = rows_to_translate[SOURCE_COL].astype(str).tolist()

    # Translate batch
    translated_texts = translator.translate_batch(texts)

    # 3. Use .loc to update ONLY the specific rows that were null
    df.loc[mask, target_lang] = translated_texts

    # Save the updated CSV
    df.to_csv(file_path, index=False)
    print(f"Updated successfully.")

def proc_files(root_folder, target_lang):
    # Initialize the translator once to reuse
    translator = GoogleTranslator(source='auto', target=target_lang)

    # Walk through folders recursively
    for root, _, files in os.walk(root_folder):
        for file in files:
            if file.endswith('.csv'):
                file_path = os.path.join(root, file)
                print(f"{file} ", end="")
                try:
                    proc_file(file_path, target_lang, translator)
                except Exception as e:
                    print(f"Error in {file}: {e}")

def proc(root):
    dirs = set(os.listdir(root))
    dirs.intersection_update(x.name.lower() for x in iso639_1.language)
    for lang in dirs:
        proc_files(f"{root}/{lang}", lang)

if __name__ == "__main__":
    proc('../')