#!/usr/bin/env python3
"""
ingest.py — Reconstruct a full project directory from a series of
"Phase N Code.py" design documents.

Rule applied throughout: when the same file OR the same function is
defined in more than one phase document, the HIGHEST phase number wins.

Two kinds of content appear in the phase docs:

  FULL   — a complete file (either pasted directly after a
           "# FILE: <path>" marker, or wrapped in a Python variable
           like `SCHEMA_SQL = '''...'''`). These become the base
           content for that path.

  SNIPPET — a later, smaller patch: usually one or more standalone
           `def name(...):` functions meant to be inserted into /
           replace a function inside an already-existing FULL file.
           These get merged into the FULL file at the function level.

Anything that is not a clean, whole function (elif-blocks to splice
into an existing function body, HTML/CSS/SQL fragments, prose
instructions) CANNOT be merged safely by a script, so it is written
out under _patches_for_review/ instead of being guessed at, and
listed in MANIFEST.md so a person can apply it by hand.
"""

import argparse
import ast
import re
import sys
from pathlib import Path

FILE_MARKER_RE = re.compile(r'^\s*(?:#|//|<!--)\s*FILE:\s*(.+?)\s*(?:-->)?\s*$', re.IGNORECASE)
FILE_CHANGED_RE = re.compile(r'^\s*#\s*File changed:\s*(.+?)\s*$', re.IGNORECASE)
BORDER_RE = re.compile(r'^\s*(#{5,}|={5,}|#\s*={5,})\s*$')
PATCH_WORDS = re.compile(
    r'\bpatch(es)?\b|\bdiff\b|only showing|minimal diff|gap clos', re.IGNORECASE
)
FILENAME_RE = re.compile(r'([A-Za-z0-9_][A-Za-z0-9_/\-]*\.(?:py|html|sql|css|js|txt))')
IN_FILE_RE = re.compile(r'\bIn\s+([A-Za-z0-9_][A-Za-z0-9_/\-]*\.(?:py|html|sql|css|js|txt))', re.IGNORECASE)
DEF_RE = re.compile(r'^def\s+(\w+)\s*\(', re.MULTILINE)


def phase_num(fname: str) -> int:
    m = re.search(r'Phase(\d+)', fname)
    return int(m.group(1)) if m else 0


def strip_border_and_blank(block_lines):
    while block_lines and (BORDER_RE.match(block_lines[0]) or not block_lines[0].strip()):
        block_lines.pop(0)
    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
    return block_lines


def split_combined_target(raw_target: str):
    """'routes/a.py + routes/b.py (stubs)' -> ['routes/a.py', 'routes/b.py']"""
    head = raw_target.split('(')[0]
    parts = [p.strip() for p in head.split(' + ')]
    return [p for p in parts if p]


def classify(desc: str, var_name: str, content: str):
    """Return 'FULL', 'SNIPPET', or 'INFO'."""
    if var_name and var_name.upper() in ('SUMMARY', 'WARNING_STATES'):
        return 'INFO'
    first_real_line = None
    for cl in content.splitlines():
        s = cl.strip()
        if not s or s.startswith('#'):
            continue
        first_real_line = s
        break
    if desc and PATCH_WORDS.search(desc):
        return 'SNIPPET'
    if var_name and ('PATCH' in var_name.upper() or var_name.upper() == 'SCHEMA_UPDATE'):
        return 'SNIPPET'
    if first_real_line and re.match(r'^def\s+\w+\(', first_real_line):
        return 'SNIPPET'
    return 'FULL'


def extract_target(ctx_text: str, content: str, nearest_file_marker: str, doc_default: str):
    # An explicit "In <path>," instruction inside the snippet's own text is
    # the most reliable signal — prefer it over anything else, including a
    # nearby FILE: marker that may belong to an earlier/different block.
    m = IN_FILE_RE.search(content)
    if m:
        return m.group(1)
    if nearest_file_marker:
        head = nearest_file_marker.split('(')[0].strip()
        if ' + ' not in head:
            return head
    m = IN_FILE_RE.search(ctx_text)
    if m:
        return m.group(1)
    m = FILENAME_RE.search(ctx_text)
    if m:
        return m.group(1)
    m = FILENAME_RE.search(content[:400])
    if m:
        return m.group(1)
    return doc_default


def unwrap_if_single_assign(span_text: str):
    """If span_text is exactly one `NAME = '''...'''` / `NAME = ""` statement,
    parse it (scoped, so escaping is handled correctly by Python itself) and
    return (var_name, inner_string). Otherwise return (None, None) meaning
    'use the raw span text as-is — it's real multi-statement file content.'"""
    stripped = span_text.strip()
    if not stripped:
        return None, None
    try:
        tree = ast.parse(stripped)
    except SyntaxError:
        return None, None
    if len(tree.body) != 1:
        return None, None
    node = tree.body[0]
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        return None, None
    val = node.value
    if isinstance(val, ast.Constant) and isinstance(val.value, str):
        return node.targets[0].id, val.value
    return None, None


