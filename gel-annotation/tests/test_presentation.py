"""Opt-in recognized family preset; fixtures test mechanics, never new experiments."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import annotate_gel as a
from compare_replay import compare


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(tempfile.mkdtemp(prefix='gel-presentation-',dir='/tmp/opencode'))
        self.source=self.base/'fixture.png';Image.new('RGB',(1600,1600),(60,60,60)).save(self.source)
        self.spec=dict(src=str(self.source),source_sha256=a.sha256(self.source),out=str(self.base/'fixture（标注）.png'),
                       date='2026-10-03',primer_name='Fixture-F/R',well=600,lane_x=[400,600,800,1000],lane_y=[600]*4,
                       marker_indices=[0],groups=[dict(head='样本',lanes=[dict(index=1,sample_id='real-one',display_label='编号1'),
                                                                        dict(index=2,sample_id='real-two',display_label='编号2')]),
                                                 dict(control='NTC',head='隐藏NTC大字',param='隐藏浓度',lanes=[dict(index=3,display_label='NTC')])])

    def test_preset_executes_footer_policy_and_changes_real_pixels(self):
        old=dict(self.spec,annotation_profile='report_minimal',out=str(self.base/'old（标注）.png'))
        oldout=a.annotate(old,self.base,None)
        preset=dict(self.spec,presentation_profile='recognized_minimal_v1')
        out=a.annotate(preset,self.base,None)
        archive=json.loads(out.with_suffix('.annotation-manifest.json').read_text())
        footer=archive['footers'][0]
        self.assertEqual((footer['text'],footer['language'],footer['separator'],footer['layout_engine'],footer['face_index']),
                         ('2026-10-03 · Fixture-F/R','en',' · ','RAQM',0))
        self.assertFalse(compare(oldout,out)['decoded_pixels']['equal'])
        original=json.loads(oldout.with_suffix('.annotation-manifest.json').read_text())['footers'][0]
        self.assertEqual((original['text'],original['language']),('2026-10-03 Fixture-F/R',None))
        final=archive['finalspec'];final['out']=str(self.base/'replay（标注）.png')
        replay=a.annotate(final,out.parent,None)
        self.assertTrue(compare(out,replay)['whole_bytes']['equal'])

    def test_row_facts_override_top_level_and_dynamic_geometry_identity(self):
        row={k:copy.deepcopy(self.spec[k]) for k in ('well','lane_x','lane_y','marker_indices','groups')}
        row.update(date='2026-10-12',primer_name='Recorded-Other',lane_y=[600,605,610,600])
        row['lane_x'][1]=620;row['groups'][0]['lanes'][0].update(sample_id='different-real-id',display_label='不同编号')
        spec={k:v for k,v in self.spec.items() if k not in row}
        spec.update(date='top-date',primer_name='top-primer',rows=[row],presentation_profile='recognized_minimal_v1')
        out=a.annotate(spec,self.base,None);archive=json.loads(out.with_suffix('.annotation-manifest.json').read_text())
        self.assertEqual(archive['footers'][0]['text'],'2026-10-12 · Recorded-Other')
        self.assertEqual(archive['finalspec']['rows'][0]['lane_x'][1],620)
        self.assertEqual(archive['sample_mapping'][1]['labels'][0]['sample_id'],'different-real-id')
        with Image.open(out) as image:self.assertEqual(image.getpixel((620,605)),a.COLORS['purple'])

    def test_unknown_conflict_engine_control_separator_and_missing_font_fail_before_save(self):
        preset=dict(self.spec,presentation_profile='recognized_minimal_v1')
        cases=[dict(preset,presentation_profile='unknown'),dict(preset,primer_language='zh'),
               dict(preset,primer_separator='\n'),dict(preset,font_layout_engine=dict(regular='BASIC')),
               dict(preset,font_paths=dict(regular=str(self.base/'missing.ttc'))),
               dict(preset,source_sha256=None),dict(self.spec,primer_separator='a\u200bb')]
        for spec in cases:
            with self.subTest(spec=spec),patch.object(Image.Image,'save') as save,self.assertRaises(SystemExit):
                a.annotate(spec,self.base,None)
            save.assert_not_called()
        self.assertFalse(Path(preset['out']).exists())

    def test_existing_minimal_control_rules_and_default_pixels_remain(self):
        spec=dict(self.spec,presentation_profile='recognized_minimal_v1')
        spec['groups']=copy.deepcopy(self.spec['groups'])
        spec['groups'][-1]['lanes'][0]['display_label']=''
        with self.assertRaises(SystemExit):a.annotate(spec,self.base,None)
        legacy=dict(self.spec,groups=self.spec['groups'][:1])
        one=a.annotate(legacy,self.base,None)
        two=a.annotate(dict(legacy,out=str(self.base/'explicit-none（标注）.png'),presentation_profile=None),self.base,None)
        self.assertTrue(compare(one,two)['whole_bytes']['equal'])


if __name__=='__main__':unittest.main()
