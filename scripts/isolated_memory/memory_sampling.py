"""Scalar/self snapshot implementation; imports inert. Never resolves trace filenames."""
import ctypes
import hashlib
from common import require
from pair_contract import values_valid

class VMInfo(ctypes.Structure):
    _pack_=4
    _fields_=[('virtual_size',ctypes.c_uint64),('region_count',ctypes.c_int32),
     ('page_size',ctypes.c_int32)]+[(k,ctypes.c_uint64) for k in (
     'resident_size','resident_size_peak','device','device_peak','internal','internal_peak',
     'external','external_peak','reusable','reusable_peak','purgeable_volatile_pmap',
     'purgeable_volatile_resident','purgeable_volatile_virtual','compressed','compressed_peak',
     'compressed_lifetime','phys_footprint')]
def self_vm():
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    lib.mach_task_self.restype=ctypes.c_uint32
    lib.task_info.argtypes=[ctypes.c_uint32,ctypes.c_int32,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    info=VMInfo();count=ctypes.c_uint32(ctypes.sizeof(info)//4)
    rc=lib.task_info(lib.mach_task_self(),22,ctypes.byref(info),ctypes.byref(count))
    require(rc==0 and count.value>=ctypes.sizeof(info)//4,'sample')
    return {k:getattr(info,k) for k in ('resident_size','phys_footprint','compressed')}
def checkpoint(trace,baseline):
    current=trace.take_snapshot();stats=current.statistics('lineno')
    deltas=[] if baseline is None else current.compare_to(baseline,'lineno')
    values={'trace_records':len(current.traces),'snapshot_bytes':sum(s.size for s in stats),
      'delta_rows':len(deltas),'net_delta_bytes':sum(s.size_diff for s in deltas),
      'top':[{'file_sha256':hashlib.sha256(s.traceback[0].filename.encode()).hexdigest(),
              'line':s.traceback[0].lineno,'bytes':s.size,'blocks':s.count} for s in stats[:25]],
      'interpretation':'filename_provenance_only_not_ownership'}
    require(values_valid(values),'checkpoint')
    return values,current if baseline is None else baseline
