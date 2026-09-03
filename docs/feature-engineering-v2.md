# Feature Engineering V2

| Family | Observable concept and examples | Support/evidence limits |
|---|---|---|
| Temporal | gap quantiles, sessions, bursts, time concentration | Requires enough timestamped transactions. |
| Periodicity | median/MAD baseline, interval clusters, autocorrelation, weekly stability | Sparse activity is insufficient; spectral fields remain missing without the optional dependency. |
| Cell lifecycle | creation/consumption joins, lifetimes, turnover, censoring | Requires locally joined outpoints; unconsumed Cells are right-censored. |
| Topology | input/output shapes, fragmentation, consolidation, lock diversity | Structural only; no sender/recipient inference. |
| Templates | canonical transaction-structure recurrence | Depends on normalized Cell/script structure. |
| Scripts | lock/type family diversity and recurrence | Describes scripts, not owner identity. |
| Capacity | controlled/consumed/created capacity and repeat structure | Capacity is not interpreted as economic transfer between parties. |
| Lineage | continuation, split, merge, depth, repetition | Local observation evidence only; not a global entity graph. |
| Typed assets | xUDT recognition and strict decoding groundwork | Cached raw payloads are insufficient for supported population analysis; excluded from primary ML matrices. |

Support states are `SUPPORTED`, `PARTIAL`, `INSUFFICIENT_EVIDENCE`, and `UNRESOLVED`. Missing values mean `NOT_SUPPORTED_OR_NOT_OBSERVED`; they are not zero behaviour. Twelve transparent evidence rules remain support-qualified, label-free descriptions.
