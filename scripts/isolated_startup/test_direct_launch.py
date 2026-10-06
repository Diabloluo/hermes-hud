"""V3 direct interpreter and cleanup regressions, entirely modeled OS/IO."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_diagnostics as old
full=old.full;regression=old.regression;l=old.l;a=old.a;n=old.n
import identity_contract as i
INPUTS=dict(old.INPUTS)
for name in ('test_direct_launch.py','identity_contract.py','native_io.py',
             'lifecycle.py','observer_smoke.py','entry.py','controller.py','analyze_integration.py'):
    INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()
OBSERVER=(HERE/'observer_smoke.py').read_bytes()
for name in full.e.FILES:
    INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()


def owned():
    obj=full.native();proc=regression.Process();obj.proc=proc
    row=old.actual(obj)
    obj.inspect=lambda _:copy.deepcopy(row)
    return obj,proc,row


class LaunchTests(unittest.TestCase):
    def test_direct_spec_uses_only_prebound_image_and_header(self):
        obj=full.native()
        spec=i.direct_launch(obj.argv,obj.home,obj.binding,obj.root)
        self.assertEqual(spec,{'argv':[obj.binding['argv0']]+obj.argv[1:],
            'executable':obj.binding['exe'],'venv_launcher':obj.binding['launcher']})
        self.assertEqual(obj.argv[0],obj.binding['launcher'])
    def test_spawn_exact_executable_env_and_one_original_handle(self):
        obj=full.native();proc=regression.Process()
        with patch.object(i,'revalidate_binding',return_value=True) as verify,\
             patch.object(n.subprocess,'Popen',return_value=proc) as popen:
            self.assertIs(obj.spawn(),proc)
            self.assertRaises(l.BoundaryRefused,obj.spawn)
        verify.assert_called_once_with(obj.binding,obj.root)
        self.assertEqual(popen.call_count,1)
        self.assertEqual(popen.call_args.args,([obj.binding['argv0']]+obj.argv[1:],))
        self.assertEqual(popen.call_args.kwargs['executable'],obj.binding['exe'])
        self.assertEqual(popen.call_args.kwargs['env']['__PYVENV_LAUNCHER__'],obj.binding['launcher'])
        self.assertFalse({'OPENAI_API_KEY','GITHUB_TOKEN','PYTHONHOME','PYTHONPATH'} &
                         set(popen.call_args.kwargs['env']))
    def test_hash_drift_has_no_popen(self):
        obj=full.native()
        with patch.object(i,'revalidate_binding',side_effect=l.BoundaryRefused('interpreter_binding')),\
             patch.object(n.subprocess,'Popen') as popen:
            self.assertRaises(l.BoundaryRefused,obj.spawn)
        popen.assert_not_called();self.assertIsNone(obj.proc)
    def test_spawn_does_not_inspect_or_adopt_child(self):
        obj=full.native();obj.inspect=lambda _:self.fail('child cannot bind launch')
        with patch.object(i,'revalidate_binding',return_value=True),\
             patch.object(n.subprocess,'Popen',return_value=regression.Process()):
            obj.spawn()
    def test_rehash_cannot_spawn_after_reserved_budget(self):
        obj=full.native()
        with patch.object(i,'revalidate_binding',return_value=True),\
             patch.object(n.time,'monotonic',lambda:obj.begin+280),\
             patch.object(n.subprocess,'Popen') as popen:
            self.assertRaises(l.BoundaryRefused,obj.spawn)
        popen.assert_not_called()
    def test_same_image_launcher_valid_without_special_wrapper_assumption(self):
        obj=full.native();obj.binding['argv0']=obj.binding['launcher'];obj.binding['exe']=obj.binding['launcher']
        self.assertEqual(i.direct_launch(obj.argv,obj.home,obj.binding,obj.root)['argv'],obj.argv)


LAUNCH_BAD={
 'old_binding_schema':lambda o:o.binding.update(schema='hud_remote_interpreter_v2'),
 'binding_extra':lambda o:o.binding.update(raw='SECRET'),
 'missing_hash':lambda o:o.binding.pop('exe_sha256'),
 'hash_bool':lambda o:o.binding.update(exe_sha256=True),
 'foreign_launcher':lambda o:o.binding.update(launcher='/FOREIGN/python'),
 'foreign_prefix':lambda o:o.binding.update(prefix='/FOREIGN/venv'),
 'relative_image':lambda o:o.binding.update(exe='relative'),
 'raw_control':lambda o:o.binding.update(argv0='/MODEL/SECRET\n'),
 'argument_tail':lambda o:o.argv.__setitem__(9,'--open'),
 'missing_isolated':lambda o:o.argv.__setitem__(1,'-O'),
 'other_observer':lambda o:o.argv.__setitem__(3,'/FOREIGN/observer.py'),
 'production_port':lambda o:o.argv.__setitem__(8,'9119'),
 'port_leading_zero':lambda o:o.argv.__setitem__(8,'050123'),
 'unicode_port':lambda o:o.argv.__setitem__(8,'５０１２３'),
 'port_overflow':lambda o:o.argv.__setitem__(8,'65536'),
 'home':lambda o:setattr(o,'home',Path('/FOREIGN/home')),
 'extra_arg':lambda o:o.argv.append('SECRET')}
for name,change in LAUNCH_BAD.items():
    def case(self,change=change):
        obj=full.native();change(obj)
        self.assertRaises(l.BoundaryRefused,i.direct_launch,obj.argv,obj.home,obj.binding,obj.root)
    setattr(LaunchTests,'test_reject_'+name,case)


class BindingTests(unittest.TestCase):
    def test_revalidate_two_bound_binary_hashes(self):
        obj=full.native();reads=[]
        def digest(path):
            reads.append(str(path));return '1'*64 if str(path)==obj.binding['launcher'] else '2'*64
        with patch.object(i.Path,'resolve',lambda p:p),patch.object(i,'digest',digest):
            self.assertIs(i.revalidate_binding(obj.binding,obj.root),True)
        self.assertEqual(reads,[obj.binding['launcher'],obj.binding['exe']])
    def test_parent_derives_headers_not_launch_path_guess(self):
        obj=full.native();actual=old.actual(obj)
        with patch.object(i,'inspect',return_value=actual),\
             patch.object(i.sys,'executable',obj.binding['launcher']),\
             patch.object(i.sys,'prefix',obj.binding['prefix']),\
             patch.object(i.sys,'orig_argv',actual['argv']),\
             patch.object(i.Path,'resolve',lambda p:p),patch.object(i,'digest',return_value='a'*64):
            result=i.bind_parent(obj.root)
        self.assertEqual(result['argv0'],actual['argv'][0]);self.assertEqual(result['exe'],actual['exe'])
        self.assertNotEqual(result['argv0'],result['launcher'])

for name,change in (
 ('launcher_drift',lambda o:o.binding.update(launcher_sha256='f'*64)),
 ('image_drift',lambda o:o.binding.update(exe_sha256='f'*64)),
 ('schema',lambda o:o.binding.update(schema='hud_remote_interpreter_v2'))):
    def case(self,change=change):
        obj=full.native();change(obj)
        def digest(path):return '1'*64 if str(path)==obj.binding['launcher'] else '2'*64
        with patch.object(i.Path,'resolve',lambda p:p),patch.object(i,'digest',digest):
            self.assertRaises(l.BoundaryRefused,i.revalidate_binding,obj.binding,obj.root)
    setattr(BindingTests,'test_reject_'+name,case)


class ContextTests(unittest.TestCase):
    def test_context_accepts_owned_venv_and_flags(self):
        obj=full.native()
        self.assertTrue(i.child_context(obj.root,obj.binding['launcher'],obj.binding['prefix'],obj.argv,1,True))
    def test_observer_checks_context_before_third_party_imports(self):
        tree=ast.parse(OBSERVER)
        boot=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='boot')
        context=next(x.lineno for x in ast.walk(boot) if isinstance(x,ast.Call)
                     and isinstance(x.func,ast.Name) and x.func.id=='child_context')
        dep=next(x.lineno for x in ast.walk(boot) if isinstance(x,ast.Import)
                 and any(y.name=='psutil' for y in x.names))
        self.assertLess(context,dep)

for index,value,name in ((0,'/FOREIGN/python','launcher'),(1,'/FOREIGN/venv','prefix'),
 (2,['/MODEL/python','-B','-I'],'argv'),(3,False,'bool_isolated'),(3,0,'nonisolated'),
 (4,1,'int_no_bytecode'),(4,False,'bytecode')):
    def case(self,index=index,value=value):
        obj=full.native();args=[obj.binding['launcher'],obj.binding['prefix'],obj.argv,1,True]
        args[index]=value;self.assertFalse(i.child_context(obj.root,*args))
    setattr(ContextTests,'test_reject_'+name,case)


class CleanupSeedTests(unittest.TestCase):
    def test_seed_recovered_after_initial_mismatch_without_adopting_image(self):
        obj,proc,row=owned();bad=dict(row,exe='/UNKNOWN')
        obj.inspect=lambda _:bad
        with patch.object(n.time,'time',lambda:100.5):
            self.assertRaises(l.BoundaryRefused,obj.expected,proc)
        seed=obj.cleanup_expected(proc)
        self.assertEqual(seed,row);self.assertNotEqual(seed['exe'],bad['exe'])
        seed['exe']='/UNKNOWN';self.assertEqual(obj.cleanup_expected(proc),row)
    def test_foreign_handle_same_pid_has_no_seed(self):
        obj,proc,row=owned()
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):obj.expected(proc)
        self.assertIsNone(obj.cleanup_expected(regression.Process()))
    def test_no_initial_inspection_seed_no_authority(self):
        obj,proc,row=owned();self.assertIsNone(obj.cleanup_expected(proc))
    def test_lifecycle_binding_failure_can_clean_final_matching_image_but_remains_fail(self):
        io=regression.IO();obj,proc,row=owned();io.proc=proc;calls=[]
        def inspect(_):
            calls.append(1);return dict(row,exe='/UNKNOWN') if len(calls)==1 else copy.deepcopy(row)
        obj.inspect=inspect;io.inspect=inspect;io.expected=obj.expected
        io.cleanup_expected=obj.cleanup_expected;io.identity_diagnostic=obj.identity_diagnostic
        with patch.object(n.time,'time',lambda:100.5):
            _,payload,seal,analysis=regression.run(io)
        self.assertTrue(payload['cleanup']['identity_matched']);self.assertEqual(proc.signals,['TERM'])
        self.assertEqual(payload['identity_diagnostic']['site'],'initial_match')
        self.assertEqual(payload['http_calls'],0);self.assertEqual(payload['ws_calls'],0)
        self.assertEqual(seal['verdict'],'FAIL');self.assertEqual(analysis['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_still_unknown_image_zero_signal(self):
        io=regression.IO();obj,proc,row=owned();io.proc=proc
        obj.inspect=lambda _:dict(row,exe='/UNKNOWN');io.inspect=obj.inspect
        io.expected=obj.expected;io.cleanup_expected=obj.cleanup_expected;io.identity_diagnostic=obj.identity_diagnostic
        with patch.object(n.time,'time',lambda:100.5):_,payload,seal,_=regression.run(io)
        self.assertEqual(proc.signals,[]);self.assertFalse(payload['cleanup']['identity_matched'])
        self.assertEqual(seal['verdict'],'FAIL')
    def test_seed_getter_exception_zero_signal(self):
        io=regression.IO();io.expected=lambda p:(_ for _ in ()).throw(RuntimeError('SECRET'))
        io.cleanup_expected=lambda p:(_ for _ in ()).throw(RuntimeError('SECRET'))
        _,payload,seal,_=regression.run(io)
        self.assertEqual(io.proc.signals,[]);self.assertNotIn('SECRET',json.dumps(payload))
        self.assertEqual(seal['verdict'],'FAIL')
    def test_bad_pid_observation_creates_no_seed(self):
        obj,proc,row=owned();obj.inspect=lambda _:dict(row,pid=999)
        with patch.object(n.time,'time',lambda:100.5):self.assertRaises(l.BoundaryRefused,obj.expected,proc)
        self.assertIsNone(obj.cleanup_expected(proc))
    def test_seed_does_not_replace_nonzero_actual_exit(self):
        obj,proc,row=owned()
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):obj.expected(proc)
        proc.code=2
        clean=l.close_owned(proc,obj.cleanup_expected(proc),obj.inspect)
        self.assertFalse(clean['identity_matched']);self.assertEqual(clean['exit_code'],2)

for field,value in (('argv',['/EVIL']),('exe','/EVIL'),('cwd','/EVIL'),('pid',999),('birth',101.0)):
    def case(self,field=field,value=value):
        obj,proc,row=owned()
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):obj.expected(proc)
        obj._cleanup_seed[field]=value
        self.assertIsNone(obj.cleanup_expected(proc))
    setattr(CleanupSeedTests,'test_seed_tampering_'+field,case)


class SchemaTests(unittest.TestCase):
    def test_old_backend_and_seal_rejected(self):
        _,row,seal,_=regression.run(old.prior.TerminalFirstIO())
        row['schema']='hud_short_startup_backend_v2';self.assertFalse(a.valid(row))
        _,row,seal,_=regression.run(old.prior.TerminalFirstIO())
        seal['schema']='hud_short_completion_v2';self.assertIsNone(a.analyze(l.encode(row),seal,old.F,old.R)['evidence'])
    def test_old_authority_schema_rejected(self):
        grant=dict(regression.AUTH,schema='hud_short_startup_backend_v2')
        self.assertFalse(l.authority_valid(grant,100.,old.F,old.R))
    def test_no_sleeps_or_additional_child_creation_in_spawn(self):
        tree=ast.parse((full.SOURCES['native_io.py']))
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='NativeIO')
        spawn=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='spawn')
        calls=[x.func.attr for x in ast.walk(spawn) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute)]
        self.assertEqual(calls.count('Popen'),1);self.assertNotIn('sleep',calls)


if __name__=='__main__':
    sys.addaudithook(full.audit)
    groups=[regression.previous,regression,full,old.prior,old,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=old.prior.NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'DIRECT_INTERPRETER_AND_PREBOUND_CLEANUP_MODEL_PLUS_PRIOR396',
        'native_execution':'NOT_RUN','real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN',
        'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
