"""Targeted Oracle M1-M4 regressions; synthetic fixtures are mechanism tests only."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import annotate_gel as a
import batch_replay as batch
import replay_operations as ops
from compare_replay import compare


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='gel-v3-safety-', dir='/tmp/opencode'))
        self.source = self.base / 'source.png'
        Image.new('RGB', (1600, 1600), (60, 60, 60)).save(self.source)
        self.spec = dict(src=str(self.source), source_sha256=a.sha256(self.source), out='result（标注）.png',
                         well=600, lane_x=[400, 600], marker_indices=[0],
                         groups=[dict(lanes=[dict(index=1, name='fixture')])])
        self.recipe = dict(schema_version=1, start='old', inputs={'old':dict(path='source.png',sha256=a.sha256(self.source))},
                           font=dict(path=str(a.FONT), sha256=a.sha256(a.FONT)), operations=[])

    def operation_batch(self, identities=('first', 'last'), recipe=None):
        p = self.base / 'recipe.json'; ops.write_json(p, recipe or self.recipe)
        b = self.base / 'batch.json'
        ops.write_json(b, dict(schema_version=1, items=[dict(id=i,spec=p.name,sha256=a.sha256(p)) for i in identities]))
        return b, p

    def test_last_reserved_directory_rejected_before_writes_both_executors(self):
        b, _ = self.operation_batch(('first','replay-manifest.json'))
        with self.assertRaises(SystemExit): ops.replay(b,self.base/'ops-out')
        self.assertFalse((self.base/'ops-out').exists())
        p = self.base/'annotation.json'; ops.write_json(p,self.spec)
        b2 = self.base/'annotation-batch.json'; ops.write_json(b2,dict(schema_version=1,items=[dict(id=i,spec=p.name) for i in ('first','replay-manifest.json')]))
        with self.assertRaises(SystemExit): batch.replay(b2,self.base/'batch-out')
        self.assertFalse((self.base/'batch-out').exists())

    def test_batch_and_recipe_symlinks_rejected_without_writes(self):
        b,p = self.operation_batch()
        link = self.base/'link.json'; link.symlink_to(b)
        with self.assertRaises(SystemExit): ops.replay(link,self.base/'out')
        other = self.base/'other.json'; other.symlink_to(p)
        payload=json.loads(b.read_text()); payload['items'][-1]['spec']=other.name
        b.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit): ops.replay(b,self.base/'out')
        self.assertFalse((self.base/'out').exists())

    def test_relative_public_api_out_is_cwd_relative_not_spec_base(self):
        specs=self.base/'specs'; specs.mkdir()
        p=specs/'spec.json'; ops.write_json(p,self.spec)
        b=specs/'batch.json'; ops.write_json(b,dict(schema_version=1,items=[dict(id='fixture',spec=p.name)]))
        with patch('os.getcwd',return_value=str(self.base)):
            result=batch.replay(b,Path('api-output'))
        output=self.base/'api-output'/result['items'][0]['output']['path']
        self.assertTrue(output.is_file()); self.assertFalse((specs/'api-output').exists())
        archived=json.loads((output.parent/'finalspec.json').read_text())
        self.assertEqual((output.parent/archived['out']).resolve(),output)

    def test_operation_bounds_and_nonfinite_are_rejected(self):
        cases=[dict(op='paste',source='old',crop=[-1,0,5,5],xy=[0,0]),
               dict(op='paste',source='old',crop=[0,0,5,5],xy=[1599,0]),
               dict(op='rectangle',box=[0,0,1601,5],fill=[0,0,0]),
               dict(op='text',xy=[-2,-2],text='overflow',size=31,anchor='lt',fill=[255,0,0]),
               dict(op='text',xy=[float('nan'),10],text='invalid',size=31,anchor='lt',fill=[255,0,0])]
        for op in cases:
            with self.subTest(op=op), self.assertRaises(SystemExit): ops.render(dict(self.recipe,operations=[op]),self.base)

    def test_expand_and_signal_roi_checks_use_evolving_canvas(self):
        for n in (0,-1,True,1.2):
            with self.assertRaises(SystemExit):ops.render(dict(self.recipe,operations=[dict(op='expand_bottom',pixels=n,fill=[0,0,0])]),self.base)
        bad=dict(self.recipe,signal_roi=[0,0,10,10],operations=[dict(op='rectangle',box=[0,0,5,5],fill=[0,0,0])])
        with self.assertRaises(SystemExit):ops.render(bad,self.base)
        good=dict(self.recipe,signal_preservation=dict(source='old',source_roi=[0,0,10,10],offset=[0,10]),
                  operations=[dict(op='expand_bottom',pixels=10,fill=[0,0,0]),dict(op='paste',source='old',crop=[0,0,10,10],xy=[0,10])])
        image,final=ops.render(good,self.base,True)
        self.assertEqual(image.height,1610);self.assertTrue(final['signal_preservation']['equal'])

    def test_one_past_rectangle_is_explicit_normalization(self):
        _,final=ops.render(dict(self.recipe,operations=[dict(op='rectangle',box=[0,0,1600,1600],fill=[0,0,0])]),self.base,True)
        self.assertEqual(final['operations'][0]['box'],[0,0,1599,1599])
        self.assertEqual(final['operations'][0]['original_box'],[0,0,1600,1600])

    def test_direct_source_annotation_profile_font_symlinks_fail(self):
        link=self.base/'source-link.png';link.symlink_to(self.source)
        profile=self.base/'profile-link.json';profile.symlink_to(a.PROFILE_PATH)
        font=self.base/'font-link.ttc';font.symlink_to(a.FONT)
        cases=[dict(self.spec,src=str(link)),dict(self.spec,source_annotations=[dict(path=str(link))]),
               dict(self.spec,style_profile=str(profile)),dict(self.spec,font_paths=dict(regular=str(font)))]
        for spec in cases:
            with self.assertRaises(SystemExit):a.annotate(spec,self.base,None)
        self.assertFalse((self.base/self.spec['out']).exists())

    def test_explicit_language_finalspec_and_font_hash_fail_closed(self):
        text=dict(op='text',xy=[800,100],text='2026-10-03 · HUM_1',size=38,anchor='mt',fill=[255,70,70],language='en')
        _,final=ops.render(dict(self.recipe,operations=[text]),self.base,True)
        self.assertEqual(final['operations'][0]['language'],'en')
        self.assertIn(final['operations'][0]['layout_engine'],('RAQM','BASIC'))
        bad=copy.deepcopy(self.recipe);bad['font']['sha256']='0'*64
        with self.assertRaises(SystemExit):ops.render(bad,self.base)

    def test_palette_comparison_not_misreported_as_visual_equality(self):
        p=self.base/'palette.png';Image.new('P',(10,10)).save(p)
        with self.assertRaises(SystemExit):compare(p,p)

    def test_asset_drives_font_sizes_and_saved_finalspec(self):
        p=copy.deepcopy(a.DEFAULT_STYLE);p['font_sizes']['lane']=24
        reference=a.annotate(self.spec,self.base,None)
        changed=a.annotate(dict(self.spec,out='changed（标注）.png',style_profile=p),self.base,None)
        self.assertFalse(compare(reference,changed)['decoded_pixels']['equal'])
        archive=json.loads(changed.with_suffix('.annotation-manifest.json').read_text())
        final=archive['finalspec'];self.assertEqual(final['style_profile']['font_sizes']['lane'],24)
        final['out']='replayed（标注）.png'
        replay=a.annotate(final,changed.parent,None)
        self.assertTrue(compare(changed,replay)['whole_bytes']['equal'])


if __name__=='__main__':unittest.main()
