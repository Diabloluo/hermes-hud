"""Injected resource models only. No actual psutil, resource IO, pipe or host."""
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
import test_optional_process as previous
import resource_diagnostics as rd
regression=previous.regression
full=previous.full
old=previous.old
l=previous.l
a=previous.a
INPUTS=dict(previous.INPUTS)
for name in full.e.FILES:INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()

class Query:
    def __init__(self,memory=rd.MEMORY_MIN,disk=rd.DISK_MIN):
        self.memory,self.disk=memory,disk
        self.calls=[]
    def virtual_memory(self):
        self.calls.append('memory')
        if isinstance(self.memory,BaseException):raise self.memory
        return SimpleNamespace(available=self.memory)
    def disk_usage(self,root):
        self.calls.append('disk')
        if root!='/MODEL/owned':raise AssertionError('ROOT_CONTRACT')
        if isinstance(self.disk,BaseException):raise self.disk
        return SimpleNamespace(free=self.disk)

def observe(memory=rd.MEMORY_MIN,disk=rd.DISK_MIN):
    q=Query(memory,disk);row=rd.collect(lambda:q,'/MODEL/owned')
    return q,row

def passed_row():return observe()[1]

class NativeModel(regression.IO):
    execution_kind='NATIVE'
    def __init__(self,row=None,ok=True):
        super().__init__()
        self.diagnostic=passed_row() if row is None else row
        self.ok=ok
    def resources(self):self.hit('resource');return self.ok
    def resource_diagnostic(self):return self.diagnostic
    def transport(self):
        return {'port':50123,'http_status':200,'http_bytes':24,'http_schema':1,
                'ws_frames':1,'ws_bytes':20,'ws_schema':1,'handshakes':1}

class AdmissionTests(unittest.TestCase):
    def test_exact_inclusive_thresholds(self):
        q,row=observe()
        self.assertTrue(rd.valid(row));self.assertTrue(rd.passed(row))
        self.assertEqual(q.calls,['memory','disk'])
        self.assertEqual(row['available_memory_bytes'],3221225472)
        self.assertEqual(row['free_disk_bytes'],5368709120)
    def test_memory_below_short_circuits_disk(self):
        q,row=observe(rd.MEMORY_MIN-1)
        self.assertEqual(q.calls,['memory']);self.assertTrue(rd.valid(row))
        self.assertEqual(row['memory_status'],'BELOW');self.assertEqual(row['disk_status'],'SKIPPED')
        self.assertIsNone(row['free_disk_bytes']);self.assertIsNone(row['error'])
        self.assertFalse(rd.passed(row))
    def test_disk_below_retains_both_measures(self):
        q,row=observe(disk=rd.DISK_MIN-1)
        self.assertEqual(q.calls,['memory','disk']);self.assertTrue(rd.valid(row))
        self.assertEqual(row['disk_status'],'BELOW');self.assertFalse(rd.passed(row))
    def test_zero_is_measurement_not_missing(self):
        q,row=observe(0)
        self.assertEqual(row['available_memory_bytes'],0);self.assertIsNone(row['free_disk_bytes'])
        self.assertEqual(q.calls,['memory']);self.assertTrue(rd.valid(row))
    def test_max_bounded_integer_supported_without_conversion(self):
        q,row=observe(rd.MAX_BYTES,rd.MAX_BYTES)
        self.assertTrue(rd.passed(row));self.assertEqual(row['free_disk_bytes'],rd.MAX_BYTES)
    def test_dependency_failure_no_queries_no_text(self):
        def load():raise ImportError('/Users/SECRET credential')
        row=rd.collect(load,'/Users/SECRET')
        self.assertTrue(rd.valid(row));self.assertEqual(row,rd.seed())
        self.assertNotIn('SECRET',json.dumps(row))
    def test_baseexception_dependency_not_swallowed(self):
        def load():raise KeyboardInterrupt('SECRET')
        self.assertRaises(KeyboardInterrupt,rd.collect,load,'/MODEL/owned')
    def test_snapshot_detached(self):
        row=passed_row();out=rd.snapshot(row);out['error']='query_error'
        self.assertIsNone(row['error']);self.assertRaises(ValueError,rd.snapshot,out)
    def test_native_thin_adapter_uses_only_fake_dependency(self):
        q=Query()
        # Native constructor remains modeled, disk argument checked separately.
        q.disk_usage=lambda root:(q.calls.append('disk') or SimpleNamespace(free=rd.DISK_MIN))
        obj=full.native()
        with patch.dict(sys.modules,{'psutil':q}):
            self.assertTrue(obj.resources())
            self.assertTrue(rd.passed(obj.resource_diagnostic()))
            obj.resource_diagnostic()['free_disk_bytes']=0
            self.assertEqual(obj.resource_diagnostic()['free_disk_bytes'],rd.DISK_MIN)
        self.assertEqual(q.calls,['memory','disk'])

