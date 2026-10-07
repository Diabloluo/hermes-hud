"""Pure profile/gate models: no uname, native probe, process, network or DB."""
import unittest
from unittest.mock import patch
import entry
import controller
import lifecycle
from boundary_policy import BoundaryRefused

class ProfileTests(unittest.TestCase):
    def test_expected(self):
        self.assertTrue(entry.runner_profile_valid({'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',(3,13)))
    def test_old_scope_rejected(self):
        grant={'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':'one_remote_same_trace_pair_async_v2_100min_no_retry_no_risk_acceptance',
          'freeze_sha256':'b'*64,'review_sha256':'c'*64,'issued':100.,'expires':200.,'max_runs':1,'owner_confirmed':True}
        self.assertFalse(lifecycle.authority_valid(grant,101.,'b'*64,'c'*64))
    def test_new_scope_accepted(self):
        grant={'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':lifecycle.SCOPE,
          'freeze_sha256':'b'*64,'review_sha256':'c'*64,'issued':100.,'expires':200.,'max_runs':1,'owner_confirmed':True}
        self.assertTrue(lifecycle.authority_valid(grant,101.,'b'*64,'c'*64))
    def test_old_acceptance_rejected(self):
        a={'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':lifecycle.SCOPE,
          'freeze_sha256':'b'*64,'review_sha256':'c'*64,'issued':100.,'expires':200.,'max_runs':1,'owner_confirmed':True,
          'sha':'f'*40,'repository':'Diabloluo/hermes-hud','branch':'test/v2-isolated-memory-20261003'}
        accepted={'schema':'hud_memory_pair_review_acceptance_v2','sha':a['sha'],
          'freeze_sha256':'b'*64,'report_sha256':'c'*64,'safety':'PASS','scope':lifecycle.SCOPE}
        with self.assertRaises(BoundaryRefused):controller.gates(a,accepted,'b'*64,'c'*64,101.)
    def test_new_acceptance_accepted(self):
        a={'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':lifecycle.SCOPE,
          'freeze_sha256':'b'*64,'review_sha256':'c'*64,'issued':100.,'expires':200.,'max_runs':1,'owner_confirmed':True,
          'sha':'f'*40,'repository':'Diabloluo/hermes-hud','branch':'test/v2-isolated-memory-20261003'}
        accepted={'schema':'hud_memory_pair_review_acceptance_v3','sha':a['sha'],
          'freeze_sha256':'b'*64,'report_sha256':'c'*64,'safety':'PASS','scope':lifecycle.SCOPE}
        controller.gates(a,accepted,'b'*64,'c'*64,101.)
    def test_wrong_profile_prevents_freeze_or_setup(self):
        with patch.object(entry,'workflow_authority'),patch.object(entry.platform,'machine',return_value='arm64'),\
             patch.object(entry,'freeze_check',side_effect=AssertionError('MUST_NOT_REACH')) as frozen:
            with self.assertRaises(BoundaryRefused):entry.remote_gate(type('Args',(),{'sha':'f'*40,'grant':'a'*32,'issued':100.,'expires':200.,'review':'b'*64})())
            frozen.assert_not_called()

BAD_PROFILES=[
 ('arm_label',{'RUNNER_OS':'macOS','RUNNER_ARCH':'ARM64'},'darwin','x86_64',(3,13)),
 ('linux_label',{'RUNNER_OS':'Linux','RUNNER_ARCH':'X64'},'darwin','x86_64',(3,13)),
 ('missing_arch',{'RUNNER_OS':'macOS'},'darwin','x86_64',(3,13)),
 ('missing_os',{'RUNNER_ARCH':'X64'},'darwin','x86_64',(3,13)),
 ('arch_case',{'RUNNER_OS':'macOS','RUNNER_ARCH':'x64'},'darwin','x86_64',(3,13)),
 ('linux',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'linux','x86_64',(3,13)),
 ('arm_machine',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','arm64',(3,13)),
 ('unknown_machine',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','UNKNOWN',(3,13)),
 ('version_314',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',(3,14)),
 ('version_bool',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',(True,13)),
 ('version_list',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',[3,13]),
 ('version_extra',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',(3,13,0)),
 ('version_missing',{'RUNNER_OS':'macOS','RUNNER_ARCH':'X64'},'darwin','x86_64',None),
 ('env_wrong_type',[],'darwin','x86_64',(3,13)),
]
def make_case(args):
    def test(self):self.assertFalse(entry.runner_profile_valid(*args))
    return test
for name,*args in BAD_PROFILES:setattr(ProfileTests,'test_reject_'+name,make_case(args))
