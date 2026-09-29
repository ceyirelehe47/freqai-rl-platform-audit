from pathlib import Path,PurePosixPath
import zipfile,json,hashlib,stat,collections,xml.etree.ElementTree as ET
B=Path(__file__).resolve().parents[1]; Z=Path('/mnt/data/RouteC_QualifiedInput_TrainingBridge_v1_RETURN_TO_CHATGPT(1).zip');R=B/'received/RouteC_QualifiedInput_TrainingBridge_v1_RETURN'
def sha(b):return hashlib.sha256(b).hexdigest()
with zipfile.ZipFile(Z) as z:
 names=z.namelist(); infos=z.infolist(); pref='RouteC_QualifiedInput_TrainingBridge_v1_RETURN/'
 assert len(names)==len(set(names))==len(set(n.casefold() for n in names))
 assert z.testzip() is None
 assert all(n.startswith(pref) and not n.startswith('/') and '\\' not in n and ':' not in n and '..' not in PurePosixPath(n).parts for n in names)
 assert all(not i.is_dir() and stat.S_IFMT(i.external_attr>>16) in (0,stat.S_IFREG) for i in infos)
 manifest=pref+'return_stage/SHA256SUMS.txt'; entries={}
 for l in z.read(manifest).decode().splitlines():
  h,n=l.split(None,1);n=n.lstrip('*');assert n not in entries;entries[n]=h
 assert set(entries)=={n[len(pref):] for n in names if n!=manifest}
 assert all(sha(z.read(pref+n))==h for n,h in entries.items())
 src=json.loads((R/'return_stage/candidate_source_manifest.json').read_text()); source_checks=[]
 remote_known={'ppo262_qualified_input.py':'14cf48a1152037466d9a141befddfe6f452d73f1','ppo262_eng_profile.py':'2a63efde01ffaaf48ed2ef865190da145f2d0375','ppo262_entry_specs.py':'3459b462fdf778ef7cb767204dedb6d0c4b21186'}
 for r in src['files']:
  p=R/'return_stage/candidate_source'/r['path'];b=p.read_bytes();blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
  assert sha(b)==r['sha256'] and len(b)==r['bytes']
  remote=remote_known.get(p.name)
  if remote:assert blob==remote
  source_checks.append({'path':r['path'],'sha256':sha(b),'git_blob':blob,'package_manifest_match':True,'remote_blob_match':True if remote else 'not independently fetched'})
 archive={'sha256':sha(Z.read_bytes()),'bytes':Z.stat().st_size,'members':len(infos),'uncompressed':sum(i.file_size for i in infos),'manifest_entries':len(entries),'safe':True,'crc_pass':True,'manifest_exact':True,'candidate':src['candidate_commit'],'source':source_checks}
 expected='0e82e8add2916b9b43dbac6271c9295f6e8bf83a71ae6822e88df9df80705794';assert archive['sha256']==expected
 for receipt in ['RouteC_QualifiedInput_TrainingBridge_v1_DELIVERY_RECEIPT(1).md','RouteC_QualifiedInput_TrainingBridge_v1_RETURN_TO_CHATGPT.REVIEWER_FINAL_RECEIPT(1).md','RouteC_QualifiedInput_TrainingBridge_v1_RETURN_TO_CHATGPT.zip.sha256(1).txt']:
  assert expected in (Path('/mnt/data')/receipt).read_text()
 (B/'validation/ARCHIVE.json').write_text(json.dumps(archive,indent=2,ensure_ascii=False))
# Archive regression bodies: v1-v4; v5 intentionally reported absent, not replaced by older tests.
reg=[]
for p in sorted((R/'regression').glob('*/junit.xml')):
 root=ET.fromstring(p.read_bytes());tcs=list(root.iter('testcase')); counts={'tests':len(tcs),'failures':sum(x.find('failure') is not None for x in tcs),'errors':sum(x.find('error') is not None for x in tcs),'skips':sum(x.find('skipped') is not None for x in tcs)}
 item={'file':str(p.relative_to(R)),**counts,'sha256':sha(p.read_bytes())}
 record=p.parent/'regression_evidence_v3_record.json'
 if record.exists():
  j=json.loads(record.read_text());item['record_sha256']=sha(record.read_bytes());item['record_top_keys']=list(j)
  summary=p.parent/'summary.json'
  if summary.exists():
   sm=json.loads(summary.read_text());item['summary_ok']=sm.get('ok');item['record_sha_matches_summary']=sm.get('record_sha256')==sha(record.read_bytes())
  item['candidate']=j.get('commit_a_sha');
  coll=p.parent/'collection.stdout.txt'
  if coll.exists():
   ids=[l.strip() for l in coll.read_text().splitlines() if l.strip().startswith('tests/') and '::' in l]
   def asid(t):
    cls=t.get('classname','').split('.');pos=next((i for i,c in enumerate(cls) if c.startswith('test_')),len(cls)-1);return '/'.join(cls[:pos+1])+'.py::'+('::'.join(cls[pos+1:])+'::' if len(cls)>pos+1 else '')+t.get('name','')
   junit_ids=[asid(t) for t in tcs];item['collection_count']=len(ids);item['collection_multiset_match']=collections.Counter(ids)==collections.Counter(junit_ids)
   assert item['collection_multiset_match'],(p,ids[:1],junit_ids[:1])
 reg.append(item)
missing=[n for n in ['full_regression_v5','regression_262_v5'] if not (R/'regression'/n).is_dir()]
(B/'validation/REGRESSION_ARCHIVES.json').write_text(json.dumps({'archived':reg,'latest_candidate_v5_directories_missing_from_return':missing,'v5_remote_summary_read_separately':True,'not_a_v5_raw_reverification':True},indent=2))
# Same historical main model bytes as preceding upload. No deserialization or re-training.
main=R/'eng_training_bridge_v1/eng_ppo_smoke_256.zip'
old=zipfile.ZipFile('/mnt/data/RouteC_QualifiedInput_TrainingBridge_v1_RETURN_TO_CHATGPT.zip');oldname=next(n for n in old.namelist() if n.endswith('/eng_training_bridge_v1/eng_ppo_smoke_256.zip'))
model={'sha256':sha(main.read_bytes()),'bytes':main.stat().st_size,'identical_to_prior_upload':main.read_bytes()==old.read(oldname),'load_or_train_executed':False};assert model['identical_to_prior_upload']
ledger=[json.loads(l) for l in (R/'eng_training_bridge_v1/ppo262e_quota_ledger.jsonl').read_text().splitlines() if l.strip()]
model['ledger']={'events':len(ledger),'bank_replays':sum(r['event']=='bank_generation_replay' for r in ledger),'successful_episodes':sum(r.get('count',0) for r in ledger if r['event']=='bank_episode_success'),'smoke_runs':sum(r['event']=='ppo_smoke' for r in ledger),'smoke_steps':sum(r.get('steps',0) for r in ledger if r['event']=='ppo_smoke')}
(B/'validation/MODEL_AND_LEDGER.json').write_text(json.dumps(model,indent=2))
print(json.dumps({'archive':{k:v for k,v in archive.items() if k!='source'},'source_manifest_matches':len(source_checks),'independent_remote_matches':len(remote_known),'regressions':reg,'missing_from_return':missing,'model':model},ensure_ascii=False,indent=2))
