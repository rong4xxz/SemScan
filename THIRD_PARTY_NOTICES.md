# Third-Party Notices

**SemScan artifact — provenance and licenses of the third-party source snapshots
shipped under `benchmark/`.**

This file exists to satisfy the attribution and notice obligations of the
licenses that cover the third-party code redistributed with this artifact.

---

## 0. Scope

- The root [`LICENSE`](LICENSE) applies **only** to the SemScan source code
  (`src/`, `scripts/`, `rules/`) and to documentation written by us.
- It does **not** apply to anything under `benchmark/`. Every snapshot there
  remains governed by its own upstream license, a verbatim copy of which is
  shipped inside the snapshot directory (see the *License file* column in §2).
- Nothing in this repository is intended to relicense, sublicense, or claim
  ownership of third-party code.

---

## 1. How the snapshots were obtained and verified

Each directory under `benchmark/<CVE-ID>/` is a **verbatim, unmodified copy** of
an upstream release archive or a single upstream commit. The `.git` directories
were removed from the copies, so the provenance is carried by the directory name
and by `rules/bench.jsonl`:

| Directory name pattern | Example | Meaning |
|---|---|---|
| `<project>-<version>` | `gradio-4.10.0` | upstream release tag `4.10.0` |
| `<project>-<commit-sha>` | `devika-cdfb782b0e634b773b10963c8034dc9207ba1f9f` | upstream commit `cdfb782b…` |

No source file, copyright header, `LICENSE` / `NOTICE` file, or branding asset
has been altered, added, or removed. The only files added by us are the empty
(zero-byte) marker files described in §4.

---

## 2. Inventory

30 CVE entries (see `rules/bench.jsonl`) map onto **26 physical snapshots**;
4 CVE IDs intentionally reuse a snapshot that is shared with another CVE (§4).

