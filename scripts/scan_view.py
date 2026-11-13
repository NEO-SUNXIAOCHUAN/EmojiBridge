"""Transient hints for authenticated WeChat catalog refreshes, never receipts."""
from emoji_bridge import catalog


def observed_ids(side):
    # Include collapsed observations so preparation cannot invent a new item.
    return {i['id'] for i in side['items'] if not i.get('source_receipt_only')}


def snapshot_key(side):
    return side.get('source_report'),side.get('snapshot_at')


class RecentWechatScan:
    def __init__(self,side):
        self.previous=observed_ids(side);self.snapshot=snapshot_key(side)
        self.recent=set();self.checked=False;self.incomplete=False;self.stale=False

    def begin(self,side):
        self.previous=observed_ids(side);self.snapshot=snapshot_key(side)

    def observe(self,side,*,finished=False,failed=False):
        current=observed_ids(side);snapshot=snapshot_key(side)
        changed=snapshot!=self.snapshot
        if not changed and not finished:return False
        if failed and not changed:
            self.incomplete=True;self.stale=True
            return False
        self.recent=current-self.previous;self.previous=current;self.snapshot=snapshot
        self.checked=True;self.incomplete=failed;self.stale=False
        return True

    def items(self,side):
        representatives={i.get('duplicate_of') or i['id'] for i in side['items']
                         if i['id'] in self.recent and not i.get('source_receipt_only')}
        return [i for i in catalog.display_items(side) if i['id'] in representatives]

    def hint(self,side):
        if self.stale:
            return '本次刷新未完成；保留上次定位结果。请查看停止原因，尚不能判断本次有无新条目。'
        prefix='本次刷新未完成；按已保存索引显示。' if self.incomplete else ''
        if not self.checked:
            return prefix+'在微信手动收藏后，更新列表并定位新出现项，再勾选加入素材库。'
        count=len(self.recent & observed_ids(side));items=self.items(side)
        if not count:return prefix+'本次未发现新条目；仅比较本地索引，不代表云端全集。'
        ready=sum(i.get('original_state')=='ready' and i.get('original_available') is True
                  and bool(i.get('asset')) for i in items)
        merged=f'（合并显示 {len(items)} 项）' if len(items)!=count else ''
        return (prefix+f'本次新出现 {count} 项{merged}：原件就绪 {ready}，待取得/核验 {len(items)-ready}。'
                +'定位后勾选加入素材库。')


def retained_scroll_top(previous,current,top,row_height,columns=3):
    """Keep the first surviving card in the old top row at the same offset."""
    if previous==current:return top
    start=max(0,int(top//row_height))*columns
    positions={ident:n for n,ident in enumerate(current)}
    for ident in previous[start:start+columns]:
        if ident in positions:return positions[ident]//columns*row_height+top%row_height
    return top
