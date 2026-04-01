import os
from typing import List

import pandas as pd


PREFERRED_LANG_COLUMN_ORDER: List[str] = [
    "zh-Hans",
    "zh-Hant",
    "de",
    "es",
    "fr",
    "hu",
    "ja",
    "ko",
    "ru",
]


def reorder_one_csv(file_path: str) -> None:
    df = pd.read_csv(file_path)

    if "en" not in df.columns:
        raise ValueError(f"{file_path}: missing required base column 'en'")

    # Base columns: everything up to and including 'en' (preserves per-file schema like DisplayName/AnimationName)
    base_cols = list(df.loc[:, :"en"].columns)

    preferred_langs = [c for c in PREFERRED_LANG_COLUMN_ORDER if c in df.columns]
    extra_cols = [c for c in df.columns if c not in base_cols and c not in preferred_langs]

    # Keep remaining columns deterministic too
    extra_cols_sorted = sorted(extra_cols)

    df = df[base_cols + preferred_langs + extra_cols_sorted]
    df.to_csv(file_path, index=False)


def walk_collage(collage_root: str) -> None:
    for root, _, files in os.walk(collage_root):
        for name in files:
            if not name.endswith(".csv"):
                continue
            reorder_one_csv(os.path.join(root, name))


if __name__ == "__main__":
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    collage_root = os.path.join(repo_root, "_collage")
    walk_collage(collage_root)

