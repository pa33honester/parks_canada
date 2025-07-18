import os
import sqlite3
import json
from typing import Any, List, Tuple, Optional, Dict

class DB:
    def __init__(self, db_file: str):
        self.db_file = db_file

    def _connect(self):
        try:
            return sqlite3.connect(self.db_file)
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            return None

    def execute(self, query: str, params: Tuple = (), commit: bool = False) -> Optional[sqlite3.Cursor]:
        """Execute a query with optional parameters. Commit if needed."""
        conn = self._connect()
        if conn is None:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            return cursor
        except sqlite3.Error as e:
            print(f"Database query error: {e}\nQuery: {query}\nParams: {params}")
            return None
        finally:
            conn.close()

    def create_table(self, create_table_sql: str) -> bool:
        """Create a table using the provided SQL statement."""
        conn = self._connect()
        if conn is None:
            return False
        try:
            conn.execute(create_table_sql)
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error creating table: {e}")
            return False
        finally:
            conn.close()

    def insert(self, table: str, data: Dict[str, Any]) -> Optional[int]:
        """Insert a row into table. Returns last row id or None on error."""
        keys = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        values = tuple(data.values())
        query = f'INSERT INTO {table} ({keys}) VALUES ({placeholders})'
        conn = self._connect()
        if conn is None:
            return None
        try:
            cursor = conn.execute(query, values)
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            print(f"Insert error: {e}\nQuery: {query}\nValues: {values}")
            return None
        finally:
            conn.close()

    def count(self, table: str, record_id):
        conn = self._connect()

        if conn is None:
            return None

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE id = ?", (record_id,))
        count = cursor.fetchone()[0]  # Get the count from the result
        return count > 0  # Return True if count is greater than 0

    def fetch_one(self, table: str, where: str = '', params: Tuple = ()) -> Optional[Dict]:
        """Fetch single row matching where clause as a dict."""
        query = f'SELECT * FROM {table}'
        if where:
            query += f' WHERE {where}'
        
        conn = self._connect()
        if conn is None:
            return None

        # Use row_factory to get dict-like access
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            print(f"Fetch one error: {e}\nQuery: {query}\nParams: {params}")
            return None
        finally:
            conn.close()

    def fetch_all(self, table: str, where: str = '', params: Tuple = ()) -> Optional[List[Dict]]:
        """Fetch all rows matching where clause as a list of dicts."""
        query = f'SELECT * FROM {table}'
        if where:
            query += f' WHERE {where}'
        conn = self._connect()
        if conn is None:
            return None
        
        # Use row_factory to get dict-like access
        conn.row_factory = sqlite3.Row
        
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            print(f"Fetch all error: {e}\nQuery: {query}\nParams: {params}")
            return None
        finally:
            conn.close()

    def update_row(self, table: str, data: Dict[str, Any], where: str, params: Tuple) -> Optional[int]:
        """Update rows matching where clause. Returns number of rows updated or None on error."""
        set_clause = ', '.join([f"{k}=?" for k in data.keys()])
        values = tuple(data.values()) + params
        query = f'UPDATE {table} SET {set_clause} WHERE {where}'
        conn = self._connect()
        if conn is None:
            return None
        try:
            cursor = conn.execute(query, values)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Update error: {e}\nQuery: {query}\nValues: {values}")
            return None
        finally:
            conn.close()

    def delete_row(self, table: str, where: str, params: Tuple) -> Optional[int]:
        """Delete rows matching where clause. Returns number of rows deleted or None on error."""
        query = f'DELETE FROM {table} WHERE {where}'
        conn = self._connect()
        if conn is None:
            return None
        try:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            print(f"Delete error: {e}\nQuery: {query}\nParams: {params}")
            return None
        finally:
            conn.close()

class Store(DB):
    def __init__(self):
        super().__init__('store.db')
        self.data = self.load('ini')

    def get(self, key = None):
        """
        Get a value from the store by key.
        If the key does not exist, it returns None.
        """
        if key is None:
            return self.data
        if key in self.data:
            return self.data[key]
        else :
            return None

    def set(self, key : str, value, flush=False):
        """
        Set a value in the store by key.
        If the key already exists, it updates the value.
        """
        if key not in self.data:
            self.data[key] = dict()
        else :
            self.data[key] = value
        
    def flush(self, file, data):
        try:
            with open(f"store/{file}.json", "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=4)
        except Exception as e:
            print(e)
    
    def load(self, file):
        data = None
        try:
            with open(f"store/{file}.json", "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except : #noqa : E722
            data = dict()
        return data

    def update(self, params : dict):
        for key in params.keys():
            self.data[key] = params[key]
        self.flush('ini', self.data)

    # return -> resource location id
    def find_location_id(self, map_id):
        row = super().fetch_one('map', 'map_id = ?', (map_id,))
        if row is None or row['resource_location_id'] is None:
            row =  super().fetch_one('location', 'root_map_id = ?', (map_id,))
            return None if row is None else row['id']
        else :
            return row['resource_location_id']

    def find_location(self, l_id):
        return super().fetch_one('location', 'id = ?', (l_id,))
    
    def find_resource(self, r_id):
        return super().fetch_one('resource', 'id = ?', (r_id,))

if __name__ == '__main__':
    
    db = DB('store.db')
    with open('.test/resourceCategory.json','r', encoding = 'utf-8') as fp:
        data = json.load(fp)
    
    db.create_table('''CREATE TABLE IF NOT EXISTS resourceCategory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,   
        name TEXT NOT NULL,
        description TEXT,
        icon TEXT,
        resource_type INTEGER NOT NULL
    )''')

    for item in data:
        db.insert('resourceCategory', {
            "id"    : item.get('id'),
            "name"  : item.get('localizedValues')[0]['name'],
            "description": item.get('localizedValues')[0].get('description', ''),
            "resource_type": item.get('resourceType', 0),
        })