def gather_blocks(upload_dir: Path):
    blocks = []
    seq = 0
    paths = sorted(upload_dir.glob("Phase*_Code.py"), key=lambda p: phase_num(p.name))
    for path in paths:
        phase = phase_num(path.name)
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()

        markers = []  # (lineno, 'FILE'|'CHANGED', text)
        for i, line in enumerate(lines, start=1):
            m = FILE_MARKER_RE.match(line)
            if m:
                markers.append((i, 'FILE', m.group(1).strip()))
                continue
            m2 = FILE_CHANGED_RE.match(line)
            if m2:
                markers.append((i, 'CHANGED', m2.group(1).strip()))

        doc_default_target = None
        for ln, kind, text in markers:
            if kind == 'CHANGED':
                doc_default_target = text

        file_markers = [(l, t) for (l, k, t) in markers if k == 'FILE']

        if file_markers:
            # ── Primary path: split the doc into spans between FILE markers.
            # Each span is either (a) one variable wrapping the whole file's
            # text, or (b) raw file content pasted directly — either way we
            # want the span's full text as ONE block, never split further.
            for idx, (ln, raw_target) in enumerate(file_markers):
                start = ln
                end = (file_markers[idx + 1][0] - 1) if idx + 1 < len(file_markers) else len(lines)
                block_lines = strip_border_and_blank(lines[start:end])
                span_text = "\n".join(block_lines)
                target_head = raw_target.split('(')[0].strip()

                # Pure group-label markers ("templates/admin/ (all admin
                # templates)") — real files come from the sub-markers right
                # after. Nothing to materialize for the label itself.
                if target_head.endswith('/'):
                    continue

                if ' + ' in target_head:
                    sub_targets = split_combined_target(raw_target)
                    split_points = []
                    for st in sub_targets:
                        pat = re.compile(r'^\s*#\s*' + re.escape(st) + r'\s*$', re.MULTILINE)
                        m = pat.search(span_text)
                        if m:
                            split_points.append((m.start(), st))
                    if len(split_points) == len(sub_targets) and split_points:
                        split_points.sort()
                        for j, (pos, st) in enumerate(split_points):
                            endpos = split_points[j + 1][0] if j + 1 < len(split_points) else len(span_text)
                            sub_lines = span_text[pos:endpos].splitlines()
                            if sub_lines and re.match(r'^\s*#\s*' + re.escape(st), sub_lines[0]):
                                sub_lines.pop(0)
                            sub_lines = strip_border_and_blank(sub_lines)
                            seq += 1
                            blocks.append(dict(phase=phase, seq=seq, doc=path.name, var=None,
                                                target=st, desc=raw_target,
                                                content="\n".join(sub_lines), kind='FULL'))
                    elif not split_points:
                        # No plain-comment split found — the sub-files are
                        # almost certainly captured separately via their own
                        # "<!-- FILE: ... -->" markers right after this
                        # group label. Nothing left to do here.
                        pass
                    else:
                        seq += 1
                        blocks.append(dict(phase=phase, seq=seq, doc=path.name, var=None,
                                            target=target_head,
                                            desc=raw_target + " [UNSPLIT COMBINED BLOCK]",
                                            content=span_text, kind='SNIPPET'))
                    continue

                var, unwrapped = unwrap_if_single_assign(span_text)
                content = unwrapped if unwrapped is not None else span_text
                kind = classify(raw_target, var, content)
                seq += 1
                blocks.append(dict(phase=phase, seq=seq, doc=path.name, var=var,
                                    target=target_head, desc=raw_target,
                                    content=content, kind=kind))
            continue

        # ── Fallback: no FILE markers anywhere in this doc (e.g. a single
        # "File changed: X" header covering several loosely-separated
        # variables). Parse the whole doc and take each top-level string
        # assignment as its own block.
        try:
            tree = ast.parse(src)
        except SyntaxError:
            tree = None
        if tree is None:
            continue

        assigns = []
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                val = node.value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    assigns.append((node.targets[0].id, val.value, node.lineno))

        prev_end = 0
        for var, content, lineno in assigns:
            ctx_start = max(prev_end, lineno - 20)
            ctx_text = "\n".join(lines[ctx_start:lineno - 1])
            prev_end = lineno

            target = extract_target(ctx_text, content, None, doc_default_target)
            kind = classify(ctx_text, var, content)

            seq += 1
            blocks.append(dict(phase=phase, seq=seq, doc=path.name, var=var,
                                target=target, desc=(doc_default_target or ""),
                                content=content, kind=kind))
    return blocks


