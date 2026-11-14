# Contributing

1. Create a branch from `main`: `feature/<short-description>`.
2. Keep each pull request to one feature or fix.
3. Before pushing, run:

   ```bash
   pytest -q
   ruff check .
   ```

4. If you changed C++, also run `bash scripts/sync_ns3.sh`, rebuild, and run `bash scripts/check_ns3.sh`.
5. Have your teammate review the pull request before merging.

## Rules that keep the project consistent

- `configs/default.yaml` is the source of truth for topology and traffic. If it changes, update the defaults in `ns3/scratch/drl-arco/drl-arco.cc` too. A test checks they match.
- The message format lives in both `routing-gym-env.cc` and `drl_arco/envs/ns3_bridge.py`. Change them together.
- Do not commit `results/` or extra checkpoints. Put final tables and figures in your report.
- Report numbers from the ns-3 backend, not the surrogate.

See [docs/STEP_BY_STEP.md](docs/STEP_BY_STEP.md#github-workflow) for the Git commands.
