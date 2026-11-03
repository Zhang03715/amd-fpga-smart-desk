import unittest
from .consensus import BookFrameConsensus


def result(text='大学物理学',confidence=.96,box=(10,20,50,200),conflict=False,count=1):
    match=dict(text=text,ocr_confidence=confidence,book_box=list(box))
    return dict(matches=[dict(match) for _ in range(count)],
                decisions=[dict(v4_text=text,native_review=dict(conflict=conflict))])


def info(sequence):return dict(device='0',sequence=sequence,captured_monotonic=float(sequence))


class ConsensusTests(unittest.TestCase):
    def test_only_final_decisions_can_veto_the_match(self):
        r=result(confidence=.99)
        r['decisions'][0].update(accepted=False,recognition_conflict=True)
        p=BookFrameConsensus('大学物理学',single_frame=True,max_frames=1)
        self.assertIsNotNone(p.observe(r,info(1)))
        r['decisions'][0]['accepted']=True
        p=BookFrameConsensus('大学物理学',single_frame=True,max_frames=1)
        self.assertIsNone(p.observe(r,info(1)))

    def test_selected_glyph_review_uses_pipeline_confidence_gate(self):
        r=result(confidence=.96)
        text=r['matches'][0]['text']
        r['decisions'][0].update(accepted=True,recognition_conflict=True,
            upright_glyph_review=dict(selected=True,text=text,confidence=.96,
                attempts=[dict(selected=True,text=text,confidence=.96,
                               corroborating_text=text,corroborating_confidence=.98)]))
        p=BookFrameConsensus(text,single_frame=True,max_frames=1)
        self.assertIsNotNone(p.observe(r,info(1)))
        r['decisions'][0]['upright_glyph_review']['attempts'][0]['corroborating_text']='大学物现学'
        p=BookFrameConsensus(text,single_frame=True,max_frames=1)
        self.assertIsNone(p.observe(r,info(1)))

    def test_edition_and_main_title_share_one_spine_despite_boundary_variation(self):
        r=result()
        r['matches']=[
            dict(text='大学物理学',ocr_confidence=.998,orientation='upright',
                 book_box=[10,20,110,300],title_box=[[30,40],[50,40],[50,160],[30,160]]),
            dict(text='大学物理学（第四版）',ocr_confidence=.977,orientation='upright',
                 book_box=[0,20,140,300],title_box=[[20,30],[60,30],[60,250],[20,250]])]
        p=BookFrameConsensus('大学物理学',single_frame=True,max_frames=1)
        self.assertIsNotNone(p.observe(r,info(1)))
        self.assertEqual(p.frames[0]['matching_candidates'],1)
        r['matches'][1].update(book_box=[200,20,340,300],
                              title_box=[[220,30],[260,30],[260,250],[220,250]])
        p=BookFrameConsensus('大学物理学',single_frame=True,max_frames=1)
        self.assertIsNone(p.observe(r,info(1)))
        self.assertEqual(p.frames[0]['matching_candidates'],2)

    def test_discarded_duplicate_cannot_veto_resolved_same_location(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        r=json.loads((Path(__file__).parent/'fixtures/duplicate_glyph_conflict.json').read_text())
        target=r['matches'][0]['text']
        p=BookFrameConsensus(target,single_frame=True,max_frames=1)
        self.assertIsNotNone(p.observe(r,info(1)))
        other=deepcopy(r)
        other['decisions'][0]['accepted']=True
        other['decisions'][0]['upright_glyph_review']['selected']=False
        p=BookFrameConsensus(target,single_frame=True,max_frames=1)
        self.assertIsNone(p.observe(other,info(1)))

    def test_strong_first_frame_fast_path(self):
        p=BookFrameConsensus('大学物理学')
        self.assertIsNotNone(p.observe(result(),info(1)));self.assertTrue(p.info()['fast_path'])

    def test_miss_requires_two_new_agreeing_frames(self):
        p=BookFrameConsensus('大学物理学')
        self.assertIsNone(p.observe(result(text='大学物理实验'),info(1)))
        self.assertIsNone(p.observe(result(),info(2)))
        self.assertIsNotNone(p.observe(result(),info(3)))

    def test_low_confidence_or_conflict_needs_second_vote(self):
        for first in [result(confidence=.91),result(conflict=True)]:
            p=BookFrameConsensus('大学物理学')
            self.assertIsNone(p.observe(first,info(1)))
            self.assertIsNotNone(p.observe(result(),info(2)))

    def test_duplicate_or_changed_location_cannot_confirm(self):
        p=BookFrameConsensus('大学物理学');p.observe(result(confidence=.91),info(1))
        with self.assertRaises(ValueError):p.observe(result(),info(1))
        self.assertIsNone(p.observe(result(box=(200,20,250,200)),info(2)))
        self.assertIsNone(p.observe(result(count=2),info(3)))
        with self.assertRaises(ValueError):p.observe(result(),info(4))

    def test_below_gate_and_near_title_do_not_vote(self):
        p=BookFrameConsensus('大学物理学')
        for seq,r in enumerate([result(confidence=.89),result(text='大学物现学'),result()],1):
            self.assertIsNone(p.observe(r,info(seq)))
        self.assertFalse(p.confirmed)

    def test_disagreeing_models_and_overlapping_transcriptions_disable_fast_path(self):
        p=BookFrameConsensus('大学物理学')
        r=result(confidence=.99)
        r['decisions'][0]['recognition_conflict']=True
        self.assertIsNone(p.observe(r,info(1)))
        self.assertIsNotNone(p.observe(result(),info(2)))
        p=BookFrameConsensus('大学物理学')
        r=result(confidence=.99)
        r['matches'].append(dict(text='大学物用学',ocr_confidence=.99,book_box=[10,20,50,200]))
        self.assertIsNone(p.observe(r,info(1)))
        self.assertTrue(p.info()['frames'][0]['overlapping_transcription_conflict'])
