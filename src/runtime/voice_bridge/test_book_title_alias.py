import tempfile
import threading
import unittest
from pathlib import Path
from .pynq_service import DeskService


class TitleAliasTests(unittest.TestCase):
    def test_voice_book_name_reaches_same_worker_and_retry_is_not_reexecuted(self):
        calls=[];gate=threading.Event()
        class Adapter:
            camera='0'
            def find(self,title,image,rid):
                calls.append(title);gate.wait(2)
                return dict(title=title,found=False,matches=[],indicator_lit=False,motor_action=False)
        with tempfile.TemporaryDirectory() as directory:
            service=DeskService(db_path=str(Path(directory)/'records.sqlite3'),book_adapter=Adapter())
            request=dict(v=1,type='request',id='voice-1',action='book.find',params={'book_name':'马克思主义基本原理'})
            try:
                self.assertEqual(service.handle(request)['status'],'pending')
                self.assertEqual(service.handle(request)['status'],'pending')
                gate.set()
                service.jobs['voice-1']['future'].result(timeout=2)
                events=service.poll_events()
                self.assertEqual(calls,['马克思主义基本原理'])
                self.assertEqual(events[0]['status'],'success')
                self.assertEqual(service.handle(request),events[0])
            finally:
                gate.set();service.close()

    def test_conflicting_and_missing_titles_are_rejected(self):
        class Adapter:
            def find(self,*args):raise AssertionError('must not execute')
        service=DeskService(book_adapter=Adapter())
        try:
            for index,params,error in [(1,{},'title_required'),(2,{'book_name':''},'title_required'),
                    (3,{'title':'甲','book_name':'乙'},'conflicting_book_title')]:
                result=service.handle(dict(v=1,type='request',id=str(index),action='book.find',params=params))
                self.assertEqual(result['error'],error)
            self.assertFalse(service.jobs)
        finally:service.close()


if __name__=='__main__':unittest.main()
