from concurrent.futures import Future
from unittest.mock import patch
import unittest
from .run import AdapterService
from .menu import Menu


class BookLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.service=AdapterService(book_image='fixture.jpg',clock=lambda:self.now)
        self.future=Future()
        self.submit=patch.object(self.service.worker,'submit',return_value=self.future)
        self.submit.start()

    def tearDown(self):
        self.submit.stop()
        self.service.close()

    def request(self,rid='one'):
        return self.service.handle(dict(v=1,type='request',id=rid,action='book.find',params={'title':'Test book'}))

    def finish(self,found=True):
        self.future.set_result(dict(found=found,title='Test book',matches=[{'text':'Test book'}] if found else []))
        self.service.collect_jobs()

    def test_request_result_and_menu_share_state(self):
        self.assertEqual(self.request()['status'],'pending')
        self.assertEqual(self.service.book_view['state'],'searching')
        self.finish()
        self.assertEqual(self.service.execute('book.status',{})['state'],'found')
        self.assertFalse(self.service.book_view['indicator_lit'])
        menu=Menu(self.service);menu.page='book'
        self.assertEqual(menu.render().size,(240,320))

    def test_absent_and_worker_failure_are_distinct(self):
        self.request();self.finish(False)
        self.assertEqual(self.service.book_view['state'],'not_found')

    def test_failure_is_visible(self):
        self.request();self.future.set_exception(ValueError('network_timeout'))
        self.service.collect_jobs()
        self.assertEqual(self.service.book_view['state'],'failed')
        self.assertEqual(self.service.book_view['error'],'network_timeout')

    def test_expired_result_does_not_stay_available_for_guidance(self):
        self.request();self.finish();self.now=31
        view=self.service.execute('book.status',{})
        self.assertEqual(view['state'],'expired')
        self.assertEqual(view['result'],{})

    def test_invalid_new_request_replaces_old_success_on_display(self):
        self.request();self.finish()
        self.service.handle(dict(v=1,type='request',id='bad',action='book.find',params={'title':''}))
        self.assertEqual(self.service.book_view['state'],'failed')

    def test_cancelled_running_job_cannot_repopulate_display(self):
        self.request();self.future.set_running_or_notify_cancel()
        self.service.execute('book.cancel',{})
        self.finish()
        self.assertEqual(self.service.book_view['state'],'cancelled')

    def test_timeout_and_idempotent_retry_do_not_revive_view(self):
        self.request();self.now=91
        self.assertEqual(self.service.execute('book.status',{})['state'],'timeout')
        self.request()
        self.assertEqual(self.service.book_view['state'],'timeout')
        self.finish()
        self.assertEqual(self.service.book_view['state'],'timeout')

    def test_late_completion_without_intermediate_poll_does_not_appear_fresh(self):
        self.request();self.now=91;self.finish()
        self.assertEqual(self.service.book_view['state'],'timeout')

    def test_retry_of_older_pending_job_does_not_steal_new_display(self):
        self.request('one')
        newer=Future()
        with patch.object(self.service.worker,'submit',return_value=newer):
            self.request('two')
        self.request('one')
        self.assertEqual(self.service.book_view['request_id'],'two')
        newer.cancel();self.future.cancel()

    def test_status_snapshot_cannot_modify_cached_result(self):
        self.request();self.finish()
        view=self.service.execute('book.status',{})
        view['result']['matches'].clear()
        self.assertEqual(len(self.service.execute('book.status',{})['result']['matches']),1)

    def test_returning_to_timer_does_not_restart_it(self):
        menu=Menu(self.service);menu.index=1;menu.key('ok')
        self.now=60;before=self.service.timer_status()['remaining_seconds']
        menu.key('back');menu.key('ok')
        self.assertEqual(self.service.timer_status()['remaining_seconds'],before)


if __name__=='__main__':
    unittest.main()
