"""White media and wide sidebar regressions; no client input."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PIL import Image,ImageDraw
from emoji_bridge.message_media import staged_matches,WeChatFrameMatcher
from emoji_bridge.wechat_visual_bridge import load_cv2
from emoji_bridge.wechat_visual import search_box,helper_icon

class WhitePreviewTests(unittest.TestCase):
    def ref(self):
        im=Image.new('RGBA',(240,200),'white');d=ImageDraw.Draw(im)
        d.ellipse((75,40,155,120),fill='orange',outline='black',width=5)
        d.rectangle((40,138,195,165),fill='red');d.text((80,142),'S175',fill='white')
        return im

    def test_white_border_blends_into_composer_at_three_scales(self):
        ref=self.ref()
        for scale in (1,1.25,1.5):
            for bg in ('white','#fafafa','#1f1f1f'):
                with self.subTest(scale=scale,bg=bg):
                    im=Image.new('RGB',(round(400*scale),round(160*scale)),bg)
                    size=(round(120*scale),round(100*scale));im.paste(ref.convert('RGB').resize(size,Image.Resampling.LANCZOS),(7,9))
                    hits=staged_matches(im,[ref],WeChatFrameMatcher([ref]),scale)
                    self.assertEqual(len(hits),1)
                    self.assertLess(abs(hits[0].x-7),3);self.assertLess(abs(hits[0].y-9),3)
                    self.assertLess(abs(hits[0].width-size[0]),3)

    def test_blank_and_different_white_art_not_accepted(self):
        ref=self.ref();im=Image.new('RGB',(400,160),'white')
        self.assertFalse(staged_matches(im,[ref],WeChatFrameMatcher([ref])))
        wrong=ref.copy();ImageDraw.Draw(wrong).ellipse((75,40,155,120),fill='blue')
        im.paste(wrong.convert('RGB').resize((120,100)),(7,9))
        self.assertFalse(staged_matches(im,[ref],WeChatFrameMatcher([ref])))

    def test_two_identical_previews_remain_ambiguous(self):
        ref=self.ref();im=Image.new('RGB',(400,160),'white')
        for x in (7,150):im.paste(ref.convert('RGB').resize((120,100),Image.Resampling.LANCZOS),(x,9))
        self.assertEqual(len(staged_matches(im,[ref],WeChatFrameMatcher([ref]))),2)

    def test_wide_search_field_and_light_dark(self):
        for scale in (1,1.25,1.5):
            for bg,field in (('#ececec','#fafafa'),('#303030','#404040')):
                im=Image.new('RGB',(1000,800),bg)
                ImageDraw.Draw(im).rounded_rectangle((80,43,460,70),6,fill=field)
                im=im.resize((round(1000*scale),round(800*scale)))
                rect=search_box(im,510*scale,scale,load_cv2())
                self.assertLess(abs(rect[0]-80*scale),3)
                self.assertGreater(rect[2]-rect[0],350*scale)

    def test_helper_icon_nested_in_light_background(self):
        for bg in ('#fafafa','#222222','#00ab68'):
            im=Image.new('RGB',(250,100),bg);d=ImageDraw.Draw(im)
            d.ellipse((30,24,63,57),fill='#00bc62')
            icon=Image.new('RGB',(32,26),'#00bc62');p=ImageDraw.Draw(icon)
            p.polygon([(0,0),(10,0),(13,3),(31,3),(31,25),(0,25)],fill='white')
            p.polygon([(9,12),(18,12),(18,9),(24,14),(18,19),(18,16),(9,16)],fill='#00bc62')
            im.paste(icon.resize((20,16)),(37,33))
            self.assertEqual(helper_icon(im,(80,30,164,48),1,load_cv2()),(37,33,57,49))

    def test_avatar_contour_inset_still_proposes_the_intact_media(self):
        from emoji_bridge.message_media import viewport_media_rects
        from types import SimpleNamespace
        image=Image.new('RGB',(940,663),'white')
        matcher=SimpleNamespace(native_size=(140,320))
        proposals=list(viewport_media_rects(image,[(890,335,925,371)],matcher,1))
        self.assertIn((817,335,875,467),proposals)
        self.assertNotIn((810,335,868,467),proposals)

    def test_transparency_recheck_accepts_observed_white_surface(self):
        from emoji_bridge.recognition import rgb
        ref=Image.new('RGBA',(240,200));ImageDraw.Draw(ref).ellipse((75,40,155,120),fill='orange')
        matcher=WeChatFrameMatcher([ref]);preview=rgb(ref,(255,255,255)).resize((120,100),Image.Resampling.LANCZOS)
        self.assertLess(matcher(preview)[1],.04)

if __name__=='__main__':unittest.main()
