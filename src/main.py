import os
import pandas as pd
import pathlib
from deep_translator import GoogleTranslator

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
}

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
            if self.lang == 'zh-Hant':
                translation_target = 'zh-TW'
            elif self.lang == 'zh-Hans':
                translation_target = 'zh-CN'
            elif self.lang == 'pt-br':
                translation_target = 'pt'
            else:
                translation_target = self.lang

            print(f'translating {sum(translate_msk)} entries for {translation_target} from {src_lang}...')
            translator = GoogleTranslator(source=src_lang, target=translation_target)

            self.df.loc[translate_msk, self.lang] = self.df[translate_msk].apply(lambda row: translator.translate(row[src_lang]), axis="columns")

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

c = Collator(dct_langs, f"..{os.sep}_collage")
c.update_collate()
