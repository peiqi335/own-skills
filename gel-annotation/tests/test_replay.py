"""Narrow checks for recovered operations and the existing new-input batch mechanism."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import annotate_gel as annotation
import replay_operations as operations
import batch_replay
from compare_replay import compare


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(tempfile.mkdtemp(prefix='gel-replay-',dir='/tmp/opencode'))
        self.source=self.base/'source.png'
        image=Image.new('RGB',(1600,1600),(60,60,60))
        image.putpixel((2,2),(90,80,70));image.save(self.source)
        self.recipe=dict(schema_version=1,start='old',inputs={'old':dict(path=self.source.name,sha256=annotation.sha256(self.source))},
                         font=dict(path=str(annotation.FONT),sha256=annotation.sha256(annotation.FONT)),
                         operations=[dict(op='rectangle',box=[0,0,5,5],fill=[0,0,0]),dict(op='restore_gray',boxes=[[0,0,5,5]])])

    def test_gray_restore_preserves_only_original_nonzero_grayscale(self):
        image=operations.render(self.recipe,self.base)
        self.assertEqual(image.getpixel((1,1)),(60,60,60))
        self.assertEqual(image.getpixel((2,2)),(0,0,0))

    def test_whole_batch_preflight_rejects_last_item_without_output(self):
        one=self.base/'one.json';two=self.base/'two.json'
        operations.write_json(one,self.recipe)
        bad=copy.deepcopy(self.recipe);bad['operations'].append(dict(op='not-an-operation'))
        operations.write_json(two,bad)
        batch=self.base/'batch.json'
        operations.write_json(batch,dict(schema_version=1,items=[dict(id='one',spec=one.name,sha256=annotation.sha256(one)),
                                                               dict(id='two',spec=two.name,sha256=annotation.sha256(two))]))
        output=self.base/'output'
        with self.assertRaises(SystemExit):operations.replay(batch,output)
        self.assertFalse(output.exists())

    def test_byte_and_pixel_comparison_are_separate(self):
        other=self.base/'other.png'
        with Image.open(self.source) as image:image.save(other,compress_level=0)
        result=compare(self.source,other,[0,0,10,10])
        self.assertFalse(result['whole_bytes']['equal'])
        self.assertTrue(result['decoded_pixels']['equal'])
        self.assertTrue(result['signalROI']['equal'])
        self.assertEqual(result['geometry']['status'],'missing')

    def test_new_input_profile_batch_twice_matches_default(self):
        spec=dict(src=self.source.name,source_sha256=annotation.sha256(self.source),out='default（标注）.png',
                  well=600,lane_x=[400,600,800,1000],marker_indices=[0],
                  groups=[dict(head='兔',param='条件',lanes=[dict(index=1,name='兔2′'),dict(index=2,name='兔4′')])])
        reference=annotation.annotate(spec,self.base,None)
        path=self.base/'spec.json';operations.write_json(path,spec)
        batch=self.base/'batch.json';operations.write_json(batch,dict(schema_version=1,items=[dict(id='new',spec=path.name)]))
        for name in ('run-01','run-02'):
            result=batch_replay.replay(batch,self.base/name)
            output=self.base/name/result['items'][0]['output']['path']
            self.assertTrue(compare(reference,output)['decoded_pixels']['equal'])
            archived=json.loads((output.parent/'annotation-manifest.json').read_text())
            self.assertFalse(Path(archived['render_environment']['fonts']['regular']['path']).is_absolute())

if __name__=='__main__':unittest.main()
