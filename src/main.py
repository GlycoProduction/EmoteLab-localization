import html
import os
import pathlib
import time
import uuid

import pandas as pd
import requests

"""
input:
collated csv files (row reference)
ordered dict langlist
dct = {
    lang: translation src,  - translation source not working right now, just sources english
    ...
}

1. create missing langs based on langlist
2. update rows (strings) based on _collage
3. machine translate missing items based on dct
4. collate, summarize

Set AZURE_TRANSLATOR_KEY (and usually AZURE_TRANSLATOR_REGION) from an Azure Translator resource.
See the Azure setup notes at the bottom of this file's run error, or README-style comment in azure_credentials().
"""

dct_langs = {
    'zh-Hans': None,  # src lang None indicates manual translation only
    'zh-Hant': 'zh-Hans',
    'de': 'en',
    'es': 'en',
    'fr': 'en',
    'hu': 'en',
    'ja': 'zh-Hans',
    'ko': 'zh-Hans',
    'ru': 'en',
    'pt-br': 'en',
    'uk': 'en',
    'it': 'en',
    'th': 'en',
    'tr': 'en',
    'sv': 'en',
    'sk': 'en',
}

_AZURE_BATCH_SIZE = 1000  # Azure max array elements per request
_AZURE_MAX_CHARS = 50000  # Azure max characters per request


class MissingApiKeyError(RuntimeError):
    pass


def _load_dotenv():
    """Load KEY=VALUE pairs from .env without overriding real environment variables."""
    here = pathlib.Path(__file__).resolve()
    for path in (here.parent / ".env", here.parent.parent / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def azure_credentials():
    _load_dotenv()
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
    endpoint = os.environ.get(
        "AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com"
    ).rstrip("/")
    if not key:
        raise MissingApiKeyError(
            "Azure Translator needs a resource key.\n"
            "1. Create a free Azure account: https://azure.microsoft.com/free/\n"
            "2. In Azure Portal, create a Translator resource (pricing tier F0).\n"
            "3. Open Keys and Endpoint; copy Key 1 and Location/Region.\n"
            "4. Set AZURE_TRANSLATOR_KEY and AZURE_TRANSLATOR_REGION "
            "(in the environment or a .env file next to main.py)."
        )
    return key, region, endpoint


class AzureTranslator:
    """Official Azure Translator Text API v3."""

    def __init__(self, source: str, target: str, credentials=None):
        self.source = source
        self.target = target
        key, region, endpoint = credentials or azure_credentials()
        self.api_key = key
        self.region = region
        self.endpoint = endpoint

    def translate(self, text: str) -> str:
        return self.translate_batch([text])[0]

    def translate_batch(self, texts: list[str]) -> list[str]:
        out = [""] * len(texts)
        pending = [
            i for i, text in enumerate(texts)
            if isinstance(text, str) and text.strip()
        ]
        start = 0
        while start < len(pending):
            chunk = []
            chars = 0
            while start + len(chunk) < len(pending) and len(chunk) < _AZURE_BATCH_SIZE:
                idx = pending[start + len(chunk)]
                piece = texts[idx].strip()
                if chunk and chars + len(piece) > _AZURE_MAX_CHARS:
                    break
                chunk.append(idx)
                chars += len(piece)
            translated = self._request([texts[i].strip() for i in chunk])
            for i, value in zip(chunk, translated):
                out[i] = value
            start += len(chunk)
        return out

    def _request(self, queries: list[str]) -> list[str]:
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "X-ClientTraceId": str(uuid.uuid4()),
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.endpoint}/translate",
                    params={
                        "api-version": "3.0",
                        "from": self.source,
                        "to": self.target,
                        "textType": "plain",
                    },
                    headers=headers,
                    json=[{"Text": text} for text in queries],
                    timeout=60,
                )
            except requests.RequestException as ex:
                last_error = ex
                time.sleep(1.5 * (attempt + 1))
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait_s = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 2)
                print(f"[rate-limit] Azure Translator 429; retrying in {wait_s}s")
                time.sleep(wait_s)
                last_error = RuntimeError(response.text)
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Azure Translator HTTP {response.status_code}: {response.text}"
                )

            payload = response.json()
            if len(payload) != len(queries):
                raise RuntimeError(
                    f"Azure Translator returned {len(payload)} results "
                    f"for {len(queries)} inputs"
                )
            return [
                html.unescape(item["translations"][0].get("text", "")).strip()
                for item in payload
            ]
        raise last_error


class CSVFile:
    def __init__(self, filepath, df):
        self.key = 'Key'  # join key
        self.filepath = filepath
        self.df = df

    @classmethod
    def from_filepath(cls, filepath, **kwargs):
        df = pd.read_csv(filepath)
        # Pass the df and any extra kwargs (like lang) to the constructor
        return cls(filepath, df, **kwargs)

    def __repr__(self):
        return f'"{self.filepath.split(os.sep)[-1]}" on key "{self.key}"'

    def write(self, path=None):
        if path is None:
            path = self.filepath
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(path, index=False)

