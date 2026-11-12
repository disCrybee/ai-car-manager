import unittest
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from helpcrunch_bot_message_ids import guard_key, load_bot_message_ids, record_bot_message_id

class Query:
    def __init__(self,db):self.db=db
    def bind(self,*args):self.args=args;return self
    async def first(self):
        if self.args not in self.db.rows:return None
        return {"state_json":self.db.rows[self.args]}
    async def run(self):
        self.db.rows[self.args[:2]]=self.args[2]
class DB:
    def __init__(self):self.rows={}
    def prepare(self,query):return Query(self)

class BotIdsTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_ids_isolated_by_chat_and_application(self):
        db=DB()
        await record_bot_message_id(db,42,7,800)
        await record_bot_message_id(db,42,7,801)
        self.assertEqual(await load_bot_message_ids(db,42,7),[800,801])
        self.assertEqual(await load_bot_message_ids(db,43,7),[])
        self.assertEqual(await load_bot_message_ids(db,42,8),[])
        self.assertNotEqual(guard_key(42,7),guard_key(42,8))
    async def test_missing_receipt_fails(self):
        with self.assertRaises(ValueError):
            await record_bot_message_id(DB(),42,7,0)
if __name__=="__main__":unittest.main()
