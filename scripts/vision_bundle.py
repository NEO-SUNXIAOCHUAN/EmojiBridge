"""Bundle reviewed OCR/tracking distributions and three pinned OCR models."""
from pathlib import Path
import base64,hashlib,importlib.metadata as metadata,json,shutil

APP=Path(__file__).resolve().parents[1]

def copy_runtime(source,destination):
    source=Path(source).resolve();destination=Path(destination)
    lock=json.loads((APP/'third_party/factory/vision-runtime-lock.json').read_text('utf-8'))
    installed={d.metadata['Name'].lower().replace('_','-'):d for d in metadata.distributions(path=[str(source)])}
    for name,version in lock['packages'].items():
        dist=installed[name]
        if dist.version!=version:raise ValueError('vision_runtime_version_mismatch: '+name)
        for relative in dist.files or ():
            parts=Path(relative).parts
            if '__pycache__' in parts or str(relative).endswith('.pyc'):continue
            # Both wheels own cv2. Use the contrib/headless wheel that provides
            # CSRT; retain the base wheel's metadata for RapidOCR's dependency.
            if name=='opencv-python' and parts[0]=='cv2':continue
            original=Path(dist.locate_file(relative)).resolve()
            if not original.is_relative_to(source):continue
            if not original.is_file():raise ValueError('vision_runtime_file_missing: '+str(relative))
            if relative.hash:
                actual=base64.urlsafe_b64encode(hashlib.new(relative.hash.mode,original.read_bytes()).digest()).decode().rstrip('=')
                if actual!=relative.hash.value:raise ValueError('vision_runtime_file_changed: '+str(relative))
            output=destination/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,output)
    for row in lock['models']:
        relative=Path(row['path']);original=(source/relative).resolve()
        if not original.is_relative_to(source) or hashlib.sha256(original.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('vision_model_changed')
        output=destination/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,output)
    (destination/'ready.json').write_text(json.dumps({'packages':lock['requirements']}),'utf-8')
    shutil.copyfile(APP/'third_party/factory/vision-runtime-lock.json',destination/'runtime-lock.json')
    return lock['packages']
