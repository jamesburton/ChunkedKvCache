Rows: 300 edits (3 seeds x 100), 198 distinct files, 290 distinct methods.

### Re-encoded tokens per edit (all seeds pooled)

| chunker | mean | min | p10 | p25 | median | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| symbol | 254 | 25 | 77 | 124 | 234 | 362 | 487 | 779 |
| fixed | 6590 | 12 | 265 | 460 | 842 | 2212 | 9266 | 95407 |
| edited method (incl. leading trivia) | 305 | 27 | 77 | 127 | 237 | 392 | 610 | 1578 |
| edited file (after edit) | 16298 | 249 | 610 | 1083 | 2054 | 5005 | 40937 | 136393 |

### Per seed (mean / median re-encoded tokens)

| seed | symbol mean | symbol median | fixed mean | fixed median | fixed / symbol (ratio of means) |
|---:|---:|---:|---:|---:|---:|
| 0 | 280 | 244 | 6604 | 794 | 23.62 |
| 1 | 240 | 208 | 5669 | 790 | 23.57 |
| 2 | 243 | 240 | 7497 | 939 | 30.82 |

### Paired comparison (bootstrap over files, 10,000 resamples, 95 % percentile CI)

| quantity | value | 95 % CI |
|---|---:|---|
| symbol mean re-encoded tokens | 254 | 230 .. 278 |
| fixed mean re-encoded tokens | 6590 | 1121 .. 14918 |
| fixed - symbol (mean of paired differences) | 6335 | 881 .. 14645 |
| fixed / symbol (ratio of means) | 25.90 | 4.58 .. 56.33 |
| fixed / symbol (ratio of medians) | 3.59 | 3.00 .. 5.37 |
| fixed / symbol (median of per-edit ratios) | 4.83 | 3.28 .. 6.86 |

Largest contributor: `src/CodeSharp.Tui/TuiApp.cs` (136393 tokens), 30/300 edits, 0.812 of all fixed re-encoded tokens. Without it (270 edits): symbol mean 244, fixed mean 1378, ratio of means 5.65, ratio of medians 3.34, median per-edit ratio 4.03.

Per edit: fixed re-encodes more than symbol in 271/300, the same in 4, less in 25.

### By edit kind (mean / median re-encoded tokens)

| kind | edits | token delta of file (median) | symbol mean | symbol median | fixed mean | fixed median |
|---|---:|---:|---:|---:|---:|---:|
| insert | 107 | +10 | 255 | 239 | 8902 | 762 |
| delete | 99 | -13 | 243 | 223 | 3928 | 895 |
| modify | 94 | +1 | 266 | 246 | 6761 | 908 |

### Cache hit rate after one edit

Chunk hit rate = share of the edited file's chunks still in the store; token hit rate = share of the edited file's tokens not re-encoded.

| chunker | chunks per edited file (median) | re-encoded chunks: mean / median / max | chunk hit rate, edited file (mean / median) | token hit rate, edited file (mean / median) | token hit rate, whole corpus (mean) |
|---|---:|---|---|---|---:|
| symbol | 11 | 1.03 / 1 / 2 | 0.869 / 0.909 | 0.852 / 0.903 | 0.999834 |
| fixed | 5 | 13.39 / 2 / 187 | 0.440 / 0.500 | 0.493 / 0.521 | 0.995694 |

Symbol edits re-encoding more than one chunk: 9/300. Edited methods over 512 tokens (split into several chunks): 44/300; for those, symbol re-encodes mean 407 of mean 787 method tokens.

Fixed: share of the edited file re-encoded, median 0.48 (p10 0.13, p90 1.00).

Index update time per edit (re-chunk + key one file), ms, median / p90: symbol 9.2 / 486.4, fixed 3.3 / 107.5.
