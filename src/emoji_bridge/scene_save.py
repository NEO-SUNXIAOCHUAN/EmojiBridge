"""Save one captured editor revision, using the existing output and material services."""
from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import threading
import uuid


@dataclass
class SceneSave:
    document: object
    name: str
    output_size: tuple
    extra: dict
    work_id: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cancel: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def capture(cls, document, name, output_size, extra, work_id):
        # EditDocument replaces immutable state records; pixel sources are never
        # modified in place. Histories are not shared with this worker snapshot.
        snapshot=copy(document)
        snapshot._undo=[];snapshot._redo=[]
        return cls(snapshot,name,tuple(output_size),deepcopy(extra),work_id)

    @property
    def revision(self):return self.document.revision

    def run(self,store,progress):
        from .animated_edit import check_cancel
        from .editing import save_scene,load_scene
        from .work_output import prepare_output
        from PIL import Image
        def report(stage,n=None,total=None):
            check_cancel(self.cancel);progress(stage,n,total)
        report('准备成品')
        file,_,size=prepare_output(self.document,store.root,output_size=self.output_size,cancel=self.cancel,
                                  progress=lambda n,total,stage:report(stage,n,total))
        report('保存草稿')
        folder=store.root/'drafts'/self.job_id
        metadata={**self.extra,'work_snapshot':True,'work_id':self.work_id,
                  'document_revision':self.revision,'save_job_id':self.job_id}
        save_scene(self.document,folder,self.name,extra=metadata,cancel=self.cancel)
        # Verify the published scene and all owned references before adding a
        # library record; failed imports leave a recoverable independent draft.
        reopened,_=load_scene(folder,cancel=self.cancel)
        if [l['id'] for l in reopened.layers]!=[l['id'] for l in self.document.layers]:
            raise ValueError('草稿图层核对未通过；原件保留')
        report('写入素材库')
        recipe={'type':'editor-scene','recipe_version':1,'draft_id':self.job_id,'operations':self.document.operations,
                **self.extra,'output_size':list(size),'work_id':self.work_id,
                'document_revision':self.revision,'save_job_id':self.job_id}
        if self.document.animation:
            item,_=store.save_animated_work(file,name=self.name,source_ids=self.document.source_ids,
                                           recipe=recipe,cancel=self.cancel)
        else:
            with Image.open(file) as image:
                item,_=store.save_work(image,name=self.name,source_ids=self.document.source_ids,
                                      recipe=recipe,cancel=self.cancel)
        # The store commits its managed original and SQLite transaction before
        # returning. A late cancel must not turn this committed result into failure.
        store.original(item['id'])
        return item
