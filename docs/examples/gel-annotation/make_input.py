"""Deterministic synthetic wells; NOT an experiment or a band interpretation."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FONT = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
BOLD = FONT.with_name('NotoSansCJK-Bold.ttc')


def make_input():
    image = Image.new('RGB', (1200, 900), (17, 20, 24))
    draw = ImageDraw.Draw(image)
    xs = [240, 480, 720, 960]
    for x in xs:
        draw.rounded_rectangle((x - 45, 440, x + 45, 460), radius=4, fill=(80, 84, 88))
    # Decorative synthetic bands, with no size scale or biological interpretation.
    bands = Image.new('RGB', image.size, (0, 0, 0))
    d = ImageDraw.Draw(bands)
    for x, ys in zip(xs, [[510, 555, 600, 650, 700], [610], [585, 655], []]):
        for y in ys:
            d.rounded_rectangle((x - 44, y - 4, x + 44, y + 4), radius=4, fill=(145, 145, 145))
    from PIL import ImageChops
    image = ImageChops.add(image, bands.filter(ImageFilter.GaussianBlur(3)))
    image.save(HERE / 'synthetic-input.png', optimize=True)
    spec = json.loads((ROOT / 'gel-annotation/assets/recognized_minimal.spec.template.json').read_text())
    spec.update(src='synthetic-input.png', out='synthetic（标注）.png',
                source_sha256=hashlib.sha256((HERE / 'synthetic-input.png').read_bytes()).hexdigest(),
                date='合成示例', primer_name='仅展示孔位标注', portable_resources=False,
                font_paths={'regular': str(FONT), 'bold': str(BOLD)},
                font_sha256={role: hashlib.sha256(path.read_bytes()).hexdigest()
                             for role, path in [('regular', FONT), ('bold', BOLD)]},
                rows=[dict(well=450, lane_x=xs, lane_y=[450] * 4, marker_indices=[0],
                           review_box=[140, 420, 1060, 740],
                           groups=[dict(head='', lanes=[dict(index=i, sample_id=f'synthetic-{i}',
                                                            display_label=label)])
                                   for i, label in [(1, '样品1'), (2, '样品2'), (3, 'NTC')]])])
    (HERE / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')


def comparison():
    canvas = Image.new('RGB', (1400, 660), 'white')
    draw = ImageDraw.Draw(canvas)
    title = ImageFont.truetype(str(BOLD), 30)
    text = ImageFont.truetype(str(FONT), 22)
    draw.text((28, 14), '凝胶孔位标注演示 · 合成图像，非真实实验', font=title, fill='#172033')
    draw.text((28, 60), '仅演示 Marker / 样品1 / 样品2 / NTC 的标注；条带不代表任何实验结果。', font=text, fill='#333333')
    for x, filename, label in [(28, 'synthetic-input.png', 'Pillow 合成输入'), (714, 'synthetic（标注）.png', 'annotate_gel.py 实际输出')]:
        draw.text((x, 103), label, font=text, fill='#172033')
        with Image.open(HERE / filename) as im:
            canvas.paste(im.resize((658, 494), Image.Resampling.LANCZOS), (x, 143))
    canvas.save(HERE / 'comparison.png', optimize=True)


if __name__ == '__main__':
    import sys
    comparison() if '--comparison' in sys.argv else make_input()
