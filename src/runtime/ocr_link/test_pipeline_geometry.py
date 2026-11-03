"""Replay captured CUDA stage outputs to verify optional service integration."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from ocr_link.pipeline import GPUPipeline

ROOT=Path(__file__).resolve().parents[1]


class PipelineGeometryTests(unittest.TestCase):
    def test_experiment_preserves_legacy_matches_and_default_is_isolated(self):
        source=ROOT/'output/ocr-link-server/pc-multi-b-grouped-v2-20261014-01'
        if not (source/'pipeline/input_hybrid.json').exists():
            self.skipTest('captured full CUDA stage outputs unavailable')
        original=json.loads((source/'pipeline/input_hybrid.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(dir=ROOT/'output') as temporary:
            base=Path(temporary)
            dummy=base/'existing-path'
            dummy.write_text('local replay fixture',encoding='utf-8')
            for enabled in (False,True):
                destination=base/str(enabled)
                destination.mkdir()
                def replay(*args,**kwargs):
                    shutil.copytree(source/'pipeline',destination/'pipeline',dirs_exist_ok=True)
                    process=MagicMock()
                    process.returncode=0
                    return process
                with patch('ocr_link.pipeline.subprocess.Popen',side_effect=replay):
                    result=GPUPipeline(dummy,dummy,dummy,upright_geometry=enabled)(
                        source/'input.jpg',dict(action='book.scan',params={}),destination)
                self.assertEqual(result['matches'],original)
                self.assertEqual(result['geometry_mode'],'upright_experimental' if enabled else 'legacy')
                self.assertEqual(result['geometry_quality_evaluated'],enabled)
                if not enabled:
                    self.assertIsNone(result['geometry_review_required_count'])
                self.assertEqual((destination/'upright_geometry.json').exists(),enabled)
                self.assertEqual(len(result['text_regions']),len(original))
                self.assertFalse(result['motor_action'])
                if enabled:
                    self.assertEqual(result['spine_count'],9)
                    self.assertEqual(result['text_regions'][10]['spine_group_id'],
                                     result['text_regions'][12]['spine_group_id'])
                    self.assertNotEqual(result['text_regions'][10]['spine_group_id'],
                                        result['text_regions'][11]['spine_group_id'])


if __name__=='__main__':
    unittest.main()
