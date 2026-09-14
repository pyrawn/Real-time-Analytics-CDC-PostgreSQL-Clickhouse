# Workload Record

The benchmark ran with the generator active throughout.

- Initial generator run: 125,177 database mutations.
- Extended generator run at 100 events/sec: 77,420 additional mutations immediately before the final benchmark.
- Total before the final five-repetition run: 202,597 INSERT/UPDATE/DELETE mutations.

The initial run was configured for one hour and stopped before the target. The
extension reused the existing PostgreSQL volume, so the counts are additive. The
final benchmark used the active pipeline rather than pausing the generator.
