# Proofs

One file per accepted step: `S001.lean`, `S002.lean`, and so on.

Each file proves the matching statement from `QPCP/Statements.lean`:

```lean
import QPCP.Statements

namespace QPCP.Proof

theorem S001 : QPCP.Statement.S001 := by
  sorry -- replace with a real proof

end QPCP.Proof
```

See `JOIN.md` at the repository root for the full rules.
