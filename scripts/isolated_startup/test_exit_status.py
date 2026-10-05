"""B1 regression: self-reported child PASS cannot override real wait status.

Every process and IO here is an in-memory model. No host, psutil, native pipe,
socket, DB, gate or signal is used. The terminal-first fixture deliberately
models a PASS record written BEFORE the interpreter's actual wait result.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_backend as full

l,a,regression=full.l,full.a,full.regression
F,R,AUTH=full.F,full.R,full.AUTH
INPUTS=dict(full.INPUTS)
INPUTS['test_exit_status.py']=hashlib.sha256((HERE/'test_exit_status.py').read_bytes()).hexdigest()


class FinalExitProcess(regression.Process):
    def __init__(self,exit_code,kill=False):
        super().__init__();self.final_code=exit_code;self.timeout=kill
    def terminate(self):
        self.signals.append('TERM')
        if not self.timeout:self.code=self.final_code
    def kill(self):
        self.signals.append('KILL');self.code=self.final_code


class TerminalFirstIO(regression.IO):
    def __init__(self,code=0,kill=False,kind='MODEL'):
        super().__init__();self.proc=FinalExitProcess(code,kill);self.execution_kind=kind
        self.early=None
    def request_finish(self):
        super().request_finish()
        self.early=self.child.terminal(regression.SOURCE,True,0)
    def child_terminal(self):
        self.hit('child_terminal');return copy.deepcopy(self.early)
    def transport(self):
        return {'port':50123,'http_status':200,'http_bytes':24,'http_schema':1,
                'ws_frames':1,'ws_bytes':20,'ws_schema':1,'handshakes':1}


class ParentExitTests(unittest.TestCase):
    pass


for kind in ('MODEL','NATIVE'):
    for code in (1,2,255,-1,-9,-15):
        def nonzero(self,kind=kind,code=code):
            obj=TerminalFirstIO(code,kind=kind)
            _,row,seal,analysis=regression.run(obj)
            self.assertEqual(obj.early['candidate'],'PASS')
            self.assertEqual(row['child']['exit_code'],0)
            self.assertEqual(row['cleanup']['exit_code'],code)
            self.assertTrue(row['cleanup']['identity_matched'])
            self.assertFalse(row['cleanup']['alive'])
            self.assertIsNone(row['cleanup']['error']) # cleanup succeeded, acceptance must not.
            self.assertEqual(row['candidate'],'FAIL');self.assertEqual(seal['verdict'],'FAIL')
            self.assertEqual(analysis['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
            self.assertEqual(analysis['error'],'execution_failed')
            self.assertTrue(obj.claimed);self.assertEqual(obj.calls.count('spawn'),1)
            self.assertEqual(obj.proc.signals,['TERM'])
            self.assertEqual(row['memory_risk'],'WARN_NOT_ACCEPTED');self.assertEqual(row['public_release'],'BLOCK')
        setattr(ParentExitTests,'test_nonzero_'+kind+'_'+str(code).replace('-','minus'),nonzero)
    def killed(self,kind=kind):
        obj=TerminalFirstIO(-9,kill=True,kind=kind)
        _,row,seal,analysis=regression.run(obj)
        self.assertEqual(obj.early['candidate'],'PASS');self.assertEqual(obj.proc.signals,['TERM','KILL'])
        self.assertEqual(row['cleanup']['exit_code'],-9);self.assertTrue(row['cleanup']['identity_matched'])
        self.assertEqual(row['candidate'],'FAIL');self.assertEqual(seal['verdict'],'FAIL')
        self.assertEqual(analysis['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED');self.assertTrue(obj.claimed)
    setattr(ParentExitTests,'test_term_timeout_kill_not_pass_'+kind,killed)
    def zero(self,kind=kind):
        obj=TerminalFirstIO(0,kind=kind);_,row,seal,analysis=regression.run(obj)
        self.assertEqual(row['child']['exit_code'],0);self.assertEqual(row['cleanup']['exit_code'],0)
        self.assertEqual(row['candidate'],'PASS');self.assertEqual(seal['verdict'],'PASS')
        expected=('VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY' if kind=='MODEL' else
                  'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY')
        self.assertEqual(analysis['result'],expected)
        self.assertEqual(analysis['memory_risk'],'WARN_NOT_ACCEPTED');self.assertEqual(analysis['public_release'],'BLOCK')
    setattr(ParentExitTests,'test_matching_zero_control_'+kind,zero)
    def mismatch(self,kind=kind):
        obj=TerminalFirstIO(0,kind=kind);base=obj.child_terminal
        def terminal():
            row=base();row['exit_code']=2;return row
        obj.child_terminal=terminal
        _,row,seal,analysis=regression.run(obj)
        self.assertEqual(row['cleanup']['exit_code'],0);self.assertEqual(row['child']['exit_code'],2)
        self.assertEqual(row['candidate'],'FAIL');self.assertEqual(seal['verdict'],'FAIL')
        self.assertEqual(analysis['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    setattr(ParentExitTests,'test_child_actual_disagreement_'+kind,mismatch)


class AnalyzerExitTests(unittest.TestCase):
    def value(self,kind):
        obj,row,seal,_=regression.run(TerminalFirstIO(kind=kind))
        self.assertEqual(row['candidate'],'PASS');return row,seal
    def reject(self,kind,actual,child_code=0):
        row,seal=self.value(kind)
        row['cleanup']['exit_code']=actual;row['child']['exit_code']=child_code
        payload=l.encode(row);seal['payload_sha256']=hashlib.sha256(payload).hexdigest()
        result=a.analyze(payload,seal,F,R)
        self.assertEqual(result['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
        self.assertIsNone(result['evidence'])
        self.assertEqual(result['memory_risk'],'WARN_NOT_ACCEPTED');self.assertEqual(result['public_release'],'BLOCK')


class NoSourceTracebackResult(unittest.TextTestResult):
    def _exc_info_to_string(self,err,test):
        # unittest's default failure formatter opens source files via linecache.
        # Keep failure counting intact without broadening the no-open audit hook.
        return ('MODEL_ASSERTION_FAILED' if isinstance(err[1],AssertionError)
                else 'MODEL_UNEXPECTED_EXCEPTION')


BAD=(('one',1),('two',2),('max',255),('kill',-9),('term',-15),
     ('bool_false',False),('bool_true',True),('float_zero',0.),('none',None),('text','0'))
for kind in ('MODEL','NATIVE'):
    for name,code in BAD:
        def reject(self,kind=kind,code=code):self.reject(kind,code)
        setattr(AnalyzerExitTests,'test_actual_exit_'+kind+'_'+name,reject)
    for code in (2,-9):
        def disagree(self,kind=kind,code=code):self.reject(kind,0,code)
        setattr(AnalyzerExitTests,'test_child_disagreement_'+kind+'_'+str(code).replace('-','minus'),disagree)


if __name__=='__main__':
    sys.addaudithook(full.audit)
    groups=[regression.previous,regression,full,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'B1_TERMINAL_BEFORE_ACTUAL_EXIT_MODEL_PLUS_PRIOR258',
        'native_execution':'NOT_RUN','real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN',
        'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