class LanguageCSVFile(CSVFile):
    def __init__(self, filepath, df, lang):
        super().__init__(filepath, df)
        self.lang = lang

    def update(self, ref: CSVFile):
        # put all rows from reference into csv
        df = pd.merge(ref.df, self.df, how='left', left_on=ref.key, right_on=self.key, suffixes=('', '_y'))
        msk_changed = df['en'] != df['en_y']

        # For non-main-menu files we join DisplayName (ref) -> Key (locale).
        # New rows won't have a right-side Key, so backfill locale Key from the ref join key.
        if 'Key' in df.columns and ref.key in df.columns:
            df['Key'] = df['Key'].fillna(df[ref.key])
        elif ref.key in df.columns:
            df['Key'] = df[ref.key]

        df = df[self.df.columns]
        df.loc[msk_changed, 'reviewed'] = False  # if the english string has changed, reset the reviewed flag
        df['reviewed'] = df['reviewed'].fillna(False)
        df[self.lang] = df[self.lang].fillna("")
        self.df = df

    def translate(self):
        # machine translate empty
        src_lang = 'en'

        translate_msk = (self.df[self.lang] == "") & (~self.df["reviewed"].astype(bool))
        translate_msk &= self.df[src_lang] != ""
        if translate_msk.any():
            if self.lang == 'pt-br':
                translation_target = 'pt'  # Azure: pt = Brazilian Portuguese
            else:
                # zh-Hans / zh-Hant already match Azure language codes
                translation_target = self.lang

            n = int(translate_msk.sum())
            print(f'translating {n} entries for {translation_target} from {src_lang}...')
            src_texts = self.df.loc[translate_msk, src_lang].astype(str).tolist()
            try:
                translator = AzureTranslator(source=src_lang, target=translation_target)
                results = translator.translate_batch(src_texts)
            except Exception as ex:
                print(f'[warn] batch translation failed for {self.lang}: {ex}')
                # Leave empty so a later run can retry (do not fallback to English).
                results = [""] * n

            self.df.loc[translate_msk, self.lang] = results

    def summary(self):
        return self.df.loc[:, 'reviewed'].sum(), len(self.df)


class CSVDir:
    def __init__(self, dirpath):
        self.files = [CSVFile.from_filepath(filepath) for filepath in recursive_csvs(dirpath)]

    def dirpath(self, lang):
        return f'..{os.sep}{lang}'

class RefDir(CSVDir):
    def __init__(self):
        super().__init__(self.dirpath('_collage'))
        """
        current patterns: 
        Key, en                         (Main Menu String Table)
        *(wildcard), DisplayName, en    (other; DisplayName is join key)
        """
        for f in self.files:
            col_idx = f.df.columns.get_loc('en') + 1
            f.df = f.df.iloc[:, :col_idx]
            if f.filepath.split(os.sep)[-1] == "Main Menu String Table.csv":
                f.key = "Key"
            else:
                f.key = "DisplayName"
        self.files = {f.filepath: f for f in self.files}

    def lang_filepaths(self, lang):
        # returns the expected file paths corresponding to a language
        # append _{lang} to file names
        # adjust path
        lang_paths = [None] * len(self.files)
        for i, f in enumerate(self.files.values()):
            altpath = self.dirpath(lang) + f.filepath[len(self.dirpath('_collage')):]
            altpath = altpath.split('.csv')[0] + f'_{lang}.csv'
            lang_paths[i] = (f.filepath, altpath)
        return lang_paths


class LangDir(CSVDir):
    def __init__(self, lang):
        self.files = [LanguageCSVFile.from_filepath(filepath, lang=lang) for filepath in recursive_csvs(super().dirpath(lang))]
        """
        (cols: Key, en, {lang}, reviewed)
        """
        for f in self.files:
            f.df = f.df.loc[:, ['Key', 'en', f'{lang}', 'reviewed']]
        self.files = {f.filepath: f for f in self.files}
        self.lang = lang

    def update(self, ref: RefDir):
        """
        look for dir/file
        if not exist: create
        if exist: match rows
        translate
        """
        # loop through reference files
        for (reffp, langfp) in ref.lang_filepaths(self.lang):
            if langfp not in self.files.keys():
                # not exists - create
                f = LanguageCSVFile(langfp, ref.files[reffp].df, self.lang)
                f.df = f.df.rename(columns={ref.files[reffp].key: 'Key'})
                f.df[self.lang] = ""
                f.df['reviewed'] = False
                f.df = f.df.loc[:, ['Key', 'en', f'{self.lang}', 'reviewed']]
                self.files[langfp] = f
            else:
                self.files[langfp].update(ref.files[reffp])
            self.files[langfp].translate()
            self.files[langfp].write()

    def summary(self):
        reviewed, total = 0, 0
        for f in self.files.values():
            a, b = f.summary()
            reviewed += a
            total += b
        print(f"{self.lang:8}: {reviewed/total:.2%}")
        return reviewed, total

def recursive_csvs(root):
    lst = []
    for fileroot, _, files in os.walk(root):
        lst += [f"{fileroot}{os.sep}{file}" for file in files if file.endswith('.csv')]
    return lst

class Collator:
    def __init__(self, dct_langs, collage_path):
        # load references (key, en) from collage files
        self.dct_langs = dct_langs
        self.refdir = RefDir()

    def update_collate(self):
        # foreach
        """
        update each language
        """
        for k, v in self.dct_langs.items():
            ld = LangDir(k)
            ld.update(self.refdir)
            ld.summary()
            self.collate(ld, k)
        for f in self.refdir.files.values():
            f.write()

    def collate(self, ld: LangDir, lang):
        for (reffp, langfp) in self.refdir.lang_filepaths(lang):
            if self.refdir.files[reffp].key == ld.files[langfp].key:
                self.refdir.files[reffp].df = pd.merge(
                    self.refdir.files[reffp].df,
                    ld.files[langfp].df.loc[:, [ld.files[langfp].key, lang]],
                    how='left',
                    on=ld.files[langfp].key
                )
            else:
                self.refdir.files[reffp].df = pd.merge(
                    self.refdir.files[reffp].df,
                    ld.files[langfp].df.loc[:, [ld.files[langfp].key, lang]],
                    how='left',
                    left_on=self.refdir.files[reffp].key,
                    right_on=ld.files[langfp].key
                ).drop(columns=ld.files[langfp].key)

if __name__ == "__main__":
    azure_credentials()
    c = Collator(dct_langs, f"..{os.sep}_collage")
    c.update_collate()
