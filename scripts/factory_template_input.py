"""Standalone input defaults for templates originally designed for chat bots."""
NAME_TEMPLATES={'alipay','always_like','ask','google_captcha','make_friend','wechat_pay','why_have_hands'}

def catalog_defaults(row):
    row=dict(row);key=row['key'].removeprefix('meme:')
    if key in NAME_TEMPLATES:
        row['min_texts']=max(1,row['min_texts']);row['default_texts']=['名字']
    elif key=='dianzhongdian':
        row['min_texts']=2;row['default_texts']=['救命啊','第二行文字']
    return row

def prepare_texts(key,texts,image_count):
    key=key.removeprefix('meme:');texts=list(texts)
    if key in NAME_TEMPLATES:
        required=max(1,image_count) if key=='always_like' else 1
        if not texts:texts=['名字']
        while len(texts)<required:texts.append('名字 '+str(len(texts)+1))
    if key=='dianzhongdian':
        if not texts:texts=['救命啊','第二行文字']
        if len(texts)<2:raise ValueError('此模板需要两行文字，请填写第二行（可自行填写译文）；不会联网翻译')
    return texts