def split_into_defs(content: str):
    """Split a snippet's content into (name, chunk_text) for each top-level
    `def name(...):` found at column 0, plus a leading 'preamble' chunk
    (name=None) for anything before the first def."""
    matches = list(DEF_RE.finditer(content))
    if not matches:
        return [(None, content)]
    chunks = []
    if matches[0].start() > 0:
        pre = content[:matches[0].start()].strip('\n')
        if pre.strip():
            chunks.append((None, pre))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        chunks.append((m.group(1), content[start:end].rstrip() + "\n"))
    return chunks


def replace_or_append_function(base_content: str, func_name: str, new_def_text: str):
    pattern = re.compile(r'^def\s+' + re.escape(func_name) + r'\s*\(.*?(?=^def\s+\w+\(|\Z)',
                          re.MULTILINE | re.DOTALL)
    if re.search(r'^def\s+' + re.escape(func_name) + r'\s*\(', base_content, re.MULTILINE):
        new_base, n = pattern.subn(new_def_text.rstrip() + "\n\n", base_content, count=1)
        return new_base, 'replaced'
    else:
        sep = "\n\n" if not base_content.endswith("\n\n") else ""
        new_base = base_content.rstrip("\n") + "\n\n\n" + new_def_text.rstrip() + "\n"
        return new_base, 'added'


def sanitize_name(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.\-]+', '_', s).strip('_')


def parse_args():
    p = argparse.ArgumentParser(
        description="Reconstruct a project directory from PhaseN_Code.py design docs "
                     "found in the current working directory (by default)."
    )
    p.add_argument("-i", "--input-dir", type=Path, default=Path.cwd(),
                    help="Folder containing PhaseN_Code.py files (default: current directory)")
    p.add_argument("-o", "--output-dir", type=Path, default=Path.cwd(),
                    help="Folder to write game/, _patches_for_review/, and MANIFEST.md into "
                         "(default: current directory)")
    return p.parse_args()


