"""Offline models only; no real psutil inspection, process, pipe, DB or network."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import psutil  # Dependency preload only, never actual Process/OS inspection.
import test_exit_status as prior
import identity_diagnostics as d
full=prior.full;regression=prior.regression;l=prior.l;a=prior.a;n=full.n
F,R=prior.F,prior.R
INPUTS=dict(prior.INPUTS)
for name in ('identity_diagnostics.py','test_diagnostics.py','DIAGNOSTICS_DELTA.md','PROTOCOL.md'):
    INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()


def actual(obj,**change):
    row={'pid':1234,'birth':100.0,'cwd':str(obj.home),
         'argv':[obj.binding['argv0']]+obj.argv[1:],'exe':obj.binding['exe']}
    row.update(change);return row


class InitialTests(unittest.TestCase):
    def test_matching_control_no_diagnostic(self):
        obj=full.native();proc=regression.Process();obj.inspect=lambda _:actual(obj)
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):
            self.assertEqual(obj.expected(proc),actual(obj))
        self.assertIsNone(obj.identity_diagnostic())
    def test_birth_outside_window(self):
        obj=full.native();obj.inspect=lambda _:actual(obj,birth=90.0)
        with patch.object(n.time,'time',lambda:100.5):
            self.assertRaises(l.BoundaryRefused,obj.expected,regression.Process())
        row=obj.identity_diagnostic();self.assertEqual(row['site'],'initial_birth')
        self.assertIs(row['birth_window'],False);self.assertEqual(set(row),d.FIELDS)
    def test_invalid_actual_schema_exports_no_values(self):
        obj=full.native();obj.inspect=lambda _:{'raw':'/Users/SECRET'}
        self.assertRaises(l.BoundaryRefused,obj.expected,regression.Process())
        row=obj.identity_diagnostic();self.assertEqual(row['site'],'initial_schema')
        self.assertTrue(all(v is None for v in row['checks'].values()))
        self.assertNotIn('SECRET',json.dumps(row))


for code in (0,2,-9):
    def exited(self,code=code):
        obj=full.native();proc=regression.Process();proc.code=code
        obj.inspect=lambda _:self.fail('must not inspect exited process')
        self.assertRaises(l.BoundaryRefused,obj.expected,proc)
        row=obj.identity_diagnostic();self.assertEqual(row['site'],'initial_poll')
        self.assertEqual(row['exit_code'],code);self.assertIsNone(obj.saved)
    setattr(InitialTests,'test_poll_exit_'+str(code).replace('-','minus'),exited)
for field,value in (('pid',999),('cwd','/SECRET'),('argv',['/SECRET']),('exe','/SECRET')):
    def mismatch(self,field=field,value=value):
        obj=full.native();obj.inspect=lambda _:actual(obj,**{field:value})
        with patch.object(n.time,'time',lambda:100.5):
            self.assertRaises(l.BoundaryRefused,obj.expected,regression.Process())
        row=obj.identity_diagnostic();self.assertEqual(row['site'],'initial_match')
        self.assertIs(row['checks'][field],False)
        self.assertTrue(all(v is True for k,v in row['checks'].items() if k!=field))
        self.assertNotIn('SECRET',json.dumps(row));self.assertNotIn('/MODEL',json.dumps(row))
    setattr(InitialTests,'test_mismatch_'+field,mismatch)


EXCEPTIONS=(('zombie_process',lambda:psutil.ZombieProcess(1234)),
 ('no_such_process',lambda:psutil.NoSuchProcess(1234)),
 ('access_denied',lambda:psutil.AccessDenied(1234)),
 ('inspection_other',lambda:RuntimeError('/Users/SECRET')))
class InspectionTests(unittest.TestCase):pass
for site in ('initial','loop'):
    for name,factory in EXCEPTIONS:
        def inspect_error(self,site=site,name=name,factory=factory):
            obj=full.native();proc=regression.Process()
            def fail(_):raise factory()
            obj.inspect=fail
            with patch.object(n.time,'monotonic',lambda:obj.begin+1):
                self.assertRaises(Exception,obj.expected if site=='initial' else obj.check,
                                  *([proc] if site=='initial' else [proc,actual(obj)]))
            row=obj.identity_diagnostic();self.assertEqual(row['site'],site+'_inspect')
            self.assertEqual(row['inspection_error'],name)
            self.assertTrue(all(v is None for v in row['checks'].values()))
            self.assertNotIn('SECRET',json.dumps(row))
            obj._identity_note('loop_poll',code=2)
            self.assertEqual(obj.identity_diagnostic(),row) # sticky first failure
            row['checks']['pid']=False;self.assertIsNone(obj.identity_diagnostic()['checks']['pid'])
        setattr(InspectionTests,'test_'+site+'_'+name,inspect_error)


class LoopTests(unittest.TestCase):pass
for field,value in (('pid',999),('birth',101.0),('cwd','/SECRET'),('argv',['/SECRET']),('exe','/SECRET')):
    def mismatch(self,field=field,value=value):
        obj=full.native();obj.inspect=lambda _:actual(obj,**{field:value})
        with patch.object(n.time,'monotonic',lambda:obj.begin+1):
            self.assertRaises(l.BoundaryRefused,obj.check,regression.Process(),actual(obj))
        row=obj.identity_diagnostic();self.assertEqual(row['site'],'loop_match')
        self.assertIs(row['checks'][field],False);self.assertNotIn('SECRET',json.dumps(row))
    setattr(LoopTests,'test_mismatch_'+field,mismatch)
for code in (0,2,-9):
    def exited(self,code=code):
        obj=full.native();proc=regression.Process();proc.code=code
        obj.inspect=lambda _:self.fail('no inspect')
        with patch.object(n.time,'monotonic',lambda:obj.begin+1):
            self.assertRaises(l.BoundaryRefused,obj.check,proc,actual(obj))
        self.assertEqual(obj.identity_diagnostic()['exit_code'],code)
        self.assertEqual(obj.identity_diagnostic()['site'],'loop_poll')
    setattr(LoopTests,'test_poll_'+str(code).replace('-','minus'),exited)


class HandleTests(unittest.TestCase):
    def test_absent_original_handle_unknown(self):
        self.assertEqual(d.observe_handle(None),{'alive':None,'exit_code':None,'error':None})
    def test_poll_exception_fixed_enum(self):
        proc=SimpleNamespace(poll=lambda:(_ for _ in ()).throw(RuntimeError('/Users/SECRET')))
        row=d.observe_handle(proc);self.assertEqual(row['error'],'poll_other')
        self.assertNotIn('SECRET',json.dumps(row));self.assertTrue(d.handle_valid(row))

for value in (None,0,2,-9,True,False,0.,10000,'SECRET'):
    def observe(self,value=value):
        calls=[]
        def poll():calls.append(1);return value
        row=d.observe_handle(SimpleNamespace(poll=poll));self.assertEqual(calls,[1])
        self.assertTrue(d.handle_valid(row))
        if d.code_valid(value):self.assertEqual(row,{'alive':value is None,'exit_code':value,'error':None})
        else:self.assertEqual(row,{'alive':None,'exit_code':None,'error':'poll_invalid'})
    setattr(HandleTests,'test_poll_'+str(value).replace('-','minus').replace('.','dot'),observe)


class LifecycleTests(unittest.TestCase):
    def test_handle_zero_does_not_fill_unknown_cleanup(self):
        obj=prior.TerminalFirstIO();obj.inspect=lambda _:None
        def poll():return 0 if obj.calls.count('child_terminal') else None
        obj.proc.poll=poll
        _,row,seal,_=regression.run(obj)
        # Observation occurs before child_terminal; substitute solely that helper
        # to model a later zero without changing the authoritative cleanup.
        obj=prior.TerminalFirstIO();obj.inspect=lambda _:None
        with patch.object(d,'observe_handle',lambda p:{'alive':False,'exit_code':0,'error':None}):
            _,row,seal,_=regression.run(obj)
        self.assertEqual(row['handle_observation']['exit_code'],0)
        self.assertIsNone(row['cleanup']['exit_code']);self.assertFalse(row['cleanup']['identity_matched'])
        self.assertEqual(obj.proc.signals,[]);self.assertEqual(seal['verdict'],'FAIL')
    def test_pre_kill_inspection_exception_never_adds_kill(self):
        obj=prior.TerminalFirstIO(kill=True);saved=obj.inspect
        def inspect(p):
            if obj.proc.signals==['TERM']:raise psutil.NoSuchProcess(1234)
            return saved(p)
        obj.inspect=inspect
        _,row,seal,_=regression.run(obj)
        self.assertEqual(obj.proc.signals,['TERM']);self.assertEqual(seal['verdict'],'FAIL')
        self.assertEqual(row['cleanup_diagnostic']['site'],'pre_kill_inspect')
        self.assertEqual(row['cleanup_diagnostic']['inspection_error'],'no_such_process')
    def test_source_end_stage_and_primary_source_error(self):
        obj=prior.TerminalFirstIO();saved=obj.sources;calls=[]
        def sources():
            calls.append(1)
            if len(calls)>1:raise RuntimeError('SECRET')
            return saved()
        obj.sources=sources
        _,row,seal,_=regression.run(obj)
        self.assertEqual(row['failure_stage'],'source_end');self.assertEqual(row['error'],'seal')
        self.assertEqual(seal['verdict'],'FAIL');self.assertNotIn('SECRET',json.dumps(row))
    def test_unknown_cleanup_zero_observation_cannot_grant_pass(self):
        obj=prior.TerminalFirstIO();obj.inspect=lambda _:None
        obj.proc.poll=lambda:0 if obj.calls.count('child_terminal') else None
        _,row,seal,analysis=regression.run(obj)
        self.assertIs(row['cleanup']['identity_matched'],False)
        self.assertEqual(row['cleanup_diagnostic']['site'],'pre_term_match')
        self.assertEqual(obj.proc.signals,[]);self.assertEqual(seal['verdict'],'FAIL')
    def test_inspection_exception_zero_signals_and_fixed_enum(self):
        obj=prior.TerminalFirstIO()
        def fail(_):raise psutil.AccessDenied(1234)
        obj.inspect=fail
        _,row,seal,_=regression.run(obj)
        self.assertEqual(row['cleanup_diagnostic']['inspection_error'],'access_denied')
        self.assertEqual(row['cleanup_diagnostic']['site'],'pre_term_inspect')
        self.assertEqual(obj.proc.signals,[]);self.assertEqual(seal['verdict'],'FAIL')
    def test_pre_kill_mismatch_does_not_kill(self):
        obj=prior.TerminalFirstIO(kill=True);calls=[];saved=obj.inspect
        def inspect(p):
            calls.append(1)
            return dict(saved(p),pid=999) if obj.proc.signals==['TERM'] else saved(p)
        obj.inspect=inspect
        _,row,seal,_=regression.run(obj)
        self.assertEqual(obj.proc.signals,['TERM'])
        self.assertEqual(row['cleanup_diagnostic']['site'],'pre_kill_match')
        self.assertIs(row['cleanup_diagnostic']['checks']['pid'],False)
        self.assertEqual(seal['verdict'],'FAIL')
    def test_invalid_getter_raw_is_dropped(self):
        obj=prior.TerminalFirstIO();obj.identity_diagnostic=lambda:{'raw':'SECRET'}
        _,row,seal,analysis=regression.run(obj)
        self.assertIsNone(row['identity_diagnostic']);self.assertEqual(row['error'],'diagnostic')
        self.assertNotIn('SECRET',json.dumps(row));self.assertEqual(seal['verdict'],'FAIL')
    def test_nonempty_valid_diagnostic_disqualifies_parent_and_analyzer(self):
        obj=prior.TerminalFirstIO();obj.identity_diagnostic=lambda:d.project('loop_poll',exit_code=2)
        _,row,seal,_=regression.run(obj)
        self.assertEqual(row['candidate'],'FAIL');self.assertEqual(seal['verdict'],'FAIL')
        self.assertEqual(row['error'],'diagnostic');self.assertEqual(row['failure_stage'],'acceptance')


for method,site in (('expected','expected'),('ready','ready'),('http_once','http'),('ws_once','ws'),
                    ('request_finish','finish'),('child_terminal','child_terminal')):
    def stage(self,method=method,site=site):
        obj=prior.TerminalFirstIO()
        setattr(obj,method,lambda *args:(_ for _ in ()).throw(RuntimeError('SECRET')))
        _,row,seal,_=regression.run(obj)
        self.assertEqual(row['failure_stage'],site);self.assertEqual(row['candidate'],'FAIL')
        self.assertNotIn('SECRET',json.dumps(row));self.assertEqual(seal['verdict'],'FAIL')
    setattr(LifecycleTests,'test_stage_'+method,stage)

for label,index in (('ready',2),('http',3),('ws',4),('finish',5)):
    for operation in ('check','ack'):
        def checkpoint_failure(self,label=label,index=index,operation=operation):
            obj=prior.TerminalFirstIO()
            if operation=='check':
                saved=obj.check;calls=[]
                def check(*args):
                    calls.append(1)
                    if len(calls)==index:raise RuntimeError('SECRET')
                    return saved(*args)
                obj.check=check
            else:
                saved=obj.acknowledge
                def ack(current):
                    if current==label:raise RuntimeError('SECRET')
                    return saved(current)
                obj.acknowledge=ack
            _,row,seal,_=regression.run(obj)
            self.assertEqual(row['failure_stage'],operation+'_'+label)
            self.assertEqual(seal['verdict'],'FAIL');self.assertNotIn('SECRET',json.dumps(row))
        setattr(LifecycleTests,'test_'+operation+'_'+label,checkpoint_failure)


class SchemaTests(unittest.TestCase):
    def value(self):return regression.run(prior.TerminalFirstIO())[1:3]
    def test_old_schema_not_accepted(self):
        row,seal=self.value();row['schema']='hud_short_startup_backend_v1'
        self.assertFalse(a.valid(row))
        row,seal=self.value();seal['schema']='hud_short_completion_v1'
        self.assertIsNone(a.analyze(l.encode(row),seal,F,R)['evidence'])
    def test_strict_fail_schema_checked_before_early_return(self):
        obj=prior.TerminalFirstIO(2);_,row,seal,_=regression.run(obj)
        row['identity_diagnostic']={'raw':'SECRET'};payload=l.encode(row)
        seal['payload_sha256']=l.sha(payload)
        result=a.analyze(payload,seal,F,R)
        self.assertIsNone(result['evidence']);self.assertNotIn('SECRET',json.dumps(result))


MUTATIONS={
 'stage_text':lambda r:r.update(failure_stage='SECRET'),
 'stage_bool':lambda r:r.update(failure_stage=True),
 'diagnostic_raw':lambda r:r.update(identity_diagnostic={'raw':'SECRET'}),
 'cleanup_raw':lambda r:r.update(cleanup_diagnostic={'raw':'SECRET'}),
 'handle_missing':lambda r:r.update(handle_observation=None),
 'handle_raw':lambda r:r['handle_observation'].update(raw='SECRET'),
 'handle_bool':lambda r:r['handle_observation'].update(exit_code=False),
 'handle_unknown_zero':lambda r:r['handle_observation'].update(alive=None),
 'handle_alive_zero':lambda r:r['handle_observation'].update(alive=True),
 'handle_error_text':lambda r:r['handle_observation'].update(error='SECRET'),
 'handle_error_list':lambda r:r['handle_observation'].update(error=[]),
 'handle_error_with_code':lambda r:r['handle_observation'].update(error='poll_other'),
}
for name,mutate in MUTATIONS.items():
    for kind in ('PASS','FAIL'):
        def reject(self,mutate=mutate,kind=kind):
            row,seal=self.value();row['candidate']=kind;mutate(row)
            self.assertFalse(a.valid(row));payload=l.encode(row);seal['payload_sha256']=l.sha(payload)
            seal['verdict']=kind;result=a.analyze(payload,seal,F,R)
            self.assertIsNone(result['evidence']);self.assertNotIn('SECRET',json.dumps(result))
        setattr(SchemaTests,'test_'+kind+'_'+name,reject)


class ProjectionSchemaTests(unittest.TestCase):pass
for name,change in (
 ('site',{'site':'SECRET'}),('site_bool',{'site':True}),('code_bool',{'exit_code':False}),
 ('code_float',{'exit_code':0.}),('code_overflow',{'exit_code':10000}),
 ('error',{'inspection_error':'SECRET'}),('error_list',{'inspection_error':[]}),
 ('birth',{'birth_window':1}),('extra',{'raw':'SECRET'}),
 ('checks_extra',{'checks':dict.fromkeys(('pid','birth','cwd','argv','exe','raw'),None)}),
 ('checks_number',{'checks':dict.fromkeys(('pid','birth','cwd','argv','exe'),1)})):
    def reject(self,change=change):
        row=d.project('initial_inspect');row.update(change)
        self.assertFalse(d.valid(row));self.assertRaises(ValueError,d.snapshot,row)
    setattr(ProjectionSchemaTests,'test_'+name,reject)


if __name__=='__main__':
    sys.addaudithook(full.audit)
    groups=[regression.previous,regression,full,prior,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=prior.NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'V2_BOUNDED_DIAGNOSTICS_MODEL_PLUS_PRIOR300','native_execution':'NOT_RUN',
        'real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN','preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
