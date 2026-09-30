Datasets built with RealSWE-framework (`realswe construct`) are saved here by default, one folder per `--name`:

```text
benchmarks/
└── <name>/
    ├── tasks.jsonl      # the constructed tasks, in the same format as RealSWE-bench
    └── manifest.yaml    # the style, compositions, seed, and counts of this build
```

To save a dataset somewhere else, pass `--output-dir`:

```bash
realswe construct \
  --name my-bench \
  --bug PD \
  --feature PM \
  --output-dir /path/to/dir
```