def main():
    args = parse_args()
    upload_dir = args.input_dir
    out_dir = args.output_dir
    proj_dir = out_dir / "game"
    patch_dir = out_dir / "_patches_for_review"
    manifest_path = out_dir / "MANIFEST.md"

    phase_files = sorted(upload_dir.glob("Phase*_Code.py"))
    if not phase_files:
        print(f"No PhaseN_Code.py files found in {upload_dir}", file=sys.stderr)
        sys.exit(1)

    blocks = gather_blocks(upload_dir)

    full_blocks = [b for b in blocks if b['kind'] == 'FULL' and b['target']]
    snippet_blocks = [b for b in blocks if b['kind'] == 'SNIPPET']
    info_blocks = [b for b in blocks if b['kind'] == 'INFO']
    unresolved = [b for b in blocks if b['kind'] == 'FULL' and not b['target']]

    # Pick winning FULL content per target: highest phase, then latest seq.
    best_full = {}
    for b in full_blocks:
        cur = best_full.get(b['target'])
        if cur is None or (b['phase'], b['seq']) > (cur['phase'], cur['seq']):
            best_full[b['target']] = b

    base_files = {t: b['content'] for t, b in best_full.items()}
    file_source = {t: f"Phase {b['phase']} ({b['doc']})" for t, b in best_full.items()}
    changelog = {t: [] for t in base_files}

    manual_review = []  # (target, phase, doc, var, desc, content, reason)

    for b in sorted(snippet_blocks, key=lambda x: (x['phase'], x['seq'])):
        target = b['target']
        # A later complete file already contains the final integrated version.
        # Older snippets must not be re-applied on top of it: doing so violates
        # the documented highest-phase-wins rule and can duplicate old patches.
        winning_full = best_full.get(target)
        if winning_full and b['phase'] < winning_full['phase']:
            continue
        chunks = split_into_defs(b['content'])
        for name, chunk in chunks:
            if name is None:
                has_real_code = any(
                    ln.strip() and not ln.strip().startswith('#')
                    for ln in chunk.splitlines()
                )
                if not has_real_code:
                    continue  # pure comment preamble, nothing left to apply
                manual_review.append((target, b['phase'], b['doc'], b['var'], b['desc'],
                                       chunk, "not a standalone function — needs manual placement"))
                continue
            if target and target in base_files:
                base_files[target], action = replace_or_append_function(
                    base_files[target], name, chunk)
                changelog[target].append(
                    f"- `{name}()` {action} from Phase {b['phase']} ({b['doc']}, var `{b['var']}`)")
            elif target:
                # No FULL base exists yet for this target — stash function for
                # later once (if) a base file appears, else treat as new file.
                base_files.setdefault(target, "")
                changelog.setdefault(target, [])
                base_files[target], action = replace_or_append_function(
                    base_files[target], name, chunk)
                changelog[target].append(
                    f"- `{name}()` {action} from Phase {b['phase']} ({b['doc']}, var `{b['var']}`) "
                    f"— NOTE: no FULL base file was found for this target; file may be incomplete.")
            else:
                manual_review.append((None, b['phase'], b['doc'], b['var'], b['desc'],
                                       chunk, "could not determine target file"))

    # ── Write out project files ──────────────────────────────────────────
    proj_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for target, content in sorted(base_files.items()):
        # Some phase documents place a second Python string assignment after an
        # HTML payload under the same FILE marker. Do not emit that wrapper and
        # following checklist into the rendered template.
        if target.endswith('.html') and '\n"""\n' in content:
            content = content.split('\n"""\n', 1)[0]
        # SQLite treats double-quoted "now" as an identifier in DEFAULT
        # expressions; normalize the Phase 1 schema literal for fresh installs.
        if target == 'schema.sql':
            content = content.replace('datetime("now")', "datetime('now')")
        out_path = proj_dir / target
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content.strip("\n") + "\n", encoding="utf-8")
        written.append(target)

    # ── Write out manual-review patches ──────────────────────────────────
    patch_dir.mkdir(parents=True, exist_ok=True)
    for i, (target, phase, doc, var, desc, content, reason) in enumerate(manual_review, start=1):
        tname = sanitize_name(target) if target else "UNRESOLVED"
        fname = f"phase{phase:02d}_{tname}_{sanitize_name(var or str(i))}.txt"
        out_path = patch_dir / fname
        header = (
            f"Source phase doc : {doc}\n"
            f"Likely target file: {target or '(could not be determined)'}\n"
            f"Reason flagged    : {reason}\n"
            f"Context/description from doc:\n  {desc}\n"
            f"{'-'*70}\n\n"
        )
        out_path.write_text(header + content, encoding="utf-8")

    for b in unresolved:
        fname = f"phase{b['phase']:02d}_UNRESOLVED_{sanitize_name(b['var'] or str(b['seq']))}.txt"
        (patch_dir / fname).write_text(
            f"Source phase doc : {b['doc']}\nCould not determine a target file for this block.\n"
            f"desc: {b['desc']}\n{'-'*70}\n\n{b['content']}",
            encoding="utf-8"
        )

    # ── MANIFEST ──────────────────────────────────────────────────────────
    lines = []
    lines.append("# Ingestion Manifest\n")
    lines.append(f"Generated from {len(set(b['doc'] for b in blocks))} phase documents "
                 f"in `/mnt/user-data/uploads`.\n")
    lines.append("Rule applied: for any file or function defined in more than one phase, "
                 "the **highest phase number wins**.\n")

    lines.append("\n## Files materialized (`game/`)\n")
    for target in sorted(written):
        src = file_source.get(target, "(assembled from function-level patches only)")
        lines.append(f"- `{target}` — base from {src}")
        for entry in changelog.get(target, []):
            lines.append(f"  {entry}")

    if info_blocks:
        lines.append("\n## Informational blocks (not written anywhere — reference only)\n")
        for b in info_blocks:
            lines.append(f"- `{b['var']}` from Phase {b['phase']} ({b['doc']}) — "
                         f"{b['desc'].strip()[:100]}")

    if manual_review or unresolved:
        lines.append("\n## Needs manual review (`_patches_for_review/`)\n")
        lines.append("These are instructions, HTML/CSS/SQL fragments, or mid-function "
                     "inserts (e.g. an `elif` branch to splice into an existing function) "
                     "that can't be safely auto-merged with a text script. Apply by hand, "
                     "highest phase wins if more than one touches the same spot.\n")
        for (target, phase, doc, var, desc, content, reason) in manual_review:
            tname = sanitize_name(target) if target else "UNRESOLVED"
            fname = f"phase{phase:02d}_{tname}_{sanitize_name(var or '')}.txt"
            lines.append(f"- `_patches_for_review/{fname}` → target: `{target or '???'}` "
                         f"(Phase {phase}, {reason})")
        for b in unresolved:
            fname = f"phase{b['phase']:02d}_UNRESOLVED_{sanitize_name(b['var'] or str(b['seq']))}.txt"
            lines.append(f"- `_patches_for_review/{fname}` → target: UNKNOWN (Phase {b['phase']})")

    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(written)} files to {proj_dir}")
    print(f"Wrote {len(list(patch_dir.glob('*.txt')))} manual-review patches to {patch_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
