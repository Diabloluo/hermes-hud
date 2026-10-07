"""Fixed execution sites and exception categories; never serialize exception text or frames."""
import asyncio
from boundary_policy import BoundaryRefused

SCHEMA='hud_pair_execution_diagnostic_v1'
STAGES={'authority','active','resource','claim','initialize','fixture_read','source_start',
 'phase_control','spawn','expected','identity','ready','ack_ready','http_smoke','ack_http',
 'ws_smoke','ack_ws','transport','phase','phase_quality','checkpoint','check_finish',
 'ack_finish','request_finish','identity_diagnostic','child_terminal','source_end',
 'counts_end','samples_read','acceptance','release','pair_budget','arm_directory',
 'arm_initialize','arm_execute','freeze_end','pair_acceptance','pair_sources','pair_finish'}
KINDS={'boundary_refused','cancelled','timeout','os_error','runtime_error','value_error',
 'type_error','other','contract_rejected'}

def kind(error):
    if isinstance(error,BoundaryRefused):return 'boundary_refused'
    if isinstance(error,asyncio.CancelledError):return 'cancelled'
    if isinstance(error,TimeoutError):return 'timeout'
    if isinstance(error,OSError):return 'os_error'
    if isinstance(error,RuntimeError):return 'runtime_error'
    if isinstance(error,ValueError):return 'value_error'
    if isinstance(error,TypeError):return 'type_error'
    return 'other'

def valid(value):
    return (type(value) is dict and set(value)=={'schema','stage','kind'}
      and value['schema']==SCHEMA and type(value['stage']) is str and value['stage'] in STAGES
      and type(value['kind']) is str and value['kind'] in KINDS)

def project(stage,error):
    value={'schema':SCHEMA,'stage':stage,'kind':kind(error)}
    if not valid(value):raise ValueError('diagnostic') from None
    return value

def contract(stage):
    value={'schema':SCHEMA,'stage':stage,'kind':'contract_rejected'}
    if not valid(value):raise ValueError('diagnostic') from None
    return value