INVALID_VALUES={'bool':True,'float':3.0,'negative':-1,'overflow':2**63,
                'text':'SECRET','list':[],'dict':{},'null':None}
for kind in ('memory','disk'):
    for name,value in INVALID_VALUES.items():
        def case(self,kind=kind,value=value):
            q,row=observe(value if kind=='memory' else rd.MEMORY_MIN,
                          value if kind=='disk' else rd.DISK_MIN)
            self.assertTrue(rd.valid(row));self.assertFalse(rd.passed(row))
            self.assertEqual(row['error'],'invalid_scalar')
            self.assertIsNone(row['available_memory_bytes' if kind=='memory' else 'free_disk_bytes'])
            self.assertEqual(q.calls,['memory'] if kind=='memory' else ['memory','disk'])
            self.assertNotIn('SECRET',json.dumps(row))
        setattr(AdmissionTests,'test_invalid_'+kind+'_'+name,case)
EXCEPTIONS={'permission':(PermissionError,'permission_denied'),'os':(OSError,'os_error'),
            'runtime':(RuntimeError,'query_error'),'attribute':(AttributeError,'query_error')}
for kind in ('memory','disk'):
    for name,(cls,code) in EXCEPTIONS.items():
        def case(self,kind=kind,cls=cls,code=code):
            q,row=observe(cls('SECRET /Users/private') if kind=='memory' else rd.MEMORY_MIN,
                          cls('SECRET /Users/private') if kind=='disk' else rd.DISK_MIN)
            self.assertTrue(rd.valid(row));self.assertFalse(rd.passed(row))
            self.assertEqual(row[kind+'_status'],'ERROR');self.assertEqual(row['error'],code)
            self.assertEqual(q.calls,['memory'] if kind=='memory' else ['memory','disk'])
            self.assertNotIn('SECRET',json.dumps(row))
        setattr(AdmissionTests,'test_exception_'+kind+'_'+name,case)
for kind in ('memory','disk'):
    def case(self,kind=kind):
        q=Query(KeyboardInterrupt() if kind=='memory' else rd.MEMORY_MIN,
                KeyboardInterrupt() if kind=='disk' else rd.DISK_MIN)
        self.assertRaises(KeyboardInterrupt,rd.collect,lambda:q,'/MODEL/owned')
        self.assertEqual(q.calls,['memory'] if kind=='memory' else ['memory','disk'])
    setattr(AdmissionTests,'test_baseexception_'+kind+'_propagates',case)