| CVE ID | Snapshot path | Upstream project | Ref recorded | License | License file |
|---|---|---|---|---|---|
| CVE-2023-29374 | `benchmark/CVE-2023-29374/langchain-0.0.131` | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | `0.0.131` | MIT | `LICENSE` |
| CVE-2023-51449 | `benchmark/CVE-2023-51449/gradio-4.10.0` | [gradio-app/gradio](https://github.com/gradio-app/gradio) | `4.10.0` | Apache-2.0 | `LICENSE` |
| CVE-2023-6730, CVE-2023-7018 | `benchmark/CVE-2023-6730/transformers-4.35.2` | [huggingface/transformers](https://github.com/huggingface/transformers) | `4.35.2` | Apache-2.0 | `LICENSE` |
| CVE-2024-10099 | `benchmark/CVE-2024-10099/ComfyUI-0.2.2` | [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI) | `0.2.2` | **GPL-3.0** | `LICENSE` |
| CVE-2024-11042 | `benchmark/CVE-2024-11042/InvokeAI-5.0.2` | [invoke-ai/InvokeAI](https://github.com/invoke-ai/InvokeAI) | `5.0.2` | Apache-2.0 | `LICENSE` |
| CVE-2024-11822 | `benchmark/CVE-2024-11822/dify-0.9.1` | [langgenius/dify](https://github.com/langgenius/dify) | `0.9.1` | **Apache-2.0 + additional conditions** | `LICENSE` |
| CVE-2024-11958, CVE-2024-12909 | `benchmark/CVE-2024-11958/llama_index-0.12.2` | [run-llama/llama_index](https://github.com/run-llama/llama_index) | `0.12.2` | MIT | `LICENSE` |
| CVE-2024-1879, CVE-2024-1881 | `benchmark/CVE-2024-1879/AutoGPT-0.5.0` | [Significant-Gravitas/AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) | `0.5.0` | MIT | `LICENSE` |
| CVE-2024-23731 | `benchmark/CVE-2024-23731/mem0-0.1.56` | [mem0ai/mem0](https://github.com/mem0ai/mem0) | `0.1.56` | Apache-2.0 | `LICENSE` |
| CVE-2024-28088 | `benchmark/CVE-2024-28088/langchain-0.1.10` | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | `0.1.10` | MIT | `LICENSE` |
| CVE-2024-3095 | `benchmark/CVE-2024-3095/langchain-0.1.5` | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | `0.1.5` | MIT | `LICENSE` |
| CVE-2024-3271 | `benchmark/CVE-2024-3271/llama_index-0.10.23` | [run-llama/llama_index](https://github.com/run-llama/llama_index) | `0.10.23` | MIT | `LICENSE` |
| CVE-2024-34359 | `benchmark/CVE-2024-34359/llama-cpp-python-0.2.71` | [abetlen/llama-cpp-python](https://github.com/abetlen/llama-cpp-python) | `0.2.71` | MIT | `LICENSE.md` |
| CVE-2024-4941 | `benchmark/CVE-2024-4941/gradio-4.25.0` | [gradio-app/gradio](https://github.com/gradio-app/gradio) | `4.25.0` | Apache-2.0 | `LICENSE` |
| CVE-2024-6331 | `benchmark/CVE-2024-6331/devika-cdfb782b0e634b773b10963c8034dc9207ba1f9f` | [stitionai/devika](https://github.com/stitionai/devika) | commit `cdfb782b0e634b773b10963c8034dc9207ba1f9f` | MIT | `LICENSE` |
| CVE-2024-8953, CVE-2024-8958 | `benchmark/CVE-2024-8953/composio-0.4.3` | [ComposioHQ/composio](https://github.com/ComposioHQ/composio) | `0.4.3` | **Elastic License 2.0** | `LICENSE` |
| CVE-2024-9053 | `benchmark/CVE-2024-9053/vllm-0.6.0` | [vllm-project/vllm](https://github.com/vllm-project/vllm) | `0.6.0` | Apache-2.0 | `LICENSE` |
| CVE-2025-1040 | `benchmark/CVE-2025-1040/AutoGPT-autogpt-platform-beta-v0.3.4` | [Significant-Gravitas/AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) | tag `autogpt-platform-beta-v0.3.4` | **MIT (`classic/`) + Polyform Shield (`autogpt_platform/`)** | `LICENSE` |
| CVE-2025-24357 | `benchmark/CVE-2025-24357/vllm-0.6.6` | [vllm-project/vllm](https://github.com/vllm-project/vllm) | `0.6.6` | Apache-2.0 | `LICENSE` |
| CVE-2025-25362 | `benchmark/CVE-2025-25362/spacy-llm-0.7.2` | [explosion/spacy-llm](https://github.com/explosion/spacy-llm) | `0.7.2` | MIT | `LICENSE` |
| CVE-2025-64511 | `benchmark/CVE-2025-64511/MaxKB-2.3.0` | [1Panel-dev/MaxKB](https://github.com/1Panel-dev/MaxKB) | `2.3.0` | **GPL-3.0** | `LICENSE` |
| CVE-2025-65958 | `benchmark/CVE-2025-65958/open-webui-0.6.36` | [open-webui/open-webui](https://github.com/open-webui/open-webui) | `0.6.36` | **BSD-3-Clause + branding clause** | `LICENSE` |
| CVE-2026-0761 | `benchmark/CVE-2026-0761/MetaGPT-11cdf466d042aece04fc6cfd13b28e1a70341b1f` | [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT) (formerly `geekan/MetaGPT`) | commit `11cdf466d042aece04fc6cfd13b28e1a70341b1f` | MIT | `LICENSE` |
| CVE-2026-0766 | `benchmark/CVE-2026-0766/open-webui-0.7.2` | [open-webui/open-webui](https://github.com/open-webui/open-webui) | `0.7.2` | **BSD-3-Clause + branding clause** | `LICENSE` |
| CVE-2026-22807 | `benchmark/CVE-2026-22807/vllm-0.13.0` | [vllm-project/vllm](https://github.com/vllm-project/vllm) | `0.13.0` | Apache-2.0 | `LICENSE` |
| CVE-2026-24123 | `benchmark/CVE-2026-24123/BentoML-1.4.33` | [bentoml/BentoML](https://github.com/bentoml/BentoML) | `1.4.33` | Apache-2.0 | `LICENSE` |

**Summary:** 19 of 26 snapshots are under unmodified permissive licenses
(10 × MIT, 9 × Apache-2.0). The remaining 7 snapshots (marked in **bold**)
carry copyleft, source-available, or additional terms and are described in §3.

---

## 3. Licenses with non-standard or additional terms

### 3.1 GPL-3.0 — ComfyUI-0.2.2, MaxKB-2.3.0

- Redistribution in source form is granted, provided that (a) all copyright and
  license notices are retained, (b) the complete corresponding source is made
  available, and (c) modifications are marked and dated.
- We redistribute these trees **unmodified**, and their `LICENSE` files are
  present in the snapshot, so (a)–(c) are satisfied. If you modify a snapshot,
  you must license and mark the modified files under GPL-3.0.
- These programs are distributed as separate, self-contained directories
  ("mere aggregation"). They are independent works and their copyleft does not
  extend to the SemScan code in `src/`, which is not linked with nor derived
  from them.
- Not AGPL: there is no network-service copyleft clause, so merely running these
  programs (including as a service during artifact evaluation) does not create
  additional obligations.

### 3.2 Elastic License 2.0 (ELv2) — composio-0.4.3

Two CVE entries share this snapshot. ELv2 is a source-available (non-OSI)
license. It permits use, copy, distribution, and modification subject to three
limitations: you may not (i) provide the software to others as a hosted or
managed service, (ii) circumvent any license-key or protected functionality, or
(iii) remove or obscure licensing notices. This snapshot is redistributed
unmodified with its `LICENSE` intact; it is not offered to any third party as a
hosted or managed service.

### 3.3 Polyform Shield — `autogpt_platform/` inside the AutoGPT platform snapshot

The AutoGPT snapshot (CVE-2025-1040) is dual-licensed: the `classic/` subtree is
MIT, while the `autogpt_platform/` subtree is under the **Polyform Shield
License**, which permits use for any purpose other than providing a product that
competes with the licensor's. It is included here for vulnerability research and
reproduction only. Note the top-level `LICENSE` file of that snapshot states this
split explicitly.

### 3.4 Apache-2.0 with additional conditions — dify-0.9.1

Dify's license is Apache-2.0 plus conditions that restrict *use* rather than
redistribution: operating a multi-tenant environment based on the source code
requires a commercial license, and the Dify LOGO / copyright information in the
frontend components may not be removed or modified. Accordingly, this snapshot
has not been sanitized or de-branded in any way. Apache-2.0 §6 does not grant
any trademark rights.

### 3.5 BSD-3-Clause with a branding clause — open-webui-0.6.36, open-webui-0.7.2

Open WebUI's license is BSD-3-Clause with an additional material condition:
licensees must not alter, remove, obscure, or replace any "Open WebUI" branding
(name, logo, or other identifiers) in any deployment or distribution, regardless
of user count. Limited exceptions apply (deployments with ≤50 end users in a
rolling 30-day window, official contributors with written permission, or an
enterprise license). The branding assets in these snapshots are therefore
retained verbatim; do not strip them if you re-package or deploy these trees.

---

## 4. Zero-byte marker files (shared snapshots)

For CVE IDs whose affected code base is identical to another CVE in the corpus,
the directory contains a single empty marker file instead of a duplicate copy:

| Marker file | Points to |
|---|---|
| `benchmark/CVE-2023-7018/代码库与CVE-2023-6730一致` | the `transformers-4.35.2` snapshot |
| `benchmark/CVE-2024-12909/代码库与CVE-2024-11958一致` | the `llama_index-0.12.2` snapshot |
| `benchmark/CVE-2024-1881/代码库与CVE-2024-1879一致` | the `AutoGPT-0.5.0` snapshot |
| `benchmark/CVE-2024-8958/代码库与CVE-2024-8953一致` | the `composio-0.4.3` snapshot |

These empty files contain no third-party content; `rules/bench.jsonl` resolves
them to the shared snapshot.

---

## 5. Nested license files inside the snapshots

Several snapshots contain additional `LICENSE` / `COPYING` files in
subdirectories (for example `langchain-0.1.10/libs/*/LICENSE` and
`langchain-0.1.10/templates/*/LICENSE`, and per-package licenses inside the
`llama_index` package collection). Those files govern the corresponding
subdirectory and take precedence over the top-level license for that subtree.
All of them are retained unmodified. To enumerate them:

```bash
find benchmark -iname 'LICENSE*' -o -iname 'COPYING*' | sort
```

Copyright in each snapshot belongs to its respective upstream authors and
owners, as stated in the `LICENSE`, `NOTICE`, `CITATION.cff` and source file
headers included in that snapshot.

---

## 6. Contact

For attribution corrections, license questions, or takedown requests, please
contact the artifact authors at `2324923940@qq.com`, or open an issue on this
repository. Valid takedown requests concerning third-party code will be honored
by removing the affected snapshot.

---

## 7. Reproducing this inventory

The CVE → snapshot mapping is authoritative in `rules/bench.jsonl`
(`repo_path` field):

```bash
python3 -c "
import json, os
for line in open('rules/bench.jsonl'):
    d = json.loads(line)
    print(d['index'], '->', d['repo_path'], 'EXISTS' if os.path.isdir(d['repo_path']) else 'MISSING')
"
```

Check the license of any individual snapshot with:

```bash
head -3 benchmark/<CVE-ID>/<snapshot-name>/LICENSE
```
