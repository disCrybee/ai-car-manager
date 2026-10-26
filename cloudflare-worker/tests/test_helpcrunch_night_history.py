import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_night_history import night_state_key, load_night_history, save_night_history

class Statement:
    def __init__(self, db, sql):
        self.db,self.sql,self.args=db,sql,()
    def bind(self,*args):
        self.args=args
        return self
    async def first(self):
        key=self.args
        return {"state_json":self.db.rows[key]} if key in self.db.rows else None
    async def run(self):
        self.db.rows[self.args[:2]]=self.args[2]
class DB:
    def __init__(self): self.rows={}
    def prepare(self,sql): return Statement(self,sql)

class NightHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_and_application_isolation(self):
        db=DB()
        turns=[{"role":"user","content":"Audi"}]
        await save_night_history(db,60354,8,turns)
        self.assertEqual(await load_night_history(db,60354,8),turns)
        self.assertEqual(await load_night_history(db,60355,8),[])
        self.assertEqual(await load_night_history(db,60354,9),[])
        self.assertLess(night_state_key(60354,8)[1],0)
    async def test_reject_invalid_chat_and_content(self):
        db=DB()
        with self.assertRaises(ValueError):
            await save_night_history(db,0,8,[])
        with self.assertRaises(ValueError):
            await save_night_history(db,5,8,[{"role":"system","content":"no"}])
if __name__=="__main__": unittest.main()
