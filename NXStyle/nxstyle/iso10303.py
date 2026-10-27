# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check a STEP file against ISO 10303 (no FreeCAD needed).

    python -m nxstyle.iso10303 check part.stp [--exp more.exp] [--json]
    python -m nxstyle.iso10303 entities part.stp          # what is in it, by schema and part
    python -m nxstyle.iso10303 attributes ENTITY_NAME      # the Part 21 parameter list of an entity

The dictionary (resources/iso10303/dictionary.json, built by tools/iso10303_dictionary.py) holds the
schemas of ISO 10303-42 (geometry, topology, geometric models), -43 (representation structures), -55
(procedural and hybrid representation), -108 with Technical Corrigenda 1 and 2 (parameters, constraints,
variational representations, sketches), -111 (procedural solid features) and -112 (2D sketch commands),
plus what they use from ISO 10303-41, ISO 10303-50 and ISO 13584-20 (supplement.exp). An application
protocol's own entities (product structure, ADVANCED_BREP_SHAPE_REPRESENTATION, PMI) are reported as
not checked unless its long-form EXPRESS is added with --exp.

On top of express.check() (well-formedness against the schemas), rules() evaluates the WHERE rules and
informal propositions of Parts 55, 108 and 111 that decide whether parametric and procedural data means
anything, each cited by entity and rule label. Other WHERE rules are not evaluated.
"""

import argparse
import json
import os
import sys

from . import express, p21

DICTIONARY = os.path.join(os.path.dirname(__file__), "resources", "iso10303", "dictionary.json")
PART = {  # schema -> where it is defined
    "geometry_schema": "ISO 10303-42", "topology_schema": "ISO 10303-42",
    "geometric_model_schema": "ISO 10303-42", "representation_schema": "ISO 10303-43",
    "procedural_model_schema": "ISO 10303-55", "procedural_shape_model_schema": "ISO 10303-55",
    "parameterization_schema": "ISO 10303-108", "explicit_constraint_schema": "ISO 10303-108",
    "variational_representation_schema": "ISO 10303-108",
    "explicit_geometric_constraint_schema": "ISO 10303-108", "sketch_schema": "ISO 10303-108",
    "solid_shape_element_schema": "ISO 10303-111", "procedural_sketch_schema": "ISO 10303-112",
    "support_resource_schema": "ISO 10303-41", "measure_schema": "ISO 10303-41",
    "product_property_representation_schema": "ISO 10303-41",
    "mathematical_functions_schema": "ISO 10303-50",
    "iso13584_generic_expressions_schema": "ISO 13584-20", "iso13584_expressions_schema": "ISO 13584-20",
}
_DICT = None


def dictionary(extra=()):
    """The bundled dictionary, plus any EXPRESS files given."""
    global _DICT
    if _DICT is None:
        _DICT = express.Dictionary.load(DICTIONARY)
    d = _DICT
    if extra:
        d = express.Dictionary(dict(d.entities), dict(d.types), dict(d.short_names), list(d.sources))
        for path in extra:
            with open(path, encoding="utf-8", errors="replace") as f:
                d.merge(express.Dictionary.from_text(f.read()))
    return d


# ------------------------------------------------------------------ rules of Parts 55, 108, 111
class _Model:
    """Typed access to a parsed file: entity names (with supertypes) of each instance, attribute values
    by name, and the inverse references the rules need."""

    def __init__(self, f, d):
        self.f, self.d = f, d
        self._types, self._users = {}, None

    def types(self, i):
        inst = i if isinstance(i, p21.Instance) else self.f.get(i)
        if inst is None:
            return set()
        if inst.id not in self._types:
            out = set()
            for r in inst.records:
                n = self.d.entity_name(r.name)
                if n:
                    out |= self.d.supertypes(n)
            self._types[inst.id] = out
        return self._types[inst.id]

    def isa(self, i, name):
        return name in self.types(i)

    def get(self, i, attr):
        """Value of an explicit attribute (by name, or owner.name) of an instance, simple or complex."""
        inst = i if isinstance(i, p21.Instance) else self.f.get(i)
        if inst is None:
            return None
        owner, _, name = attr.rpartition(".")
        if not inst.complex:
            n = self.d.entity_name(inst.records[0].name)
            if not n:
                return None
            for a, v in zip(self.d.attributes(n), inst.records[0].params):
                if a["name"] == name and (not owner or a["owner"] == owner):
                    return v
            return None
        within = self.d.complex_closure({self.d.entity_name(r.name) for r in inst.records} - {None})
        for r in inst.records:
            n = self.d.entity_name(r.name)
            if not n:
                continue
            for a, v in zip(self.d.attributes(n, within=within), r.params):
                if a["name"] == name and (not owner or a["owner"] == owner):
                    return v
        return None

    def users(self, ref):
        """Instances that reference ref directly."""
        if self._users is None:
            self._users = {}
            for inst in self.f:
                for r in self.f.references(inst):
                    self._users.setdefault(int(r), []).append(inst)
        return self._users.get(int(ref), [])

    def all_of(self, name):
        return [i for i in self.f if self.isa(i, name)]


def _refs(v):
    out = []
    p21._refs(v, out)
    return out


def _used_variables(m, ref, seen=None):
    """ISO 13584-20 used_variables: the generic_variable instances an expression tree uses."""
    seen = seen if seen is not None else set()
    if int(ref) in seen:
        return set()
    seen.add(int(ref))
    if m.isa(ref, "generic_variable"):
        return {int(ref)}
    out = set()
    inst = m.f.get(ref)
    if inst is not None and m.isa(inst, "generic_expression"):
        for r in m.f.references(inst):
            out |= _used_variables(m, r, seen)
    return out


def rules(f, d=None):
    """WHERE rules and propositions of Parts 55, 108 and 111 that express.check() does not evaluate."""
    d = d or dictionary()
    m = _Model(f, d)
    out = []

    def bad(inst, msg):
        out.append(express.Issue("error", inst.id, msg))

    # ISO 10303-108 clause 4 (Cor.1): parameters and their binding
    envs = {}
    for e in m.all_of("environment"):
        envs.setdefault(int(m.get(e, "syntactic_representation") or 0), []).append(e)
    for p in m.all_of("variational_parameter"):
        if m.get(p, "representation_item.name") != m.get(p, "maths_variable.name"):
            bad(p, "variational_parameter WR2: maths_variable.name differs from representation_item.name "
                   "(ISO 10303-108 Cor.1, 4.4.1)")
        mine = envs.get(p.id, [])
        want = "bound_parameter_environment" if m.isa(p, "bound_variational_parameter") else \
            "unbound_parameter_environment"
        if len(mine) != 1 or not m.isa(mine[0], want):
            bad(p, f"{want.split('_parameter')[0]}_variational_parameter WR1: its "
                   f"interpretation (the environment whose syntactic_representation it is) must be one "
                   f"{want}; found {len(mine)} (ISO 10303-108 Cor.1, 4.4.2-4.4.3)")
    for e in m.all_of("bound_parameter_environment"):
        if not m.isa(m.get(e, "semantics"), "instance_attribute_reference"):
            bad(e, "bound_parameter_environment WR1: semantics must be an instance_attribute_reference")
    for e in m.all_of("unbound_parameter_environment"):
        if not m.isa(m.get(e, "semantics"), "unbound_variational_parameter_semantics"):
            bad(e, "unbound_parameter_environment WR1: semantics must be an "
                   "unbound_variational_parameter_semantics")
    for r in m.all_of("instance_attribute_reference"):
        name, owner = m.get(r, "attribute_name"), m.get(r, "owning_instance")
        parts = name.split(".") if isinstance(name, str) else []
        if len(parts) < 3:
            bad(r, f"instance_attribute_reference: attribute_name {name!r} is not SCHEMA.ENTITY.ATTRIBUTE "
                   "(ISO 10303-108 4.4.6 informal proposition, annex F.1)")
            continue
        schema, ent, attr = parts[0].lower(), parts[1].lower(), parts[2].lower()
        if ent not in d.entities:
            bad(r, f"instance_attribute_reference: {parts[1]} is not an entity of the loaded schemas")
        elif d.entities[ent]["schema"] != schema:
            bad(r, f"instance_attribute_reference: {parts[1]} is in {d.entities[ent]['schema'].upper()}, "
                   f"not {parts[0]}")
        elif not any(a["name"] == attr for a in d.attributes(ent)):
            bad(r, f"instance_attribute_reference: {parts[1]} has no attribute {parts[2]}")
        elif owner is not None and m.types(owner) and not m.isa(owner, ent):
            bad(r, f"instance_attribute_reference: owning_instance #{int(owner)} is not a {parts[1]}")
        elif len(parts) == 3 and owner is not None and m.types(owner):
            v = m.get(owner, f"{ent}.{attr}") if any(a["owner"] == ent for a in d.attributes(ent)
                                                     if a["name"] == attr) else m.get(owner, attr)
            v = v.value if isinstance(v, p21.Typed) else v
            if v is not None and not isinstance(v, (int, float)) and v is not p21.DERIVED:
                out.append(express.Issue("warning", r.id, f"{name} of #{int(owner)} is not a number"))

    # clause 5: constraints between parameters
    for c in m.all_of("explicit_constraint"):
        cons, refs = m.get(c, "constrained_elements") or [], m.get(c, "reference_elements") or []
        if m.isa(c, "equal_parameter_constraint") and len(cons) + len(refs) < 2:
            bad(c, "equal_parameter_constraint WR1: needs at least two parameters")
        if m.isa(c, "free_form_constraint"):
            expr = m.get(c, "constraining_expression")
            used = _used_variables(m, expr) if isinstance(expr, p21.Ref) else set()
            if m.isa(c, "free_form_assignment"):
                if any(int(x) in used for x in cons):
                    bad(c, "free_form_assignment WR1: a constrained element occurs in its own expression")
                if any(int(x) not in used for x in refs):
                    bad(c, "free_form_assignment WR2: a reference element is not used by the expression")
                if not refs:
                    bad(c, "free_form_assignment WR3: needs at least one reference element")
            if m.isa(c, "free_form_relation"):
                if not m.isa(expr, "boolean_expression"):
                    bad(c, "free_form_relation WR1: the expression must be a boolean_expression")
                if any(int(x) not in used for x in list(cons) + list(refs)):
                    bad(c, "free_form_relation WR2: every element must occur in the expression")

    # clause 6: variational representations
    for rel in m.all_of("variational_current_representation_relationship"):
        r1, r2, cur = (m.get(rel, "rep_1"), m.get(rel, "rep_2"), m.get(rel, "current_result"))
        if int(cur or 0) != int(r2 or 0):
            bad(rel, "variational_current_representation_relationship WR5: current_result must be rep_2")
        c1, c2 = m.get(r1, "context_of_items"), m.get(r2, "context_of_items")
        if c1 is not None and c2 is not None and c1 != c2:
            bad(rel, "variational_current_representation_relationship WR2: the two representations must "
                     "share their context")
        items1 = {int(x) for x in m.get(r1, "items") or []}
        items2 = {int(x) for x in m.get(r2, "items") or []}
        if any(m.isa(x, "variational_representation_item") for x in items2):
            bad(rel, "variational_current_representation_relationship WR3: the current result holds "
                     "variational items")
        if {x for x in items1 if not m.isa(x, "variational_representation_item")} != items2:
            bad(rel, "variational_current_representation_relationship WR1: the non-variational items of "
                     "rep_1 must be exactly the items of the current result")
        if m.types(r1) - m.types(r2) != {"variational_representation"} or \
                m.types(r2) - m.types(r1):
            if m.isa(r2, "neutral_sketch_representation") and not m.isa(r1, "neutral_sketch_representation"):
                out.append(express.Issue("warning", rel.id, "variational_current_representation_relationship WR4 "
                           "not met: a NEUTRAL_SKETCH_REPRESENTATION wrapper could hold no constraints (its "
                           "items are points and curves, 8.4.9); the two rules of ISO 10303-108 conflict"))
            else:
                bad(rel, "variational_current_representation_relationship WR4: rep_1's type list must be "
                         "rep_2's plus variational_representation")
    holders = {}
    for rep in m.all_of("variational_representation"):
        for x in m.get(rep, "items") or []:
            holders.setdefault(int(x), []).append(rep)
    for it in m.all_of("variational_representation_item"):
        users = [u for u in m.users(it.id) if m.isa(u, "representation")]
        if any(not m.isa(u, "variational_representation") for u in users):
            bad(it, "variational_representation_item WR1: used by a representation that is not a "
                    "variational_representation (ISO 10303-108 6.3.1)")
        if not holders.get(it.id):
            out.append(express.Issue("warning", it.id, "variational item not listed in the items of any "
                                                       "variational_representation (6.3.1)"))

    # ISO 10303-55: procedural representations
    for s in m.all_of("procedural_representation_sequence"):
        el = {int(x) for x in m.get(s, "elements") or []}
        if any(int(x) not in el for x in m.get(s, "suppressed_items") or []):
            bad(s, "procedural_representation_sequence WR1: suppressed items must be elements "
                   "(ISO 10303-55 4.3.4)")
        if m.isa(s, "procedural_shape_representation_sequence"):
            for x in el:
                if m.types(x) and not (m.isa(x, "geometric_representation_item")
                                       or m.isa(x, "topological_representation_item")):
                    bad(s, f"procedural_shape_representation_sequence WR1: element #{x} is not a shape "
                           "representation item")
        if m.isa(s, "procedural_solid_representation_sequence") and not m.isa(s, "solid_model"):
            bad(s, "procedural_solid_representation_sequence WR1: SOLID_MODEL must be in its type list, i.e. "
                   "a complex instance with SOLID_MODEL() (ISO 10303-55 5.4.5)")
    for rel in m.all_of("explicit_procedural_representation_relationship"):
        r2 = m.get(rel, "rep_2")
        if m.isa(r2, "procedural_representation") or m.isa(r2, "variational_representation"):
            bad(rel, "explicit_procedural_representation_relationship WR1: rep_2 must be explicit")
        c1, c2 = m.get(m.get(rel, "rep_1"), "context_of_items"), m.get(r2, "context_of_items")
        if c1 is not None and c2 is not None and c1 != c2:
            bad(rel, "explicit_procedural_representation_relationship WR2: both representations must share "
                     "one context")
    for u in m.all_of("user_selected_shape_elements"):
        for x in m.get(u, "picked_items") or []:
            if m.types(x) and not (m.isa(x, "geometric_representation_item")
                                   or m.isa(x, "topological_representation_item")):
                bad(u, f"user_selected_shape_elements WR1: #{int(x)} is not a shape element")

    # ISO 10303-111: stepped holes (aggregate bounds given by an attribute)
    for h in m.all_of("solid_with_stepped_round_hole"):
        n = m.get(h, "segments")
        for a in ("segment_radii", "segment_depths"):
            v = m.get(h, a)
            if isinstance(n, int) and isinstance(v, list) and len(v) != n:
                bad(h, f"solid_with_stepped_round_hole: {a} has {len(v)} values for {n} segments")
    return out


def check(path_or_file, extra=()):
    """All issues: Part 21 header, schema conformance, and the rules above."""
    f = p21.read(path_or_file) if isinstance(path_or_file, str) else path_or_file
    d = dictionary(extra)
    issues = [express.Issue("info", None, n) for n in f.notes]
    issues += express.check(f, d)
    issues += rules(f, d)
    return issues


def inventory(f, d=None):
    """{standard: {entity: count}} for the instances of a file."""
    d = d or dictionary()
    out = {}
    for inst in f:
        for r in inst.records:
            n = d.entity_name(r.name)
            std = PART.get(d.schema_of(n), "other") if n else "not in the loaded schemas"
            out.setdefault(std, {})
            key = n or r.name.lower()
            out[std][key] = out[std].get(key, 0) + 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m nxstyle.iso10303", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check a STEP file")
    c.add_argument("file")
    c.add_argument("--exp", action="append", default=[], help="more EXPRESS (e.g. an AP long form)")
    c.add_argument("--json", action="store_true")
    e = sub.add_parser("entities", help="what a STEP file contains, by standard")
    e.add_argument("file")
    a = sub.add_parser("attributes", help="the Part 21 parameter list of an entity")
    a.add_argument("entity")
    args = ap.parse_args(argv)

    if args.cmd == "attributes":
        d = dictionary()
        n = d.entity_name(args.entity)
        if not n:
            print(f"{args.entity}: not in the dictionary", file=sys.stderr)
            return 2
        e = d.entities[n]
        print(f"{n.upper()} ({e['schema']}, {PART.get(e['schema'], '?')}){'  ABSTRACT' if e['abstract'] else ''}")
        print("  supertypes: " + " > ".join(reversed(d.mapping_order(n)[:-1])) if e["subtype_of"] else "")
        for i, at in enumerate(d.attributes(n), 1):
            flag = " *derived*" if at["derived"] else (" OPTIONAL" if at["optional"] else "")
            print(f"  {i:2}. {at['owner']}.{at['name']} : {d.type_text(at['type'])}{flag}")
        return 0
    try:
        f = p21.read(args.file)
    except p21.P21Error as err:
        print(f"{args.file}: not a valid ISO 10303-21 file: {err}", file=sys.stderr)
        return 2
    if args.cmd == "entities":
        for std, ents in sorted(inventory(f).items()):
            print(f"{std}: {sum(ents.values())}")
            for n, k in sorted(ents.items()):
                print(f"  {n.upper()}: {k}")
        return 0
    issues = check(f, args.exp)
    if args.json:
        print(json.dumps([{"level": i.level, "id": i.id, "message": i.message} for i in issues], indent=1))
    else:
        for i in issues:
            print(i)
        s = express.summary(issues)
        print(f"{args.file}: {len(f)} instances; {s['error']} errors, {s['warning']} warnings, {s['info']} notes")
    return 1 if any(i.level == "error" for i in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
