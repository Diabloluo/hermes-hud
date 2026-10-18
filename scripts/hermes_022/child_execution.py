"""One synchronous official call, retained child terminal, and fail-closed exit.

All native objects must already be assembled. This function never creates a
permit, imports an SDK on its own, or converts a cleanup observation into PASS.
"""
from child_protocol import payload, seal

def execute(channel,grant,source,bridge,checkpoint,source_check,call):
    code=None;error=None;clean=False;unchanged=False;close_error=False
    try:
        row=call()
        code=row['exit_code']
        if row['result']!='CALL_RETURNED_ZERO_NOT_ACCEPTANCE':error='entry'
    except BaseException:error='entry'
    try:
        bridge_error=bridge.finish()
        error=error or bridge_error
    except BaseException:error=error or 'server'
    # Cleanup and diagnostics never short circuit merely because entry failed.
    try:unchanged=source_check()==source
    except BaseException:unchanged=False
    if not unchanged:error=error or 'source'
    try:checkpoint();clean=True
    except BaseException:error=error or 'guard'
    if code is not None and (type(code) is not int or not -255<=code<=255):code=None;error=error or 'entry'
    record=payload(grant,source,code=code,error=error,startup=bridge.startup,stopped=bridge.stopped,
                   shutdown=bridge.shutdown,unchanged=unchanged,clean=clean)
    try:channel.write_once('terminal.json',seal(record))
    except BaseException:error=error or 'terminal'
    finally:
        try:channel.close()
        except BaseException:close_error=True
    # A successfully written terminal says nothing about the later descriptor
    # close. The parent must observe this process's actual zero exit separately.
    return 0 if error is None and not close_error and record['result']=='ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE' else 2
