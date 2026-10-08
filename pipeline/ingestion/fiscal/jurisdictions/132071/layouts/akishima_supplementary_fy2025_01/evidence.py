"""Finite local evidence restoration; exact identities, no source path fallback."""
import json,hashlib
from pathlib import Path
PKG=Path(__file__).resolve().parent

def verify_local_evidence():
 manifest=json.loads((PKG/'evidence-manifest.json').read_text())
 for name,ref in manifest.items():
  if name=='origin':continue
  body=(PKG/name).read_bytes()
  if hashlib.sha256(body).hexdigest()!=ref['sha256'] or len(body)!=ref['bytes']:raise ValueError('Supplementary evidence differs: '+name)
 return manifest

def evidence_objects():
 ref=verify_local_evidence()['origin'];return [dict(key='inputs/origin/sha256/'+ref['sha256'],**ref)]

def restore_evidence(objects_dir,remote=False):
 # Generic restoration already stores the locked origin. This hook verifies its
 # evidence binding; no remote operation is performed by this finite provider.
 for ref in evidence_objects():
  body=(Path(objects_dir)/ref['key']).read_bytes()
  if hashlib.sha256(body).hexdigest()!=ref['sha256'] or len(body)!=ref['bytes']:raise ValueError('Supplementary origin evidence differs')
 return {'objects_verified':len(evidence_objects()),'packaged_evidence_verified':True}