class LifecycleResourceTests(unittest.TestCase):
    def assert_preclaim(self,obj,row,seal):
        self.assertNotIn('claim',obj.calls);self.assertNotIn('initialization',obj.calls)
        self.assertNotIn('spawn',obj.calls);self.assertEqual(row['http_calls'],0)
        self.assertEqual(row['ws_calls'],0);self.assertIsNone(row['cleanup'])
        self.assertIsNone(row['authority_id']);self.assertEqual(seal['verdict'],'FAIL')
    def test_native_model_success_is_not_execution_receipt(self):
        obj,row,seal,analysis=regression.run(NativeModel())
        self.assertEqual(row['candidate'],'PASS');self.assertTrue(a.pass_conditions(row))
        self.assertEqual(analysis['result'],'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY')
        self.assertEqual(obj.calls.count('resource'),1)
        # This label is a model-constructed record, not actual execution.
    def test_model_omission_remains_model_only(self):
        obj,row,seal,analysis=regression.run()
        self.assertIsNone(row['resource_diagnostic'])
        self.assertEqual(analysis['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
    def test_native_resource_false_with_below_projection(self):
        obj,row,seal,analysis=regression.run(NativeModel(observe(0)[1],False))
        self.assert_preclaim(obj,row,seal)
        self.assertEqual(row['error'],'resource');self.assertEqual(row['failure_stage'],'resource')
        self.assertIsNone(row['resource_diagnostic_error']);self.assertTrue(a.valid(row))
        self.assertEqual(analysis['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_disk_and_dependency_denials_no_spawn(self):
        for diagnostic in (observe(disk=0)[1],rd.seed()):
            obj,row,seal,_=regression.run(NativeModel(diagnostic,False))
            self.assert_preclaim(obj,row,seal);self.assertTrue(a.valid(row))
    def test_false_bool_passed_projection_keeps_first_cause(self):
        obj,row,seal,_=regression.run(NativeModel(passed_row(),False))
        self.assert_preclaim(obj,row,seal);self.assertEqual(row['error'],'resource')
        self.assertEqual(row['resource_diagnostic_error'],'outcome_mismatch')
    def test_resource_baseexception_retains_no_raw(self):
        obj=NativeModel()
        obj.resources=lambda:(_ for _ in ()).throw(KeyboardInterrupt('SECRET'))
        obj,row,seal,_=regression.run(obj)
        self.assert_preclaim(obj,row,seal);self.assertEqual(row['error'],'resource')
        self.assertEqual(row['resource_diagnostic_error'],'outcome_mismatch')
        self.assertNotIn('SECRET',json.dumps(row))
    def test_native_pre_resource_failure_no_measurement_required(self):
        obj=NativeModel();obj.fail='active'
        obj,row,seal,_=regression.run(obj)
        self.assert_preclaim(obj,row,seal)
        self.assertIsNone(row['resource_diagnostic']);self.assertTrue(a.valid(row))
    def test_old_grant_and_seal_rejected(self):
        authority=copy.deepcopy(regression.AUTH);authority['schema']='hud_short_startup_backend_v5'
        self.assertFalse(l.authority_valid(authority,100.,regression.F,regression.R))
        authority=copy.deepcopy(regression.AUTH)
        authority['scope']='one_owned_optional_launchd_absence_startup_300s_http1_ws1_no_retry_no_risk_acceptance'
        self.assertFalse(l.authority_valid(authority,100.,regression.F,regression.R))
        _,row,seal,_=regression.run();seal['schema']='hud_short_completion_v5'
        self.assertIsNone(a.analyze(l.encode(row),seal,regression.F,regression.R)['evidence'])

GETTER_CASES={
 'absent':('unavailable',lambda obj:setattr(obj,'resource_diagnostic',None)),
 'null':('unavailable',lambda obj:setattr(obj,'diagnostic',None)),
 'malformed':('invalid',lambda obj:setattr(obj,'diagnostic',{'raw':'SECRET'})),
 'error':('read_failed',lambda obj:setattr(obj,'resource_diagnostic',lambda:(_ for _ in ()).throw(RuntimeError('SECRET')))),
 'interrupt':('read_failed',lambda obj:setattr(obj,'resource_diagnostic',lambda:(_ for _ in ()).throw(KeyboardInterrupt('SECRET')))),
 'below_success_bool':('outcome_mismatch',lambda obj:setattr(obj,'diagnostic',observe(0)[1])),
}
for name,(code,mutate) in GETTER_CASES.items():
    for ok in (False,True):
        def case(self,code=code,mutate=mutate,ok=ok):
            obj=NativeModel(ok=ok);mutate(obj)
            obj,row,seal,_=regression.run(obj)
            self.assert_preclaim(obj,row,seal)
            # below+False is coherent, so not a getter error in this one case.
            expected=None if code=='outcome_mismatch' and not ok else code
            self.assertEqual(row['resource_diagnostic_error'],expected)
            self.assertEqual(row['error'],'resource' if not ok else 'diagnostic')
            self.assertNotIn('SECRET',json.dumps(row));self.assertTrue(a.valid(row))
        setattr(LifecycleResourceTests,'test_getter_'+name+('_true' if ok else '_false'),case)

MUTATIONS={
 'missing':lambda x:x.pop('disk_status'),
 'extra_raw':lambda x:x.update(raw='SECRET'),
 'schema':lambda x:x.update(schema='old'),
 'memory_threshold':lambda x:x.update(memory_min_bytes=rd.MEMORY_MIN-1),
 'disk_threshold':lambda x:x.update(disk_min_bytes=rd.DISK_MIN-1),
 'bool_threshold':lambda x:x.update(memory_min_bytes=True),
 'disk_float_threshold':lambda x:x.update(disk_min_bytes=float(rd.DISK_MIN)),
 'bool_memory':lambda x:x.update(available_memory_bytes=True),
 'float_disk':lambda x:x.update(free_disk_bytes=6.0),
 'negative':lambda x:x.update(free_disk_bytes=-1),
 'overflow':lambda x:x.update(available_memory_bytes=2**63),
 'null_memory':lambda x:x.update(available_memory_bytes=None),
 'null_disk':lambda x:x.update(free_disk_bytes=None),
 'memory_status_list':lambda x:x.update(memory_status=[]),
 'disk_unknown':lambda x:x.update(disk_status='UNKNOWN'),
 'dependency_bool':lambda x:x.update(dependency_status=True),
 'error_text':lambda x:x.update(error='SECRET'),
 'error_list':lambda x:x.update(error=[]),
 'false_pass_memory':lambda x:x.update(available_memory_bytes=0),
 'false_pass_disk':lambda x:x.update(free_disk_bytes=0),
 'below_inconsistent':lambda x:x.update(memory_status='BELOW'),
 'skipped_inconsistent':lambda x:x.update(disk_status='SKIPPED'),
 'error_nonnull_value':lambda x:x.update(disk_status='ERROR',error='query_error'),
 'dependency_nonnull':lambda x:x.update(dependency_status='ERROR',error='dependency_failed'),
 'passed_error':lambda x:x.update(error='os_error'),
}
class ProjectionSchemaTests(unittest.TestCase):
    def test_fail_scalar_projection_kept_but_no_success(self):
        obj,row,seal,analysis=regression.run(NativeModel(observe(0)[1],False))
        self.assertEqual(analysis['evidence']['resource_diagnostic'],observe(0)[1])
        self.assertFalse(a.pass_conditions(row))
    def test_missing_native_projection_cannot_pass(self):
        _,row,seal,_=regression.run(NativeModel());row['resource_diagnostic']=None
        self.assertFalse(a.valid(row));self.assertFalse(a.pass_conditions(row))
    def test_secondary_error_with_extra_text_dropped_on_fail(self):
        _,row,seal,_=regression.run(NativeModel(observe(0)[1],False))
        for bad in ('SECRET',True,[],{}):
            row['resource_diagnostic_error']=bad;payload=l.encode(row)
            seal['payload_sha256']=l.sha(payload)
            self.assertIsNone(a.analyze(payload,seal,regression.F,regression.R)['evidence'])
    def test_native_early_failure_raw_projection_not_exported(self):
        obj=NativeModel();obj.fail='authority';_,row,seal,_=regression.run(obj)
        row['resource_diagnostic']={'raw':'SECRET'}
        payload=l.encode(row);seal['payload_sha256']=l.sha(payload)
        self.assertNotIn('SECRET',json.dumps(a.analyze(payload,seal,regression.F,regression.R)))
for name,mutate in MUTATIONS.items():
    def case(self,mutate=mutate):
        diagnostic=passed_row();mutate(diagnostic)
        self.assertFalse(rd.valid(diagnostic));self.assertRaises(ValueError,rd.snapshot,diagnostic)
        _,row,seal,_=regression.run(NativeModel())
        # Fail must validate before export too; this is not only PASS rejection.
        row.update(candidate='FAIL',error='resource',failure_stage='resource',resource_diagnostic=diagnostic)
        payload=l.encode(row);seal.update(verdict='FAIL',payload_sha256=l.sha(payload))
        result=a.analyze(payload,seal,regression.F,regression.R)
        self.assertIsNone(result['evidence']);self.assertNotIn('SECRET',json.dumps(result))
    setattr(ProjectionSchemaTests,'test_reject_'+name,case)

if __name__=='__main__':
    sys.addaudithook(full.audit)
    config=previous.previous
    groups=[regression.previous,regression,full,old.prior,old,config.previous,config,previous,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=old.prior.NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'INITIAL_RESOURCE_SCALAR_AND_CACHED_DIAGNOSTIC_COOPERATIVE_MODELS_PLUS_PRIOR579',
        'native_execution':'NOT_RUN','actual_resource_queries':'NOT_RUN','real_psutil_pipes':'NOT_RUN',
        'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
