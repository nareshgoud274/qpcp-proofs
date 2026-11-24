import Mathlib
open IO
-- @[init] attribute: run a declared IO action when the module is imported
def act : IO Unit := FS.writeFile "/tmp/qpcp_probe_init_attr_on_import" ""
@[init act] opaque probeRef : Unit
