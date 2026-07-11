from os.path import join, dirname, abspath, exists, splitext, basename,isdir
import sqlite3

def res_rows_to_dicts(row):
    dictionary = [dict(r) for r in row if r]
    return [{k: v for k, v in a.items() if v is not None} for a in dictionary if a]

class SQLiteDB:
    def __init__(self, db_file, check_same_thread=True, read_only=True):
        if isdir(db_file):
            db_file = join(db_file,'Metadata.db')
        self.fname = abspath(db_file)
        self.cur = None
        self.conn = None
        self.check_same_thread = check_same_thread
        self.read_only = read_only
    
    @property
    def is_connected(self):
        return self.cur is not None
    
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
            
    def open(self, **kwargs):
        if not exists(self.fname):
            raise FileNotFoundError(f"Could not find file '{self.fname}'")

        det_types = sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        if "detect_types" in kwargs:
            det_types = kwargs["detect_types"] | sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            del kwargs["detect_types"]
            
        if self.read_only:
            self.conn = sqlite3.connect(f'file:{self.fname}?mode=ro', uri=True, check_same_thread=self.check_same_thread, detect_types=det_types, **kwargs)
        else:
            self.conn = sqlite3.connect(self.fname, check_same_thread=self.check_same_thread, detect_types=det_types, **kwargs)
        
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
    
    def close(self):
        if self.is_connected:
            self.conn.close()
            self.cur = None
            self.conn = None 
            
    def query(self, query_text):
        self.cur.execute(query_text)
        rows = self.cur.fetchall()
        return res_rows_to_dicts(rows)