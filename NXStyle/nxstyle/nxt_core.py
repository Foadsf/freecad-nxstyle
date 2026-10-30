# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Part Navigator's Dependencies panel on FreeCAD-Nxt's tree snapshot (no FreeCAD needed; nxt_navigator.py
shows it)."""

KINDS = {"geometry": "Geometry", "attachment": "Attachment", "expression": "Expression", "link": "Link"}


def dependencies(snapshot, name, kind_of):
    """The parents and children of object `name` from the links Nxt's dependency arrows are drawn from (its
    tree/links.arrows, by name rather than by row): two lists of (name, label, kind), kind from Nxt's
    links.kind_of. The arrows leave out a link the tree already shows by nesting (a sketch under its Pad); NX's
    Dependencies panel lists it. Nxt's snapshot has no link to an enclosing container."""
    nodes = snapshot.nodes
    node = nodes.get(name)
    if node is None:
        return [], []
    parents = []
    for other, label, _severity, _part in node.refs:
        entry = nodes.get(other)
        props = []
        for consumer, _label, consumer_props in (entry.consumers if entry is not None else ()):
            if consumer == name:
                props = list(consumer_props)
        parents.append((other, label, kind_of(props)))
    children = [(other, label, kind_of(props)) for other, label, props in node.consumers]
    return parents, children
