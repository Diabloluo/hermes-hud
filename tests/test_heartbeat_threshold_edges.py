"""Additional F4 finite-number/language boundaries. Synthetic VM only."""
import json
import os
from pathlib import Path
import subprocess
import pytest
import test_heartbeat_threshold_contract as contract

# Optional read-only old JS control; no alternate backend or live API.
SOURCE=Path(os.environ.get('F4_RED_JS',str(contract.SOURCE)))

@pytest.mark.parametrize('kind',['NaN','Infinity','-Infinity','absentHealth','absentThresholds','absentField','array','object'])
def test_unknown_metadata_boundaries(kind):
    snap=contract.snapshot(contract.platform());snap['_health']={'thresholds':{'heartbeat_critical_s':120}}
    script=contract.SCRIPT.replace('freeze(input);', '''
const kind=input.kind;
if(kind==='absentHealth')delete input.snap._health;
else if(kind==='absentThresholds')delete input.snap._health.thresholds;
else if(kind==='absentField')delete input.snap._health.thresholds.heartbeat_critical_s;
else input.snap._health.thresholds.heartbeat_critical_s=({NaN:NaN,Infinity:Infinity,'-Infinity':-Infinity,array:[],object:{}})[kind];
freeze(input);''')
    r=subprocess.run(['node','-e',script,str(SOURCE),json.dumps({'snap':snap,'kind':kind})],check=True,capture_output=True,text=True,timeout=5)
    out=json.loads(r.stdout)
    assert out['view']['stale'] is False
    assert out['view']['dot']=='hud-dot-warn'
    assert 'Heartbeat threshold unknown' in out['text']

@pytest.mark.parametrize('threshold,age,stale',[(0.5,0.49,False),(0.5,0.5,False),(0.5,0.51,True),(30,29.99,False),(120,119.99,False)])
def test_fractional_and_below_threshold(monkeypatch,threshold,age,stale):
    monkeypatch.setattr(contract,'SOURCE',SOURCE)
    p=contract.platform();p['heartbeat_age']=age;snap=contract.snapshot(p)
    snap['_health']={'thresholds':{'heartbeat_critical_s':threshold},'checks':[]}
    out=contract.render(snap)
    assert out['view']['stale'] is stale
    assert out['view']['dot']==('hud-dot-warn' if stale else 'hud-dot-ok')

@pytest.mark.parametrize('locale,text',[('zh','心跳阈值未知'),('en','Heartbeat threshold unknown'),('fr','Seuil du rythme de vie inconnu'),('ar','عتبة نبض الاتصال غير معروفة')])
def test_four_dictionary_entries(monkeypatch,locale,text):
    monkeypatch.setattr(contract,'SOURCE',SOURCE)
    out=contract.render(contract.snapshot(contract.platform()),locale=locale)
    assert text in out['text']
